"""Chat endpoint emitting Vercel AI SDK v5 UI Message Stream (SSE).

Wire format (SSE events, `data: {json}\\n\\n` per event):
    data: {"type":"start"}                          # message start
    data: {"type":"start-step"}                     # step start
    data: {"type":"text-start","id":"text-0"}       # text part begin
    data: {"type":"text-delta","id":"text-0","delta":"..."}  # text content
    data: {"type":"text-end","id":"text-0"}         # text part end
    data: {"type":"finish-step"}                    # step end
    data: {"type":"finish","finishReason":"stop"}   # message finish
    data: [DONE]                                    # stream end sentinel

This is what `useChat` from @ai-sdk/react v5 (DefaultChatTransport) consumes.
Parsed client-side by parseJsonEventStream (EventSourceParserStream) +
uiMessageChunkSchema (zod). NOT the old `0:"token"` Data Stream Protocol.

BYOK (Bring Your Own Key) — three-stage independent credentials:
    Clients send a single `X-Provider-Config` header carrying a JSON-serialized
    ProviderConfig { draft: StageConfig, refine: StageConfig, evaluate: StageConfig }.
    Each StageConfig carries its own api_base / api_key / model / extra_headers
    so the three pipeline stages can target different providers. When the
    header is absent, the backend falls back to .env LLM credentials
    (unless BYOK_FALLBACK_TO_ENV=false).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any, AsyncIterator, Dict, List

import litellm
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.llm.clients import _redact_key, _validate_api_base
from app.pipeline import stream_pipeline
from app.schemas.chat import ProviderConfig, StageConfig

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    """Accepts both OpenAI-style (`content: str`) and AI SDK v5 (`parts: [...]`) formats.

    AI SDK v5 (`@ai-sdk/react@2.x`) sends `parts:[{type:"text",text:"..."}]`
    instead of `content:str`. We collapse text parts into a single `content`
    string so the pipeline downstream only deals with one shape.
    """

    role: str
    content: str | None = None
    parts: List[Dict[str, Any]] | None = None
    # AI SDK v5 also sends `id`, `createdAt`, etc. — ignore silently.
    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _normalize_content(self) -> "ChatMessage":
        if self.content is None:
            if self.parts:
                text_chunks = [
                    p.get("text", "")
                    for p in self.parts
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                self.content = "".join(text_chunks)
            else:
                self.content = ""
        return self


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(
        ...,
        description="OpenAI-style or AI SDK v5 messages",
        max_length=100,
    )
    # AI SDK may send these; accepted but not used by the pipeline (it has
    # its own temperature/max_tokens settings per stage). Ignored silently.
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool | None = None
    task_type: str | None = None  # "generate" | "continue" | "rewrite" | "polish" | "outline"

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _validate_message_lengths(self) -> "ChatRequest":
        total_chars = sum(len(m.content or "") for m in self.messages)
        if total_chars > 100_000:
            raise ValueError(
                f"Total message content exceeds 100KB limit ({total_chars} chars)"
            )
        return self


def _extract_topic(messages: List[ChatMessage]) -> str:
    """Use the last user message as the pipeline topic.

    Strips internal routing tags ([novel:N], [task:TYPE]) so the LLM
    only sees the actual user-facing prompt text.
    """
    for msg in reversed(messages):
        if msg.role == "user" and msg.content.strip():
            text = msg.content.strip()
            # Strip routing tags that are not meant for the LLM.
            text = re.sub(r"\[novel:\d+\]\s*", "", text)
            text = re.sub(r"\[task:\w+\]\s*", "", text)
            return text.strip()
    return ""


def _extract_task_type(messages: List[ChatMessage], explicit: str | None = None) -> str:
    """Extract task_type from explicit param or message content markers."""
    if explicit:
        return explicit
    for msg in reversed(messages):
        if msg.role != "user" or not msg.content:
            continue
        # Support [task:TYPE] marker
        m = re.search(r"\[task:(\w+)\]", msg.content)
        if m:
            return m.group(1)
        break
    return "generate"


# --- SSE encoding (AI SDK v5 UI Message Stream protocol) -------------------
#
# Wire format: `data: {json}\n\n` per SSE event, terminated by `data: [DONE]\n\n`.
# The AI SDK v5 DefaultChatTransport uses EventSourceParserStream + uiMessageChunkSchema
# to parse this. See:
#   - ai@5.x: src/ui-message-stream/ui-message-chunks.ts (schema)
#   - @ai-sdk/provider-utils: parseJsonEventStream (SSE parser)
#
# Lifecycle for a text-only response:
#   start → start-step → text-start → text-delta* → text-end → finish-step → finish → [DONE]

_TEXT_PART_ID = "text-0"  # single text part; fixed ID is sufficient


def _sse(data: dict | str) -> str:
    """Encode one SSE event: `data: {json}\\n\\n` or `data: [DONE]\\n\\n`."""
    if isinstance(data, str):
        return f"data: {data}\n\n"
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _encode_start() -> str:
    return _sse({"type": "start"})


def _encode_start_step() -> str:
    return _sse({"type": "start-step"})


def _encode_text_start() -> str:
    return _sse({"type": "text-start", "id": _TEXT_PART_ID})


def _encode_text_delta(token: str) -> str:
    return _sse({"type": "text-delta", "id": _TEXT_PART_ID, "delta": token})


def _encode_text_end() -> str:
    return _sse({"type": "text-end", "id": _TEXT_PART_ID})


def _encode_finish_step() -> str:
    return _sse({"type": "finish-step"})


def _encode_finish() -> str:
    """Finish event + [DONE] sentinel that closes the SSE stream."""
    return _sse({"type": "finish", "finishReason": "stop"}) + _sse("[DONE]")


def _encode_error(message: str) -> str:
    return _sse({"type": "error", "errorText": message})


async def _extract_provider_config(
    x_provider_config: Annotated[str | None, Header(alias="X-Provider-Config")] = None,
) -> ProviderConfig | None:
    """Parse BYOK credentials from the X-Provider-Config JSON header.

    The header carries a JSON-serialized ProviderConfig with three
    StageConfig objects (draft / refine / evaluate). Returns None if the
    header is absent (signals: use .env fallback). Raises HTTPException
    422 if the header is present but malformed — prevents silent fallback
    to .env credentials when the user intended BYOK.
    """
    if not x_provider_config:
        return None
    try:
        data = json.loads(x_provider_config)
        return ProviderConfig.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning("Invalid X-Provider-Config JSON: %s", _redact_key(str(e)))
        raise HTTPException(
            status_code=422,
            detail=f"Invalid X-Provider-Config header: {e}",
        )


async def _event_stream(
    topic: str,
    provider_config: ProviderConfig | None,
    session=None,
    novel_id: int | None = None,
    task_type: str = "generate",
) -> AsyncIterator[str]:
    """Runs the pipeline and emits AI SDK v5 UI Message Stream SSE events.

    Lifecycle: start → start-step → text-start → text-delta* → text-end →
    finish-step → finish → [DONE].

    Constructs a ReviewMatrixRunner so the evaluate node runs the
    multi-dimensional review (coherence / character_consistency / prose /
    plot_logic / world_consistency / cross_chapter_consistency) in parallel
    instead of the single-evaluator path. The runner is constructed per
    request (stateless) and gated behind the `pipeline_multi_dim_eval` flag
    so deployments can opt out.

    Branches on litellm exception types so the frontend can show a useful
    message. All log lines are passed through `_redact_key` to scrub any
    `sk-...` tokens that might appear in exception strings.
    """
    text_started = False
    try:
        yield _encode_start()
        yield _encode_start_step()
        # stream_pipeline runs the full pipeline (draft→refine→evaluate loop→
        # safety_check) to completion, THEN yields text chunks. If the pipeline
        # fails, it raises before any chunk is yielded, so text-start won't be emitted.
        evaluator = _build_evaluator()
        async for token in stream_pipeline(
            topic, provider_config,
            session=session, evaluator=evaluator, novel_id=novel_id,
            task_type=task_type,
        ):
            if not text_started:
                yield _encode_text_start()
                text_started = True
            yield _encode_text_delta(token)
        if text_started:
            yield _encode_text_end()
        if not text_started:
            # Pipeline completed but produced no text — likely a silent failure
            # inside stream_pipeline (exception swallowed, LLM returned empty, etc.)
            if task_type == "extract":
                yield _encode_error(
                    "AI 提取未返回任何内容。请检查：1) 设置中测试连接是否通过 2) 模型是否支持 JSON 输出"
                )
            else:
                yield _encode_error("AI 未返回任何内容，请检查 API Key 配置或重试")
        yield _encode_finish_step()
    except litellm.AuthenticationError as e:
        logger.error("LLM auth failed: %s", _redact_key(str(e)))
        if text_started:
            yield _encode_text_end()
        yield _encode_error("API Key 无效，请检查配置中对应阶段的 Key 是否正确")
    except litellm.APIConnectionError as e:
        logger.error("LLM connection failed: %s", _redact_key(str(e)))
        if text_started:
            yield _encode_text_end()
        yield _encode_error("无法连接到 API Base URL，请检查网络和 URL 配置")
    except litellm.NotFoundError as e:
        logger.error("LLM model not found: %s", _redact_key(str(e)))
        if text_started:
            yield _encode_text_end()
        yield _encode_error("模型不存在，请检查模型名称是否正确")
    except litellm.BadRequestError as e:
        logger.error("LLM bad request: %s", _redact_key(str(e)))
        if text_started:
            yield _encode_text_end()
        yield _encode_error("请求被拒绝，请检查 model 名")
    except ValueError as e:
        # SSRF rejection from _validate_api_base surfaces here.
        logger.error("Provider config rejected: %s", _redact_key(str(e)))
        if text_started:
            yield _encode_text_end()
        yield _encode_error("API Base URL 不被允许")
    except Exception as e:
        # Use logger.error (not exception) to avoid leaking sensitive data
        # (API keys, internal URLs) that may appear in stack traces.
        logger.error("Pipeline failed mid-stream: %s: %s", type(e).__name__, e)
        if text_started:
            yield _encode_text_end()
        yield _encode_error("Pipeline 出错，请重试")
    finally:
        yield _encode_finish()


@router.post("/v1/chat")
async def chat(
    req: ChatRequest,
    provider_config: Annotated[
        ProviderConfig | None, Depends(_extract_provider_config)
    ],
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Runs the three-stage pipeline and streams the final answer."""
    topic = _extract_topic(req.messages)
    if not topic:
        # Short-circuit: nothing to do.
        async def _empty() -> AsyncIterator[str]:
            yield _encode_start()
            yield _encode_finish()

        return StreamingResponse(
            _empty(),
            media_type="text/event-stream",
            headers=_sse_headers(),
        )

    novel_id = _extract_novel_id(req.messages)
    task_type = _extract_task_type(req.messages, req.task_type)

    if provider_config is None and not settings.byok_fallback_to_env:
        # BYOK required but no credentials supplied.
        async def _no_credentials() -> AsyncIterator[str]:
            yield _encode_start()
            yield _encode_error("请先配置 API Key")
            yield _encode_finish()

        return StreamingResponse(
            _no_credentials(),
            media_type="text/event-stream",
            headers=_sse_headers(),
        )

    return StreamingResponse(
        _event_stream(
            topic, provider_config,
            session=session, novel_id=novel_id, task_type=task_type,
        ),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


def _sse_headers() -> Dict[str, str]:
    """SSE headers. `X-Accel-Buffering: no` is mandatory when behind Nginx."""
    return {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        # Hint to clients/proxies that this is a stream of events.
        "Content-Type": "text/event-stream; charset=utf-8",
    }


def _build_evaluator():
    """Construct a ReviewMatrixRunner for multi-dimensional evaluation.

    Returns None when multi-dimensional evaluation is disabled (via
    settings.pipeline_multi_dim_eval) so the evaluate node falls back
    to the single-evaluator path. The runner is stateless and constructed
    per request.
    """
    if not getattr(settings, "pipeline_multi_dim_eval", True):
        return None
    try:
        from app.eval.matrix import ReviewMatrixRunner
        return ReviewMatrixRunner()
    except Exception:
        logger.warning("ReviewMatrixRunner unavailable, using single evaluator", exc_info=True)
        return None


def _extract_novel_id(messages: List[ChatMessage]) -> int | None:
    """Parse an optional novel_id tag from the latest user message.

    Supports ``[novel:N]`` and ``novel_id=N`` markers. Returns None when
    no marker is found — callers scope retrieval/persistence to a novel
    only when an explicit id is present.
    """
    for msg in reversed(messages):
        if msg.role != "user" or not msg.content:
            continue
        m = re.search(r"\[novel:(\d+)\]", msg.content)
        if not m:
            m = re.search(r"novel_id\s*=\s*(\d+)", msg.content)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
        break
    return None


class ModelsListRequest(BaseModel):
    """Body for POST /v1/chat/models — fetch provider's available models."""

    api_base: str = Field(..., min_length=1, max_length=2000)
    api_key: str = Field(..., min_length=1, max_length=2000)
    extra_headers: dict[str, str] = Field(default_factory=dict)


@router.post("/v1/chat/models")
async def list_provider_models(req: ModelsListRequest) -> dict:
    """Fetch the provider's available model list (OpenAI-compatible /models).

    The api_base is SSRF-validated before the outbound request (same guard as
    chat/test). Model IDs are sorted and returned as a flat list so the
    frontend can populate its model dropdown.
    """
    try:
        _validate_api_base(req.api_base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base = req.api_base.rstrip("/")
    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {req.api_key}"}
    if req.extra_headers:
        headers.update(req.extra_headers)

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="API Key 无效，请检查配置")
        if resp.status_code == 404:
            # Some providers expose /models at a different path or reject it.
            raise HTTPException(
                status_code=404, detail="该 API Base 不支持 /models 列表接口"
            )
        resp.raise_for_status()
        data = resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "LIST_MODELS failed for %s: %s: %s",
            _redact_key(req.api_base), type(e).__name__, _redact_key(str(e)),
        )
        raise HTTPException(
            status_code=502, detail="无法获取模型列表，请检查 API Base 和网络"
        )

    # OpenAI-compatible /models returns { data: [{ id: "..." }, ...] }.
    raw = data.get("data", []) if isinstance(data, dict) else []
    models: list[str] = []
    for item in raw:
        mid = item.get("id") if isinstance(item, dict) else None
        if isinstance(mid, str) and mid:
            models.append(mid)
    models = sorted(set(models))

    if not models:
        raise HTTPException(
            status_code=502, detail="模型列表为空，该 API Base 可能不支持此接口"
        )
    return {"models": models, "total": len(models)}


@router.post("/v1/chat/test")
async def test_connection(
    provider_config: Annotated[
        ProviderConfig | None, Depends(_extract_provider_config)
    ],
    stage: str = "draft",
) -> dict:
    """Test LLM connection for a specific stage. Returns success/error."""
    logger.info("TEST_CONNECTION: stage=%s, has_config=%s", stage, provider_config is not None)
    if provider_config is None:
        if not settings.byok_fallback_to_env:
            return {"ok": False, "error": "请先配置 API Key"}
        # Build a StageConfig from env fallback for the requested stage
        stage_cfg = _env_fallback_stage(stage)
        if not stage_cfg:
            return {"ok": False, "error": f"未知阶段: {stage}"}
    else:
        stage_cfg = getattr(provider_config, stage, None)
        if stage_cfg is None:
            return {"ok": False, "error": f"ProviderConfig 中缺少 {stage} 阶段配置"}

    try:
        import openai as openai_lib

        if stage == "embedding":
            # Embedding stage: use openai client directly for /embeddings.
            logger.info("TEST_CONNECTION: embedding stage, model=%s, base=%s", stage_cfg.model, stage_cfg.api_base)
            client = openai_lib.AsyncOpenAI(
                api_key=stage_cfg.api_key, base_url=stage_cfg.api_base, timeout=30,
            )
            resp = await client.embeddings.create(model=stage_cfg.model, input="hi")
            dim = len(resp.data[0].embedding)
            expected = settings.embedding_dim
            dim_match = dim == expected
            return {
                "ok": True,
                "model": stage_cfg.model,
                "sample": f"dim={dim}",
                "detected_dim": dim,
                "expected_dim": expected,
                "dim_match": dim_match,
            }

        # Chat stages: try acompletion first.
        model_name = f"openai/{stage_cfg.model}"
        try:
            resp = await litellm.acompletion(
                model=model_name,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
                api_key=stage_cfg.api_key,
                api_base=stage_cfg.api_base,
                extra_headers=stage_cfg.extra_headers or None,
            )
            content = resp.choices[0].message.content or ""
            return {"ok": True, "model": stage_cfg.model, "sample": content[:50]}
        except litellm.BadRequestError as chat_err:
            # "Model does not exist" on /chat/completions — likely an embedding
            # model (frontend may have sent wrong stage). Fall back to /embeddings.
            if "does not exist" in str(chat_err).lower():
                logger.info("TEST_CONNECTION: chat failed (%s), trying embeddings fallback", chat_err)
                client = openai_lib.AsyncOpenAI(
                    api_key=stage_cfg.api_key, base_url=stage_cfg.api_base, timeout=30,
                )
                resp = await client.embeddings.create(model=stage_cfg.model, input="hi")
                dim = len(resp.data[0].embedding)
                expected = settings.embedding_dim
                dim_match = dim == expected
                return {
                    "ok": True,
                    "model": stage_cfg.model,
                    "sample": f"dim={dim}",
                    "detected_dim": dim,
                    "expected_dim": expected,
                    "dim_match": dim_match,
                }
            raise
    except litellm.AuthenticationError:
        return {"ok": False, "error": "API Key 无效，请检查配置中对应阶段的 Key 是否正确"}
    except litellm.APIConnectionError:
        return {"ok": False, "error": "无法连接到 API Base URL，请检查网络和 URL 配置"}
    except litellm.NotFoundError:
        return {"ok": False, "error": "模型不存在，请检查模型名称是否正确"}
    except Exception as e:
        logger.error("Connection test failed: %s: %s", type(e).__name__, e)
        return {"ok": False, "error": f"连接测试失败: {type(e).__name__}: {e}"}


def _env_fallback_stage(stage: str) -> "StageConfig | None":
    """Build a StageConfig from .env vars for the given stage name."""
    from app.schemas.chat import StageConfig

    if stage == "draft":
        if not settings.deepseek_api_key:
            return None
        return StageConfig(
            api_key=settings.deepseek_api_key,
            api_base="https://api.deepseek.com/v1",
            model=settings.deepseek_model,
        )
    if stage == "refine":
        if not settings.dashscope_api_key:
            return None
        return StageConfig(
            api_key=settings.dashscope_api_key,
            api_base=settings.dashscope_api_base,
            model=settings.dashscope_model,
        )
    if stage == "evaluate":
        if not settings.relay_api_key or not settings.relay_api_base:
            return None
        return StageConfig(
            api_key=settings.relay_api_key,
            api_base=settings.relay_api_base,
            model=settings.relay_claude_model,
        )
    if stage == "embedding":
        if not settings.embedding_api_key:
            return None
        return StageConfig(
            api_key=settings.embedding_api_key,
            api_base=settings.embedding_api_base,
            model=settings.embedding_model,
        )
    return None
