"""Tests for R9-④⑥ chapter-writing context and word-count control.

Covers:
- _build_writing_context block assembly (progress / prior chapters / word target)
- generate-branch system prompt injection (chapter blocks present in system_content)
- backward compatibility (no chapter fields → generic prompt, no crash)
- draft_node word-count post-check verdicts (regenerate / continue / accept)
- refine_node top-up instruction wiring
"""
import pytest

from app.pipeline import nodes


# ── _build_writing_context ───────────────────────────────────────────────


def test_writing_context_blocks_injected() -> None:
    """chapter_index + total + title + explicit target → all blocks present."""
    state: dict = {
        "chapter_index": 2,
        "total_chapters": 10,
        "chapter_title": "风起",
        "target_word_count": 2000,
        # no session → DB-backed blocks skipped, word target uses explicit
    }
    ctx = nodes._build_writing_context(state)
    assert "【章节进度】" in ctx
    assert "第3章《风起》" in ctx
    assert "3/10" in ctx
    assert "【字数要求】" in ctx
    assert "1700-2300" in ctx  # 2000 ± 15%


def test_writing_context_empty_state_still_has_word_default() -> None:
    """No chapter fields at all → no progress block, default 1000 target."""
    ctx = nodes._build_writing_context({})
    assert "【章节进度】" not in ctx
    assert "【字数要求】" in ctx
    assert "850-1150" in ctx  # 1000 ± 15%


# ── draft_node generate branch ───────────────────────────────────────────


def _chunk(content: str):
    return type(
        "Chunk",
        (),
        {"choices": [type("C", (), {"delta": type("D", (), {"content": content})()})()]},
    )()


@pytest.mark.asyncio
async def test_generate_branch_injects_chapter_context() -> None:
    """generate + writing_context → system prompt contains chapter blocks."""
    from unittest.mock import AsyncMock, patch

    state: dict = {
        "topic": "写下一章",
        "task_type": "generate",
        "chapter_index": 1,
        "total_chapters": 5,
        "chapter_title": "夜行",
        "target_word_count": 1500,
        "writing_context": "【章节进度】\n当前：第2章《夜行》",
    }

    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return _as_async_iter([_chunk("正文" * 800)])  # 1600 chars ≥ 0.9×1500

    with patch.object(nodes, "llm_draft", AsyncMock(side_effect=_capture_messages)):
        out = await nodes.draft_node(state)

    system = captured["system"]
    assert "专业小说写作助手" in system
    assert "【章节进度】" in system
    assert "第2章《夜行》" in system
    assert "【写作要求】" in system
    # Accept verdict: 1600/1500 ≈ 1.07 → within [0.9, 1.2] → no retry flag.
    assert "word_count_retry" not in out


@pytest.mark.asyncio
async def test_generate_backward_compatible_without_context() -> None:
    """generate without chapter fields → generic-style prompt, no crash."""
    from unittest.mock import AsyncMock, patch

    state: dict = {"topic": "写一段", "task_type": "generate"}
    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return _as_async_iter([_chunk("短正文。")])

    with patch.object(nodes, "llm_draft", AsyncMock(side_effect=_capture_messages)):
        await nodes.draft_node(state)

    assert "专业小说写作助手" in captured["system"]
    assert "【章节进度】" not in captured["system"]


# ── word-count post-check verdicts ───────────────────────────────────────


@pytest.mark.asyncio
async def test_post_check_continue_verdict() -> None:
    """Draft at 0.6 ≤ ratio < 0.9 → 'continue' retry flag."""
    from unittest.mock import AsyncMock, patch

    state: dict = {"topic": "t", "task_type": "generate", "target_word_count": 1000}

    with patch.object(nodes, "llm_draft", AsyncMock(return_value=_as_async_iter([_chunk("字" * 750)]))):
        out = await nodes.draft_node(state)

    assert out["word_count_retry"] == "continue"


@pytest.mark.asyncio
async def test_post_check_regenerate_verdict() -> None:
    """Draft below 0.6× target → 'regenerate' retry flag."""
    from unittest.mock import AsyncMock, patch

    state: dict = {"topic": "t", "task_type": "generate", "target_word_count": 1000}

    with patch.object(nodes, "llm_draft", AsyncMock(return_value=_as_async_iter([_chunk("字" * 500)]))):
        out = await nodes.draft_node(state)

    assert out["word_count_retry"] == "regenerate"


@pytest.mark.asyncio
async def test_post_check_skipped_for_outline() -> None:
    """Non-generate task types never get the retry flag."""
    from unittest.mock import AsyncMock, patch

    state: dict = {"topic": "t", "task_type": "outline"}

    with patch.object(nodes, "llm_draft", AsyncMock(return_value=_as_async_iter([_chunk("短")]))):
        out = await nodes.draft_node(state)

    assert "word_count_retry" not in out


# ── refine_node top-up wiring ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refine_node_appends_word_count_instruction() -> None:
    """word_count_retry='continue' → refine user content carries top-up text."""
    from unittest.mock import AsyncMock, patch

    state: dict = {
        "draft": "初稿",
        "task_type": "generate",
        "word_count_retry": "continue",
        "target_word_count": 1000,
    }
    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["user"] = messages[1]["content"]
        return _as_async_iter([_chunk("扩写后的正文")])

    with patch.object(nodes, "llm_refine", AsyncMock(side_effect=_capture_messages)):
        out = await nodes.refine_node(state)

    assert "【字数补足】" in captured["user"]
    assert out["refined"] == "扩写后的正文"
    assert out["iterations"] == 1


# ── helpers ──────────────────────────────────────────────────────────────


def _as_async_iter(items):
    async def _gen():
        for item in items:
            yield item

    return _gen()
