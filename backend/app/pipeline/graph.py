"""LangGraph state graph construction and streaming entry points.

Build (default "generate" task):
    START -> retrieval -> draft -> refine -> evaluate --(score<threshold AND iters<max)--> refine
                                                       \\--(otherwise)--> safety_check -> END

Task-type routing selects a subset of stages:
    - "generate": full pipeline (all stages)
    - "continue": START -> retrieval -> draft -> safety_check -> END
    - "rewrite"/"polish": START -> refine -> safety_check -> END
    - "outline": START -> retrieval -> draft -> safety_check -> END

`stream_pipeline(topic, provider_config)` uses an on_token callback
injected into the pipeline state. draft_node and refine_node call this
callback for each streamed LLM token, which puts it into an asyncio.Queue.
stream_pipeline yields from the queue, so the frontend sees text appearing
character-by-character in real time. Falls back to 4-char chunking if the
streaming callback approach fails.

`provider_config` (BYOK credentials) flows into LangGraph state and is read
by every node so all LLM stages use the user's provider.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.pipeline.nodes import (
    draft_node,
    evaluate_node,
    refine_node,
    retrieval_node,
    route_after_evaluate,
    safety_check_node,
)
from app.pipeline.state import PipelineState
from app.schemas.chat import ProviderConfig

logger = logging.getLogger(__name__)


def build_pipeline():
    """Compiles the StateGraph. Call once; the result is reusable.

    Note: `recursion_limit` is NOT a compile() argument in LangGraph >=1.0.
    It is passed at invoke time via `config={"recursion_limit": N}` in
    `run_pipeline`. See langgraph 1.2.x migration notes.
    """
    graph = StateGraph(PipelineState)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("draft", draft_node)
    graph.add_node("refine", refine_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("safety_check", safety_check_node)

    graph.add_edge(START, "retrieval")
    graph.add_edge("retrieval", "draft")
    graph.add_edge("draft", "refine")
    graph.add_edge("refine", "evaluate")
    # LangGraph 1.x: conditional edges need an explicit path_map so the
    # string returned by route_after_evaluate maps to the right node.
    # Without this, the graph logs "wrote to unknown channel branch:to:END"
    # and fails to terminate, causing empty output.
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {"refine": "refine", "safety_check": "safety_check"},
    )
    graph.add_edge("safety_check", END)

    return graph.compile()


def _recursion_limit() -> int:
    """Max graph steps = 3 nodes per refine iteration + slack + retrieval + safety."""
    return settings.pipeline_max_iters * 3 + 8


def _should_run_stage(task_type: str, stage: str) -> bool:
    """Determine if a pipeline stage should run for this task type.

    - "generate": full pipeline (all stages)
    - "continue": only draft + safety (skip refine/evaluate for speed)
    - "rewrite"/"polish": only refine + safety (input is already written text)
    - "outline": only draft + safety (structural output, evaluation not useful)
    - "extract": only draft (direct JSON extraction, no safety needed)
    """
    if task_type in ("continue", "assistant"):
        # continue: fast continuation (draft + safety)
        # assistant: multi-turn creative chat (draft + safety, RAG useful)
        return stage in ("retrieval", "draft", "safety_check")
    if task_type in ("rewrite", "polish"):
        return stage in ("refine", "safety_check")
    if task_type == "outline":
        return stage in ("retrieval", "draft", "safety_check")
    if task_type == "extract":
        return stage == "draft"
    # "generate" or unknown: full pipeline
    return True


def build_pipeline_for_task(task_type: str):
    """Compiles a StateGraph tailored to the given task_type."""
    graph = StateGraph(PipelineState)

    # Always add safety_check (terminal node for all task types)
    graph.add_node("safety_check", safety_check_node)

    stages = ("retrieval", "draft", "refine", "evaluate")
    node_map = {
        "retrieval": retrieval_node,
        "draft": draft_node,
        "refine": refine_node,
        "evaluate": evaluate_node,
    }

    active_stages = [s for s in stages if _should_run_stage(task_type, s)]

    for stage in active_stages:
        graph.add_node(stage, node_map[stage])

    # Wire edges: START -> first stage -> ... -> safety_check -> END
    if active_stages:
        graph.add_edge(START, active_stages[0])
        for i in range(len(active_stages) - 1):
            graph.add_edge(active_stages[i], active_stages[i + 1])

        last_stage = active_stages[-1]

        if last_stage == "evaluate":
            # Evaluate has conditional routing back to refine
            graph.add_conditional_edges(
                "evaluate",
                route_after_evaluate,
                {"refine": "refine", "safety_check": "safety_check"},
            )
        else:
            graph.add_edge(last_stage, "safety_check")
    else:
        # Fallback: START -> safety_check -> END
        graph.add_edge(START, "safety_check")

    graph.add_edge("safety_check", END)
    return graph.compile()


# Pipeline cache keyed by task_type.
_pipeline_cache: dict[str, Any] = {}


def _get_pipeline_for_task(task_type: str):
    """Return (and cache) the compiled graph for *task_type*."""
    if task_type not in _pipeline_cache:
        _pipeline_cache[task_type] = build_pipeline_for_task(task_type)
    return _pipeline_cache[task_type]


# Legacy singleton for callers that don't specify task_type.
def _get_pipeline():
    return _get_pipeline_for_task("generate")


async def run_pipeline(
    topic: str,
    provider_config: ProviderConfig | None = None,
    session=None,
    evaluator=None,
    novel_id: int | None = None,
    task_type: str = "generate",
    on_token=None,
) -> PipelineState:
    """Runs the full pipeline non-streaming; returns final state.

    `on_token` is an optional async callback for real-time streaming.
    When provided, draft_node and refine_node call it for each streamed
    token so the caller can yield tokens as they arrive.
    """
    app = _get_pipeline_for_task(task_type)
    return await app.ainvoke(
        {
            "topic": topic,
            "provider_config": provider_config,
            "session": session,
            "evaluator": evaluator,
            "novel_id": novel_id,
            "task_type": task_type,
            "on_token": on_token,
        },
        config={"recursion_limit": _recursion_limit()},
    )


async def stream_pipeline(
    topic: str,
    provider_config: ProviderConfig | None = None,
    session=None,
    evaluator=None,
    novel_id: int | None = None,
    task_type: str = "generate",
) -> AsyncIterator[str]:
    """True streaming: yields tokens as the LLM generates them.

    Uses an on_token callback injected into the pipeline state. The
    draft_node and refine_node call this callback for each streamed
    token, which puts it into an asyncio.Queue. This function yields
    from the queue, so the frontend sees text appearing character-by-character.

    Falls back to running the pipeline to completion and chunking if the
    streaming callback approach fails.

    `task_type` selects which pipeline stages to run.
    """
    token_queue: asyncio.Queue[str | None] = asyncio.Queue()
    pipeline_error: Exception | None = None

    async def on_token(text: str) -> None:
        await token_queue.put(text)

    async def _run_pipeline():
        """Run the pipeline in a background task; puts None when done."""
        nonlocal pipeline_error
        try:
            await run_pipeline(
                topic,
                provider_config,
                session=session,
                evaluator=evaluator,
                novel_id=novel_id,
                task_type=task_type,
                on_token=on_token,
            )
        except Exception as e:
            logger.error("stream_pipeline: pipeline task failed: %s", e)
            pipeline_error = e
        finally:
            await token_queue.put(None)  # sentinel: pipeline done

    # Start pipeline in background
    pipeline_task = asyncio.create_task(_run_pipeline())

    try:
        # Yield tokens as they arrive from the pipeline nodes
        while True:
            token = await token_queue.get()
            if token is None:
                break  # pipeline finished
            yield token
        # If the pipeline failed silently, re-raise so _event_stream can send
        # an error event to the frontend instead of an empty response.
        if pipeline_error is not None:
            raise pipeline_error
    except Exception as e:
        logger.warning("True streaming failed (%s), falling back to chunking: %s", type(e).__name__, e)
        # Fallback: run pipeline to completion and chunk the result
        if not pipeline_task.done():
            pipeline_task.cancel()
            try:
                await pipeline_task
            except asyncio.CancelledError:
                pass
        final_state = await run_pipeline(
            topic,
            provider_config,
            session=session,
            evaluator=evaluator,
            novel_id=novel_id,
            task_type=task_type,
        )
        final_text = final_state.get("refined") or final_state.get("draft") or ""

        logger.info(
            "Pipeline done (fallback): iters=%d score=%.2f refined=%d chars draft=%d chars safety_passed=%s",
            final_state.get("iterations", 0),
            final_state.get("score", 0.0),
            len(final_state.get("refined") or ""),
            len(final_state.get("draft") or ""),
            final_state.get("safety_passed"),
        )

        if final_text:
            for i in range(0, len(final_text), 4):
                yield final_text[i : i + 4]
    finally:
        if not pipeline_task.done():
            pipeline_task.cancel()
            try:
                await pipeline_task
            except asyncio.CancelledError:
                pass
