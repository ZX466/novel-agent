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
from typing import Dict

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


def _user_msg(content: str) -> Dict[str, str]:
    return {"role": "user", "content": content}


def _system_msg(content: str) -> Dict[str, str]:
    return {"role": "system", "content": content}


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

    if session is None or novel_id is None:
        return {"retrieved_context": ""}

    try:
        from app.services.retrieval import retrieve
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
            return {"retrieved_context": ctx}
    except Exception:
        logger.exception(
            "retrieval_node: memory retrieval failed, continuing without context"
        )

    return {"retrieved_context": ""}


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
            "你是一个结构化数据提取器。用户会给你一段小说大纲，请从中提取角色、世界观设定和剧情事件。\n"
            "只输出 JSON，不要任何解释、markdown 或多余文字。\n"
            "输出格式：\n"
            '{"characters":[{"name":"姓名","role":"主角/配角/反派/其他","description":"简短描述","arc_summary":"成长弧线"}],'
            '"world_settings":[{"category":"地理/势力/体系/其他","title":"标题","content_text":"内容"}],'
            '"plot_events":[{"chapter_index":0,"event_type":"起/承/转/合/高潮/结局/其他","summary":"事件概述"}]}\n'
            "如果某类信息在大纲中不存在，对应数组留空 []。"
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
            "请直接给出具体、可执行的创作建议（情节发展/人物刻画/对白/节奏/连贯性），"
            "不要复述问题，不要输出与创作无关的内容。"
        )
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

    # Stream tokens in real-time
    content = ""
    draft_kwargs: dict = {"stage_config": stage, "stream": True}
    if task_type == "extract":
        # JSON extraction: lower temperature for deterministic output
        # and request JSON mode. max_tokens defaults to 4096 in draft().
        draft_kwargs["temperature"] = 0.1
        draft_kwargs["response_format"] = {"type": "json_object"}
    stream_resp = await llm_draft(messages, **draft_kwargs)
    async for chunk in stream_resp:
        delta = chunk.choices[0].delta
        # Some models (DeepSeek-R1, QwQ, etc.) put content in
        # reasoning_content or thinking fields instead of content.
        token = (
            getattr(delta, "content", None)
            or getattr(delta, "reasoning_content", None)
            or ""
        )
        if token:
            content += token
            if on_token:
                await on_token(token)

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
        elif entity_type == "plot_event":
            etype = payload.get("event_type", "")
            summary = payload.get("summary", "")
            lines.append(f"{i}. [plot_event/{etype}] (relevance={score:.2f}): {summary}")
    return "\n".join(lines)[:8000]


async def refine_node(state: PipelineState) -> dict:
    """Qwen-Max (or BYOK refine stage) refines the most recent text using feedback.

    Streams tokens in real-time via state["on_token"] callback so the
    frontend sees the refined text appearing character-by-character.
    """
    cfg = state.get("provider_config")
    stage = cfg.refine if cfg is not None else None
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

    # Stream tokens in real-time
    content = ""
    stream_resp = await llm_refine(messages, stage_config=stage, stream=True)
    async for chunk in stream_resp:
        delta = chunk.choices[0].delta
        token = getattr(delta, "content", None) or ""
        if token:
            content += token
            if on_token:
                await on_token(token)

    return {
        "refined": content,
        "iterations": iterations + 1,
    }


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
        except Exception as exc:
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
    from app.safety.rules import RuleEngine, Severity  # noqa: F811

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
