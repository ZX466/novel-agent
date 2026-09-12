"""Tests for R9-② stage events (pipeline observability protocol v1).

Covers:
- S1: stage events never carry topic/prompt text or credentials
- S2: failed events carry a safe code enum, never str(exception)
- M1: skipped events for non-active stages (pipeline layer)
- summary whitelist per stage (closed — no text leakage)
- event ordering with tokens through the same queue
"""
import json

import pytest

from app.pipeline import nodes
from app.pipeline.graph import _ACTIVE_STAGES, run_pipeline, stream_pipeline
from app.pipeline.state import PipelineState


# ── S2: error code enum ─────────────────────────────────────────────────


def test_stage_error_code_enum() -> None:
    assert nodes._stage_error_code(Exception("authentication failed: 401")) == "llm_auth"
    # class name also participates (RateLimitError → llm_rate_limit)
    class RateLimitError(Exception):
        pass
    assert nodes._stage_error_code(RateLimitError("429")) == "llm_rate_limit"
    assert nodes._stage_error_code(Exception("Request timed out")) == "llm_timeout"
    assert nodes._stage_error_code(Exception("maximum context length exceeded")) == "llm_context_length"
    assert nodes._stage_error_code(Exception("something weird")) == "stage_error"


# ── _timed event emission ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timed_emits_started_and_succeeded() -> None:
    events: list[dict] = []

    async def on_event(e: dict) -> None:
        events.append(e)

    @nodes._timed("retrieval")
    async def node(state: dict) -> dict:
        state["retrieved_context"] = "lore"  # no real node — set via state
        return {"retrieved_context": "lore"}

    state: dict = {"iterations": 0, "on_event": on_event, "retrieved_context": "lore"}
    await node(state)

    assert [e["status"] for e in events] == ["started", "succeeded"]
    ok = events[1]
    assert ok["stage"] == "retrieval"
    assert ok["summary"] == {"chars": 4}  # whitelist: length only, no text


@pytest.mark.asyncio
async def test_timed_emits_failed_with_safe_code() -> None:
    events: list[dict] = []

    async def on_event(e: dict) -> None:
        events.append(e)

    secret = "sk-abc123 real secret"

    @nodes._timed("draft")
    async def node(state: dict) -> dict:
        raise RuntimeError(f"call failed with {secret}")

    state: dict = {"on_event": on_event}
    with pytest.raises(RuntimeError):
        await node(state)

    failed = [e for e in events if e["status"] == "failed"]
    assert len(failed) == 1
    # S1/S2: neither the raw exception text nor the key leaks; only enum.
    assert secret not in json.dumps(events)
    assert "sk-" not in json.dumps(events)
    assert failed[0]["code"] == "stage_error"
    assert failed[0]["stage"] == "draft"


def test_summary_whitelist_no_text_leak() -> None:
    """All whitelisted summaries contain only counters — no topic/prompt."""
    state: dict = {
        "topic": "SECRET_TOPIC_TEXT",
        "retrieved_context": "SECRET_LORE",
        "draft": "SECRET_DRAFT_TEXT",
        "refined": "SECRET_REFINED_TEXT",
        "score": 0.83,
        "safety_report": {"matched_count": 2, "max_severity": "medium"},
        "safety_passed": True,
    }
    for stage in ("retrieval", "draft", "refine", "evaluate", "safety_check"):
        s = json.dumps(nodes._stage_summary(stage, state))
        assert "SECRET" not in s, f"{stage} summary leaks text"
    # values are lengths/scores only
    assert nodes._stage_summary("draft", state)["chars"] == len("SECRET_DRAFT_TEXT")


# ── M1: skipped events per task_type ────────────────────────────────────


def test_active_stages_map_matches_should_run_stage() -> None:
    for tt in ("generate", "continue", "rewrite", "outline", "extract"):
        for stage in ("retrieval", "draft", "refine", "evaluate"):
            expected_active = __import__(
                "app.pipeline.graph", fromlist=["_should_run_stage"]
            )._should_run_stage(tt, stage)
            is_active = stage in _ACTIVE_STAGES[tt]
            assert expected_active == is_active, f"{tt}/{stage}"


# ── stream_pipeline event passthrough ───────────────────────────────────


@pytest.mark.asyncio
async def test_stream_pipeline_yields_stage_event_tuples() -> None:
    """With on_event=True, stage events surface as ('__event__', payload)
    tuples interleaved with token strings, starting with pipeline_start."""
    from unittest.mock import patch

    async def fake_run_pipeline(topic, provider_config, *, on_token=None,
                                on_event=None, **kwargs):
        if on_event is not None:
            await on_event({"type": "stage", "stage": "draft", "status": "started"})
        if on_token:
            await on_token("你好")
        return {"draft": "你好", "refined": "", "iterations": 1}

    with patch("app.pipeline.graph.run_pipeline", side_effect=fake_run_pipeline):
        items = []
        async for item in stream_pipeline("t", None, on_event=True):
            items.append(item)

    assert items[0][1]["type"] == "pipeline_start"
    kinds = [i[0] if isinstance(i, tuple) else "token" for i in items]
    assert "token" in kinds
    started_events = [i[1] for i in items if isinstance(i, tuple) and i[1].get("status") == "started"]
    assert started_events and started_events[0]["stage"] == "draft"


@pytest.mark.asyncio
async def test_stream_pipeline_no_events_without_on_event() -> None:
    """Backward compatible: no on_event → pure token strings (old path)."""
    from unittest.mock import patch

    async def fake_run_pipeline(topic, provider_config, *, on_token=None, **kwargs):
        if on_token:
            await on_token("纯文本")
        return {"draft": "纯文本", "refined": "", "iterations": 0}

    with patch("app.pipeline.graph.run_pipeline", side_effect=fake_run_pipeline):
        items = [item async for item in stream_pipeline("t", None)]

    assert all(isinstance(i, str) for i in items)
    assert "纯文本" in items


# ── P2-2: relationship tree serialization tests live in
# test_pipeline_writing_context.py (shares its _FakeAsyncSession fixtures).
