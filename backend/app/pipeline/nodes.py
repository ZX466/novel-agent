"""LangGraph nodes for the three-stage + safety pipeline.

Each node is an async function that takes the current PipelineState and
returns a partial dict to merge back into state. All nodes read
`provider_config` from state and forward the corresponding StageConfig
(draft / refine / evaluate) to the LLM client so BYOK credentials for
each stage flow through the graph independently.

Pipeline flow:
    draft → refine → evaluate → [loop back to refine] → safety_check → END
"""
from __future__ import annotations

import json
import logging
import re
import time
from functools import wraps
from typing import Dict, TypeVar, Callable, Any, Awaitable

T = TypeVar("T")


def _timed(stage: str) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """PerfPulse: record a node's wall-clock elapsed time into
    ``state["perf"][f"{stage}_ms"]`` (rounded to 0.1ms) and, when an
    ``on_event`` callback is present in state, emit R9-② ``stage`` events
    (started / succeeded / failed) for the pipeline-visibility UI.

    Overhead is two `time.perf_counter()` calls per node (~0.05us) —
    negligible vs. LLM/DB stage cost. `state` is the first positional
    argument (PipelineState TypedDict as dict).

    Event payloads follow the closed summary whitelist from the protocol
    design (codex `480d802`): per-stage counters/lengths only — never the
    topic, prompt, draft text, IDs, or credentials (S1/S2).
    """
    def deco(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(state: dict, *args: Any, **kwargs: Any) -> T:
            on_event = state.get("on_event")
            t0 = time.perf_counter()
            if on_event:
                try:
                    await on_event({
                        "type": "stage", "stage": stage,
                        "status": "started", "iteration": state.get("iterations", 0),
                    })
                except Exception:
                    logger.warning("_timed: on_event(started) failed", exc_info=True)
            try:
                result = await fn(state, *args, **kwargs)
            except Exception as exc:
                if on_event:
                    try:
                        await on_event({
                            "type": "stage", "stage": stage,
                            "status": "failed",
                            "iteration": state.get("iterations", 0),
                            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                            # S2: safe enum, never str(exception).
                            "code": _stage_error_code(exc),
                        })
                    except Exception:
                        logger.warning("_timed: on_event(failed) failed", exc_info=True)
                raise
            finally:
                perf_key = "safety_ms" if stage == "safety_check" else f"{stage}_ms"  # PerfPulse 键名保持向后兼容
                perf = state.setdefault("perf", {})
                perf[perf_key] = round((time.perf_counter() - t0) * 1000, 1)
            if on_event:
                try:
                    await on_event({
                        "type": "stage", "stage": stage,
                        "status": "succeeded",
                        "iteration": state.get("iterations", 0),
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                        # Closed summary whitelist per stage (protocol §3):
                        # counters/lengths/scores only — no text, no IDs.
                        "summary": _stage_summary(stage, state),
                    })
                except Exception:
                    logger.warning("_timed: on_event(succeeded) failed", exc_info=True)
            return result
        return wrapper
    return deco


def _stage_summary(stage: str, state: dict) -> dict:
    """Whitelisted per-stage summary for the succeeded event (protocol §3).

    Explicit allowlist per stage; unknown stages return {} (closed whitelist
    — the serialization point refuses keys outside what's constructed here).
    """
    if stage == "retrieval":
        ctx = state.get("retrieved_context") or ""
        return {"chars": len(ctx)}
    if stage == "draft":
        draft = state.get("draft") or ""
        return {"chars": len(draft)}
    if stage == "refine":
        refined = state.get("refined") or ""
        return {"chars": len(refined), "iteration": state.get("iterations", 0)}
    if stage == "evaluate":
        summary: dict = {"score": round(state.get("score", 0.0), 3)}
        if state.get("fallback_mode"):
            summary["fallback"] = True
        return summary
    if stage == "safety_check":
        report = state.get("safety_report") or {}
        return {
            "matched_count": report.get("matched_count", 0),
            "max_severity": report.get("max_severity", "none"),
            "should_block": bool(state.get("safety_passed", True)) is False,
        }
    return {}


def _stage_error_code(exc: Exception) -> str:
    """Map an exception to the protocol's stable failed-code enum (S2)."""
    type_name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "auth" in type_name or "auth" in msg or "401" in msg:
        return "llm_auth"
    if "rate" in type_name or "rate_limit" in msg or "429" in msg:
        return "llm_rate_limit"
    if "timeout" in type_name.lower() or "timed out" in msg:
        return "llm_timeout"
    if "context length" in msg or "context_length" in msg or "max_tokens" in msg:
        return "llm_context_length"
    return "stage_error"

from app.config import settings
from app.llm import draft as llm_draft
from app.llm import evaluate as llm_evaluate
from app.llm import refine as llm_refine
from app.pipeline.state import PipelineState

EVAL_SYSTEM_PROMPT = (
    "You are a strict writing evaluator. Score the text on a 0.0-1.0 scale "
    "where 1.0 means publish-ready. Respond with ONLY a JSON object: "
    '{"score": <float>, "feedback": "<one short sentence on what to improve>"}. '
    "No prose, no markdown fences, no extra characters. "
    "Respond with ONLY the JSON object."
)

logger = logging.getLogger(__name__)

# Max iterations before forced degradation (safety net)
_HARD_MAX_ITERS = 5

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

# R9-④⑥: word-count post-check thresholds (fraction of the resolved target).
# ratio < _WC_REGENERATE → whole-chapter regenerate flag; < _WC_CONTINUE →
# continue-branch top-up. Between _WC_CONTINUE and _WC_OVER → accept.
_WC_REGENERATE = 0.6
_WC_CONTINUE = 0.9
_WC_OVER = 1.2


async def _build_writing_context(state: dict) -> str:
    """Assemble the structured chapter-writing context blocks (R9-④⑥).

    Reads chapter_index / total_chapters / chapter_title / target_word_count
    from state plus the session-scoped DB for prior chapters. Every block is
    optional: when its data is missing the block is skipped entirely (no
    "unknown" placeholders). Output goes into state["writing_context"] and is
    injected into the generate-branch system prompt — NOT into the retrieval
    query, so the embedding cache key stays stable (Pi R9 evaluation §3).
    """
    session = state.get("session")
    novel_id = state.get("novel_id")
    blocks: list[str] = []

    # ── Block 0: writing settings (R10-⑨ 篇幅/视角/频道) ────────────────
    # The frontend persists these in document metadata and sends them with
    # every chat request; only non-empty values become lines (no
    # placeholders), and the whole block is skipped when nothing is set.
    ws = state.get("writing_settings") or {}
    setting_lines: list[str] = []
    if ws.get("writing_type"):
        setting_lines.append(f"篇幅：{ws['writing_type']}")
    if ws.get("pov"):
        setting_lines.append(f"叙事视角：{ws['pov']}")
    if ws.get("genre"):
        setting_lines.append(f"频道：{ws['genre']}")
    if setting_lines:
        blocks.append(
            "【写作设置】\n"
            + "\n".join(setting_lines)
            + "\n写作时必须严格遵守以上设定（视角与人称全章保持一致）。"
        )

    # ── Block 1: chapter progress ──────────────────────────────────────
    chapter_index = state.get("chapter_index")
    total_chapters = state.get("total_chapters")
    chapter_title = state.get("chapter_title") or ""
    progress_lines: list[str] = []
    if chapter_index is not None:
        current = chapter_index + 1
        progress_lines.append(
            f"当前：第{current}章《{chapter_title}》" if chapter_title else f"当前：第{current}章"
        )
        if total_chapters and total_chapters > 0:
            pct = round(current / total_chapters * 100)
            progress_lines.append(f"进度：{current}/{total_chapters}（{pct}%）")
    if progress_lines:
        blocks.append("【章节进度】\n" + "\n".join(progress_lines))

    # ── Block 1b: volume context (09-14 优化2) ─────────────────────────
    # Volume-style outlines (卷→章, title-only) have NO per-chapter synopsis,
    # so generation was blind to its volume. The frontend extracts the
    # current volume's summary + neighbor chapter titles into
    # state["volume_context"]; render it as a block when present.
    vc = state.get("volume_context") or {}
    vc_lines: list[str] = []
    if isinstance(vc, dict):
        summary = str(vc.get("volume_summary") or "").strip()
        if summary:
            vc_lines.append(f"本卷主线：{summary}")
        prev_title = str(vc.get("prev_title") or "").strip()
        if prev_title:
            vc_lines.append(f"上一章：{prev_title}")
        next_title = str(vc.get("next_title") or "").strip()
        if next_title:
            vc_lines.append(f"下一章：{next_title}（本章须为其铺垫）")
    if vc_lines:
        blocks.append("【本卷脉络】\n" + "\n".join(vc_lines))

    # ── Blocks 2-3 need the DB ─────────────────────────────────────────
    target = state.get("target_word_count")
    if session is not None and novel_id is not None:
        # Block 2: prior-chapter background (最近 1-2 章) — improves continuity.
        try:
            from sqlalchemy import select

            from app.models.chapter import Chapter

            prev_chapters = (
                (
                    await session.execute(
                        select(Chapter)
                        .where(
                            Chapter.novel_id == novel_id,
                            Chapter.chapter_index < (chapter_index if chapter_index is not None else 0)
                            if chapter_index is not None
                            else True,
                        )
                        .order_by(Chapter.chapter_index.desc())
                        .limit(2)
                    )
                )
                .scalars()
                .all()
            )
            if prev_chapters:
                bg_lines = []
                for ch in reversed(prev_chapters):
                    snippet = (ch.summary or "").strip() or (ch.content_text or "")[:300]
                    if snippet:
                        bg_lines.append(f"- 第{ch.chapter_index + 1}章《{ch.title}》：{snippet}")
                if bg_lines:
                    blocks.append("【前文背景】\n" + "\n".join(bg_lines))
        except Exception:
            logger.warning("_build_writing_context: prior-chapter lookup failed", exc_info=True)

        # Block 4 (derivation): word-count target from prior chapters' median.
        if target is None:
            try:
                from sqlalchemy import select

                from app.models.chapter import Chapter

                rows = (
                    (
                        await session.execute(
                            select(Chapter.word_count)
                            .where(
                                Chapter.novel_id == novel_id,
                                Chapter.word_count > 0,
                            )
                            .order_by(Chapter.chapter_index.desc())
                            .limit(5)
                        )
                    )
                    .scalars()
                    .all()
                )
                if rows:
                    ordered = sorted(rows)
                    mid = len(ordered) // 2
                    target = (
                        ordered[mid]
                        if len(ordered) % 2
                        else round((ordered[mid - 1] + ordered[mid]) / 2)
                    )
            except Exception:
                logger.warning("_build_writing_context: word-count median lookup failed", exc_info=True)

    # Block 4: word-count requirement.
    if target is None:
        target = 1000  # conservative default for a first chapter
    # R9 P1-2 fix: write the resolved target back into state so the
    # draft/refine post-check uses the SAME number the prompt advertises —
    # otherwise a median-derived target (e.g. 2000) would coexist with a
    # post-check against the 1000 default and the verdicts contradict.
    state["target_word_count"] = target
    target_min = round(target * 0.85)
    target_max = round(target * 1.15)
    blocks.append(
        "【字数要求】\n"
        f"本章目标：{target_min}-{target_max} 字（正文计，不含标题/空白）。"
        "必须控制在该区间内，不足或超出过多视为不合格。"
    )

    # ── Block 2: character relationship tree (R9-④⑥ P2-2) ──────────────
    # serialize_relationships renders the character_relationships graph as
    # compact single-line entries (≤10 chars, ≤2000 chars — Pi budget).
    # Note: also prepended here so it lands BEFORE the word-count block for
    # prompt readability; falls back silently when the table is empty.
    if session is not None and novel_id is not None:
        try:
            from app.services.character_relationship import serialize_relationships

            rel_block = await serialize_relationships(session, novel_id=novel_id)
            if rel_block:
                blocks.insert(1, "【人物关系树】\n" + rel_block)
        except Exception:
            logger.warning("_build_writing_context: relationship serialization failed", exc_info=True)

    return "\n\n".join(blocks)


def _resolve_target_word_count(state: dict) -> int | None:
    """Resolve the effective word target for the post-check (R9-⑥).

    Same priority as _build_writing_context: explicit target_word_count
    first, then median of recent chapters, else the 1000 default. Kept
    separate so draft_node's post-check never re-queries the DB.
    """
    explicit = state.get("target_word_count")
    if explicit:
        return explicit
    return 1000  # matches the _build_writing_context default


def _count_codepoints(text: str) -> int:
    """Count non-whitespace codepoints — mirrors Chapter.word_count derivation
    in services/chapter.py (len-based, whitespace-stripped)."""
    return len("".join(text.split()))


class _ThinkStreamFilter:
    """Filters inline ``<think>…</think>`` blocks out of a token stream.

    Some reasoning models (e.g. step-3.7-flash) emit their chain-of-thought
    inline in ``content`` between <think> tags, instead of the separate
    ``reasoning_content`` field. This filter buffers tokens while inside a
    think block and only forwards content outside one. Final fallback:
    ``strip()`` removes any residual tags from the assembled text.
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.in_think = False
        self.emitted = ""
        self.emitted_any = False

    def feed(self, token: str) -> str:
        """Feed one streamed token; returns text safe to forward now ("" if none)."""
        self.buffer += token
        return self._drain(final=False)

    def finish(self) -> str:
        """Flush the holdback buffer at end of stream and return the tail.

        Closes the streamed phase: anything still buffered (minus a trailing
        unclosed <think>) is released. Call before/instead of strip().
        """
        return self._drain(final=True)

    def strip(self, text: str) -> str:
        """Final regex pass over the assembled text; also closes unclosed tags."""
        cleaned = _THINK_RE.sub("", text)
        # Unclosed <think> (model truncated mid-thought): drop everything after.
        idx = cleaned.find("<think>")
        if idx != -1:
            cleaned = cleaned[:idx]
        return cleaned.strip()

    def _drain(self, *, final: bool) -> str:
        out: list[str] = []
        while True:
            if not self.in_think:
                idx = self.buffer.find("<think>")
                if idx == -1:
                    if final:
                        out.append(self.buffer)
                        self.buffer = ""
                    else:
                        # Hold back the last len("<think>")-1 chars in case a
                        # tag spans a token boundary.
                        cut = max(0, len(self.buffer) - (len("<think>") - 1))
                        out.append(self.buffer[:cut])
                        self.buffer = self.buffer[cut:]
                    break
                out.append(self.buffer[:idx])
                self.buffer = self.buffer[idx + len("<think>"):]
                self.in_think = True
            else:
                end = self.buffer.find("</think>")
                if end == -1:
                    if final:
                        # Unclosed tag at end of stream: drop the whole tail.
                        self.buffer = ""
                    break
                self.buffer = self.buffer[end + len("</think>"):]
                self.in_think = False
        text = "".join(out)
        if text:
            self.emitted_any = True
        return text


def _user_msg(content: str) -> Dict[str, str]:
    return {"role": "user", "content": content}


def _system_msg(content: str) -> Dict[str, str]:
    return {"role": "system", "content": content}


@_timed("retrieval")
async def retrieval_node(state: PipelineState) -> dict:
    """Retrieve relevant memories from the novel's lore before drafting.

    Runs as a separate graph node so the retrieval step is observable
    and independently debuggable. Results are stored in
    ``state["retrieved_context"]`` for draft_node to inject into its
    system prompt. Empty string means no context was available.

    Best-effort: failures are logged and the pipeline continues without
    context — a missing memory should never block writing.
    """
    cfg = state.get("provider_config")
    topic = state["topic"]

    session = state.get("session")
    novel_id = state.get("novel_id")

    # R9-④⑥: structured chapter-writing context is built in the retrieval
    # node so draft_node can read it from state without re-querying the DB.
    writing_context = await _build_writing_context(state)

    if session is None or novel_id is None:
        return {"retrieved_context": "", "writing_context": writing_context}

    # 1) Vector RAG (needs EMBEDDING_* configured).
    try:
        from app.services.retrieval import retrieve, retrieve_structured_lore
        # Use the dedicated embedding stage from ProviderConfig when present
        # (user-configured in the frontend settings dialog). When absent,
        # falls back to .env EMBEDDING_* credentials. Never reuse the draft
        # chat stage — its endpoint exposes no /embeddings route.
        embedding_stage = cfg.embedding if cfg is not None else None
        hits = await retrieve(
            session,
            topic,
            novel_id=novel_id,
            k_per_collection=5,
            stage_config=embedding_stage,
        )
        if hits:
            ctx = _format_retrieval_context(hits)
            logger.debug(
                "retrieval_node: %d hits, %d chars", len(hits), len(ctx)
            )
            return {"retrieved_context": ctx, "writing_context": writing_context}
    except Exception:
        logger.warning(
            "retrieval_node: vector retrieval failed, falling back to structured lore",
            exc_info=True,
        )
    # 2) Structured lore fallback (no embeddings needed): characters / world /
    #    recent chapters straight from the DB, so the draft still knows the
    #    novel even when EMBEDDING_* is unconfigured or retrieval returned nothing.
    try:
        from app.services.retrieval import retrieve_structured_lore
        lore = await retrieve_structured_lore(
            session, novel_id=novel_id, max_chars=6000
        )
        if lore:
            logger.info("retrieval_node: structured lore fallback, %d chars", len(lore))
            return {"retrieved_context": lore, "writing_context": writing_context}
    except Exception:
        logger.exception(
            "retrieval_node: structured lore fallback failed, continuing without context"
        )

    return {"retrieved_context": "", "writing_context": writing_context}


@_timed("draft")
async def draft_node(state: PipelineState) -> dict:
    """DeepSeek-V4-Flash (or BYOK draft stage) generates an initial draft.

    Uses state["retrieved_context"] populated by retrieval_node to
    ground the draft in established lore. Empty context means a generic
    draft prompt is used.

    When task_type is "extract", uses a strict JSON-only system prompt
    so the model returns structured data instead of prose.

    Streams tokens in real-time via state["on_token"] callback so the
    frontend sees text appearing character-by-character.
    """
    cfg = state.get("provider_config")
    stage = cfg.draft if cfg is not None else None
    topic = state["topic"]
    on_token = state.get("on_token")
    task_type = state.get("task_type", "generate")

    if task_type == "extract":
        system_content = (
            "你是一个结构化数据提取器。用户会给你一段小说大纲，请从中提取角色、世界观设定、剧情事件和人物关系。\n"
            "只输出 JSON，不要任何解释、markdown 或多余文字。\n"
            "输出格式：\n"
            '{"characters":[{"name":"姓名","role":"主角/配角/反派/其他","description":"简短描述","arc_summary":"成长弧线"}],'
            '"world_settings":[{"category":"地理/势力/体系/其他","title":"标题","content_text":"内容"}],'
            '"plot_events":[{"chapter_index":0,"event_type":"起/承/转/合/高潮/结局/其他","summary":"事件概述"}],'
            '"relationships":[{"subject_name":"角色A","object_name":"角色B","relation_type":"师徒/恋人/敌对/搭档/亲属/其他","strength":5,"description":"关系说明"}]}\n'
            "relationships 为人物关系线：subject_name/object_name 必须是 characters 中出现的姓名，"
            "strength 为 1-10 的整数，"
            "人物关系取自大纲中角色间的互动/称谓，若大纲未体现则留空 []。"
            "其他类别如果在大纲中不存在，对应数组同样留空 []。"
        )
    elif task_type == "outline":
        system_content = (
            "你是一位专业的小说策划编辑。请生成完整的故事大纲，包含以下部分，"
            "每部分用清晰的标题分隔：\n\n"
            "【主题与核心冲突】\n（1-2 句话说明主题和核心矛盾）\n\n"
            "【主要角色】\n逐个列出角色：姓名、身份、动机、成长弧线。每角色一行或一段。\n\n"
            "【世界观设定】\n列出地理、势力、魔法/科技体系等设定。\n\n"
            "【章节梗概】\n逐章列出，每章用 \"第X章 标题\" 开头，换行后接 2-3 句概况。例如：\n"
            "第一章 初入江湖\n少年张三拜入青云宗，初识师兄弟，因天赋异禀被掌门收为关门弟子。\n"
            "第二章 首战告捷\n宗门大比中张三击败宿敌李四，初露锋芒，却引来暗处的觊觎。\n\n"
            "直接输出大纲内容，不要前后缀说明。"
        )
    elif task_type == "assistant":
        system_content = (
            "你是一位小说创作 AI 编剧。对话最后一条 user 消息是当前问题，"
            "前文为作品上下文与对话历史（角色 user/assistant 表示问答双方）。\n"
            "要求：\n"
            "1. 直接给出具体、可执行的创作建议（情节发展/人物刻画/对白/节奏/连贯性），"
            "不要复述问题，不要输出与创作无关的内容；\n"
            "2. 结合作品上下文中的角色与世界观，不凭空设定；\n"
            "3. 回复 200-600 字，条理清晰，可直接插入正文或当作修改参考；\n"
            "4. 只输出建议正文，不要任何思考过程、解释或前后缀。"
        )
    elif task_type == "generate":
        # R9-④⑥: dedicated chapter-writing branch. Injects the structured
        # writing context (chapter progress / prior-chapter background /
        # word-count requirement) assembled by retrieval_node, plus hard
        # continuity and paragraphing requirements. Character/world lore
        # still arrives via retrieved_context below — not duplicated here.
        parts = [
            "你是一位专业小说写作助手。请根据以下写作约束和作品资料，写出当前章节的正文。",
        ]
        writing_context = state.get("writing_context", "")
        if writing_context:
            parts.append(writing_context)
        parts.append(
            "【写作要求】\n"
            "1. 开头自然衔接上文，不重复已写内容\n"
            "2. 多用具体动作、环境细节、对白与心理活动，避免空泛概括\n"
            "3. 人物言行必须符合既有角色设定与世界观，推进剧情并留下至少一处伏笔\n"
            "4. 结尾停在张力点，方便继续续写\n"
            "5. 正文分段：每个自然段 2-5 句，段间换行，严禁一整段输出\n"
            "6. 除正文外不要任何解释或思考过程。"
        )
        system_content = "\n\n".join(parts)
    else:
        system_content = "You are a concise drafting assistant. Write a first draft."

    retrieved_context = state.get("retrieved_context", "")
    if retrieved_context and task_type != "extract":
        system_content = (
            system_content + "\n\n"
            "Relevant memory from the novel's lore (use this to stay consistent "
            "with established characters, world settings, and prior chapters):\n"
            f"{retrieved_context}"
        )

    messages = [
        _system_msg(system_content),
        _user_msg(topic),
    ]

    # Stream tokens in real-time. _ThinkStreamFilter drops inline
    # <think>…</think> blocks some reasoning models emit inside `content`.
    content = ""
    think_filter = _ThinkStreamFilter()
    draft_kwargs: dict = {"stage_config": stage, "stream": True}
    if task_type == "extract":
        # JSON extraction: lower temperature for deterministic output
        # and request JSON mode. max_tokens defaults to 4096 in draft().
        draft_kwargs["temperature"] = 0.1
        draft_kwargs["response_format"] = {"type": "json_object"}
    stream_resp = await llm_draft(messages, **draft_kwargs)
    async for chunk in stream_resp:
        delta = chunk.choices[0].delta
        # ONLY stream `content`. Reasoning models (DeepSeek-R1, QwQ, etc.)
        # put their chain-of-thought in `reasoning_content` — that is the
        # model's private thinking and must NEVER leak into the novel text.
        token = getattr(delta, "content", None) or ""
        if token:
            safe = think_filter.feed(token)
            if safe:
                content += safe
                if on_token:
                    await on_token(safe)
    tail = think_filter.finish()
    if tail:
        content += tail
        if on_token:
            await on_token(tail)
    content = think_filter.strip(content)

    if not content.strip():
        logger.warning(
            "draft_node: LLM returned empty content (task_type=%s, model=%s, "
            "msg_len=%d, stage_config=%s)",
            task_type,
            stage.model if stage else "env-default",
            len(topic),
            "BYOK" if stage else "env",
        )
    else:
        logger.info(
            "draft_node: completed (task_type=%s, model=%s, chars=%d)",
            task_type,
            stage.model if stage else "env-default",
            len(content),
        )

    result: dict = {"draft": content, "iterations": 0}
    if retrieved_context:
        result["retrieval_hits"] = len(retrieved_context)

    # R9-⑥ word-count post-check (generate only — outline/extract have
    # different length profiles). Verdict drives refine_node's strategy:
    # "continue" → top-up instruction; "regenerate" → stronger word-count
    # emphasis on the next iteration. Not wired into evaluate (Pi R9 §3:
    # word-count must not inflate the refine loop cost).
    if task_type == "generate" and content.strip():
        target = _resolve_target_word_count(state)
        if target and target > 0:
            wc = _count_codepoints(content)
            ratio = wc / target
            logger.info(
                "draft_node: word-count post-check wc=%d target=%d ratio=%.2f",
                wc, target, ratio,
            )
            if ratio < _WC_REGENERATE:
                result["word_count_retry"] = "regenerate"
            elif ratio < _WC_CONTINUE:
                result["word_count_retry"] = "continue"
            else:
                # R9 review P2-1: clear any stale verdict — state is
                # cumulative across refine iterations, so an un-cleared
                # flag would keep appending top-up instructions even
                # after the text reached its target.
                result["word_count_retry"] = ""
    return result


def _format_retrieval_context(hits: list) -> str:
    """Format retrieval hits into a compact lore summary string."""
    lines = []
    for i, hit in enumerate(hits[:12], 1):
        payload = hit.payload if hasattr(hit, "payload") else {}
        entity_type = hit.entity_type if hasattr(hit, "entity_type") else "unknown"
        score = hit.score if hasattr(hit, "score") else 0.0
        if entity_type == "chapter":
            title = payload.get("title", "")
            summary = payload.get("summary", "")
            lines.append(f"{i}. [chapter] {title} (relevance={score:.2f}): {summary}")
        elif entity_type == "character":
            name = payload.get("name", "")
            role = payload.get("role", "")
            desc = payload.get("description", "")
            lines.append(f"{i}. [character] {name} ({role}, relevance={score:.2f}): {desc}")
        elif entity_type == "world_setting":
            cat = payload.get("category", "")
            title = payload.get("title", "")
            content = payload.get("content_text", "")
            lines.append(f"{i}. [world_setting/{cat}] {title} (relevance={score:.2f}): {content}")
        elif entity_type == "knowledge_doc":
            # 09-14 ③: attribute lore chunks to their uploaded file so the
            # model (and the author debugging it) knows where a rule came from.
            title = payload.get("title", "")
            idx = payload.get("chunk_index", 0)
            content = payload.get("content", "")
            lines.append(f"{i}. [知识文档/{title}·{idx + 1}] (relevance={score:.2f}): {content}")
        elif entity_type == "plot_event":
            etype = payload.get("event_type", "")
            summary = payload.get("summary", "")
            lines.append(f"{i}. [plot_event/{etype}] (relevance={score:.2f}): {summary}")
    return "\n".join(lines)[:8000]


async def _refine_from_topic(state: PipelineState, stage) -> dict:
    """refine_node's first-stage branch for rewrite/polish (no draft yet).

    The topic carries the full task instruction + source text, so it goes
    through as the user message; the system prompt is a Chinese editor
    persona (the old English-only one plus empty input produced English
    output regardless of the source language).
    """
    system_content = (
        "你是一位严谨的小说编辑。按用户要求处理给出的文本：保持情节、"
        "结构与人物设定不变，只按指令改进表达。直接输出处理后的完整"
        "文本，不要任何解释或前后缀。"
    )
    retrieved_context = state.get("retrieved_context", "")
    if retrieved_context:
        system_content += (
            "\n\n小说相关记忆（保持与既有角色、世界观和前文一致）：\n"
            f"{retrieved_context}"
        )

    messages = [
        _system_msg(system_content),
        _user_msg(state["topic"]),
    ]

    content = ""
    think_filter = _ThinkStreamFilter()
    stream_resp = await llm_refine(messages, stage_config=stage, stream=True)
    async for chunk in stream_resp:
        delta = chunk.choices[0].delta
        token = getattr(delta, "content", None) or ""
        if token:
            safe = think_filter.feed(token)
            if safe:
                content += safe
                on_token = state.get("on_token")
                if on_token:
                    await on_token(safe)
    tail = think_filter.finish()
    if tail:
        content += tail
        on_token = state.get("on_token")
        if on_token:
            await on_token(tail)
    content = think_filter.strip(content)
    return {"refined": content, "iterations": state.get("iterations", 0) + 1}


@_timed("refine")
async def refine_node(state: PipelineState) -> dict:
    """Qwen-Max (or BYOK refine stage) refines the most recent text using feedback.

    Streams tokens in real-time via state["on_token"] callback so the
    frontend sees the refined text appearing character-by-character.

    rewrite/polish first stage: the graph runs retrieval → refine →
    safety_check with NO draft node, so there is no draft/feedback — the
    user's instruction + source text IS state["topic"] (chat.py already
    stripped the [task:…]/[novel:…] tags). Sending it through the
    Original-draft/feedback template left both blocks empty and the model
    hallucinated free-form text (deployed 09-13: it overwrote a novel
    outline with an unrelated English essay).
    """
    cfg = state.get("provider_config")
    stage = cfg.refine if cfg is not None else None
    task_type = state.get("task_type", "generate")
    has_prior_output = bool(state.get("refined") or state.get("draft"))
    if task_type in ("rewrite", "polish") and not has_prior_output:
        return await _refine_from_topic(state, stage)

    current_text = state.get("refined") or state.get("draft") or ""
    feedback = state.get("feedback", "")
    iterations = state.get("iterations", 0)
    on_token = state.get("on_token")

    user_content = (
        f"Original draft:\n{state.get('draft', '')}\n\n"
        f"Current version:\n{current_text}\n\n"
    )
    if feedback:
        user_content += f"Evaluator feedback:\n{feedback}\n\n"
    # R9-⑥: word-count verdict from draft_node's post-check. continue →
    # append a top-up instruction (much cheaper than a full regenerate);
    # regenerate → stronger word-count emphasis for this iteration.
    wc_retry = state.get("word_count_retry", "")
    if wc_retry in ("continue", "regenerate"):
        target = _resolve_target_word_count(state)
        current_wc = _count_codepoints(current_text)
        deficit = max(0, target - current_wc)
        if wc_retry == "continue":
            user_content += (
                f"【字数补足】当前正文约 {current_wc} 字，目标 {target} 字。"
                f"请在不破坏已有情节与风格的前提下扩写，补足约 {deficit} 字"
                "（补充动作细节、环境描写、对白或心理活动）。输出完整的扩写后正文。\n\n"
            )
        else:
            user_content += (
                f"【字数严重不足】当前正文约 {current_wc} 字，远低于目标约 {target} 字的篇幅，"
                "请在扩写时大幅充实内容（新增场景/事件/对白），确保达到目标字数区间。\n\n"
            )
    user_content += "Produce an improved version. Output only the new text, no preamble."

    system_content = "You are a meticulous editor. Refine the text per the feedback."
    retrieved_context = state.get("retrieved_context", "")
    if retrieved_context:
        system_content = (
            "You are a meticulous editor. Refine the text per the feedback.\n\n"
            "Relevant memory from the novel's lore (use this to stay consistent "
            "with established characters, world settings, and prior chapters):\n"
            f"{retrieved_context}"
        )

    messages = [
        _system_msg(system_content),
        _user_msg(user_content),
    ]

    # Stream tokens in real-time (with inline <think> filtering)
    content = ""
    think_filter = _ThinkStreamFilter()
    stream_resp = await llm_refine(messages, stage_config=stage, stream=True)
    async for chunk in stream_resp:
        delta = chunk.choices[0].delta
        token = getattr(delta, "content", None) or ""
        if token:
            safe = think_filter.feed(token)
            if safe:
                content += safe
                if on_token:
                    await on_token(safe)
    tail = think_filter.finish()
    if tail:
        content += tail
        if on_token:
            await on_token(tail)
    content = think_filter.strip(content)

    return {
        "refined": content,
        "iterations": iterations + 1,
    }


@_timed("evaluate")
async def evaluate_node(state: PipelineState) -> dict:
    """Scores the refined text — single evaluator or multi-dimensional matrix.

    When an optional ReviewMatrixRunner is present in state, runs all
    review dimensions in parallel and uses the aggregate score/feedback
    to drive the next refine iteration. Falls back to the original
    single llm_evaluate call otherwise.

    When any evaluation stage fails, returns a fallback score of 0.5 with
    a message indicating the stage was skipped.
    """
    cfg = state.get("provider_config")
    stage = cfg.evaluate if cfg is not None else None
    text_to_eval = state.get("refined") or state.get("draft") or ""

    # Multi-dimensional evaluation path.
    evaluator = state.get("evaluator")
    if evaluator is not None:
        try:
            matrix = await evaluator.evaluate(
                text_to_eval,
                stage_config=stage,
                threshold=state.get("score_threshold", 0.8),
            )
            score = matrix.aggregate_score
            feedback = matrix.aggregate_feedback
            # Persist per-dimension detail for observability.
            # matrix.results is a tuple[ReviewResult, ...] (not a dict) —
            # key by dimension_name for the state payload.
            dim_details = {
                r.dimension_name: {"score": r.score, "feedback": r.feedback, "error": r.error}
                for r in matrix.results
            }
        except Exception:
            logger.exception("evaluate_node: ReviewMatrixRunner failed, falling back")
            evaluator = None  # fall through to single-evaluator path

    # Single-evaluator path (original).
    if evaluator is None:
        try:
            messages = [
                _system_msg(EVAL_SYSTEM_PROMPT),
                _user_msg(f"Topic: {state['topic']}\n\nText to evaluate:\n{text_to_eval}"),
            ]
            resp = await llm_evaluate(messages, stage_config=stage)
            raw = resp.choices[0].message.content.strip()
            score, feedback = _parse_eval(raw)
            dim_details = None
        except Exception as exc:
            # Determine stage-aware error message
            err_str = str(exc)
            if "api" in err_str.lower() and ("key" in err_str.lower() or "auth" in err_str.lower()):
                reason = "evaluate: API key 无效"
            elif "connect" in err_str.lower() or "timeout" in err_str.lower():
                reason = "evaluate: 无法连接到 API"
            else:
                reason = f"evaluate: {err_str[:100]}"
            logger.exception("evaluate_node: single evaluator failed, using fallback")
            return {
                "score": 0.5,
                "feedback": "评估阶段暂不可用，已跳过",
                "fallback_mode": True,
                "fallback_reason": reason,
            }

    # Best-effort persistence of the evaluation score.
    #
    # Performance: only persist on the FINAL evaluation pass (the one that
    # routes to safety_check). Intermediate refine-loop passes used to each
    # commit a row — 3 iteration loop = 3 full DB transactions per request.
    # The final score/feedback is what trend analysis consumes; intermediate
    # scores remain visible in state["review_details"] / logging.
    session = state.get("session")
    if session is not None:
        persist = False
        try:
            # Predict the router's decision as of now: if this evaluation
            # pass is the last one (next hop is safety_check), persist.
            next_hop = route_after_evaluate(
                {**state, "score": score, "feedback": feedback}
            )
            persist = next_hop == "safety_check"
        except Exception:
            # Route prediction must never break persistence semantics:
            # default to persisting on failure to predict.
            persist = True

        if persist:
            try:
                from app.services.evaluation import create_evaluation
                await create_evaluation(
                    session,
                    novel_id=state.get("novel_id") or 0,
                    stage="pipeline_evaluate",
                    score=score,
                    feedback=feedback,
                    source="stream_pipeline",
                )
            except Exception:
                logger.exception("evaluate_node: failed to persist evaluation")

    result: dict = {"score": score, "feedback": feedback}
    if dim_details:
        result["review_details"] = dim_details
    return result


def _parse_eval(raw: str) -> tuple[float, str]:
    """Extract score and feedback from Claude's JSON response.

    Defensive parsing: Claude usually returns clean JSON, but occasionally
    wraps in markdown fences or adds stray prose. Falls back to regex.

    The fallback anchors to the 'score' keyword before falling back to the
    first number: models that echo the prompt's '0.0-1.0 scale' before the
    real score would otherwise yield 0.0 (the scale's leading 0.0) and
    force the pipeline to loop every refine iteration for nothing.

    Score is clamped to [0.0, 1.0] to prevent out-of-range values from
    triggering incorrect pass/fail decisions.
    """
    # Strip markdown fences if present
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

    # 1. Clean JSON.
    try:
        data = json.loads(cleaned)
        score = max(0.0, min(1.0, float(data["score"])))
        return score, str(data.get("feedback", ""))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        pass

    # 2. JSON object embedded in prose.
    obj_match = re.search(r"\{[^{}]*\}", cleaned)
    if obj_match:
        try:
            data = json.loads(obj_match.group(0))
            if "score" in data:
                score = max(0.0, min(1.0, float(data["score"])))
                return score, str(data.get("feedback", ""))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # 3. Number anchored to the 'score' keyword.
    kw_match = re.search(r"score\b[^\d]*([0-9]*\.?[0-9]+)", cleaned, re.IGNORECASE)
    if kw_match:
        score = max(0.0, min(1.0, float(kw_match.group(1))))
        return score, cleaned[:200]

    # 4. Last-resort: first number anywhere.
    score_match = re.search(r"([0-9]*\.?[0-9]+)", cleaned)
    if score_match:
        score = max(0.0, min(1.0, float(score_match.group(1))))
        return score, cleaned[:200]

    return 0.0, cleaned[:200]


def route_after_evaluate(state: PipelineState) -> str:
    """Conditional edge router: loop back to refine or proceed to safety_check.

    Pure function — MUST NOT mutate state.

    After _HARD_MAX_ITERS iterations, always proceeds to safety_check
    regardless of score to prevent infinite oscillation (degradation mode).
    """
    if state.get("score", 0.0) >= settings.pipeline_score_threshold:
        return "safety_check"
    if state.get("iterations", 0) >= settings.pipeline_max_iters:
        return "safety_check"
    if state.get("iterations", 0) >= _HARD_MAX_ITERS:
        return "safety_check"
    return "refine"


@_timed("safety_check")
async def safety_check_node(state: PipelineState) -> dict:
    """Rule-engine safety check run on the final output before release.

    Uses the default RuleEngine (which includes Chinese-language safety
    rules). BLOCK-severity matches set `safety_passed=False` and include
    a `safety_report` with details. The text is never suppressed entirely
    (the caller decides how to present blocked content), but the flag is
    available so downstream consumers can decide.

    This node replaces the missing "safety" stage in the pipeline graph
    so the three-stage pipeline gets the same safety protection as the
    multi-agent system.
    """
    # Lazy import to break circular dependency:
    # pipeline → safety → agents → pipeline
    from app.safety.rules import RuleEngine  # noqa: F811

    text = state.get("refined") or state.get("draft") or ""

    try:
        engine = RuleEngine()
        results = engine.check(text)
        summary = RuleEngine.summarize(results)
        passed = not engine.should_block(results)
    except Exception:
        logger.exception("safety_check_node: rule engine failed, defaulting to pass")
        return {
            "safety_passed": True,
            "safety_report": {"error": "safety check unavailable"},
        }

    return {
        "safety_passed": passed,
        "safety_report": summary,
    }
