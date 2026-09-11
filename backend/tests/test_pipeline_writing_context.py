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


@pytest.mark.asyncio
async def test_writing_context_blocks_injected() -> None:
    """chapter_index + total + title + explicit target → all blocks present."""
    state: dict = {
        "chapter_index": 2,
        "total_chapters": 10,
        "chapter_title": "风起",
        "target_word_count": 2000,
        # no session → DB-backed blocks skipped, word target uses explicit
    }
    ctx = await nodes._build_writing_context(state)
    assert "【章节进度】" in ctx
    assert "第3章《风起》" in ctx
    assert "3/10" in ctx
    assert "【字数要求】" in ctx
    assert "1700-2300" in ctx  # 2000 ± 15%


@pytest.mark.asyncio
async def test_writing_context_empty_state_still_has_word_default() -> None:
    """No chapter fields at all → no progress block, default 1000 target."""
    ctx = await nodes._build_writing_context({})
    assert "【章节进度】" not in ctx
    assert "【字数要求】" in ctx
    assert "850-1150" in ctx  # 1000 ± 15%


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeAsyncSession:
    """Minimal AsyncSession stand-in: pops a queued result per execute().

    Regression guard for R9 review P1-1 — the two DB lookups inside
    _build_writing_context MUST await session.execute; a missing await
    raises AttributeError (coroutine has no .scalars()) which the
    surrounding except swallows, silently dropping the blocks.
    """

    def __init__(self, results):
        self._results = list(results)
        self.executed = 0

    async def execute(self, *_args, **_kwargs):
        self.executed += 1
        return self._results.pop(0)


class _FakeChapter:
    def __init__(self, chapter_index, title, summary="", content_text="", word_count=0):
        self.chapter_index = chapter_index
        self.title = title
        self.summary = summary
        self.content_text = content_text
        self.word_count = word_count


@pytest.mark.asyncio
async def test_writing_context_with_session_renders_prior_chapters_and_median() -> None:
    """P1-1 regression: with a (fake) async session the DB-backed blocks render.

    Prior-chapter lookup returns chapters 1-2; median lookup returns
    [1500, 2000, 2500] → target 2000 → prompt advertises 1700-2300.
    """
    from types import SimpleNamespace

    fake_session = _FakeAsyncSession([
        _FakeResult([  # prior chapters (desc order, limit 2)
            _FakeChapter(1, "第二章", summary="前章梗概"),
            _FakeChapter(0, "第一章", summary="首章梗概"),
        ]),
        _FakeResult([1500, 2500, 2000]),  # word_count rows for median
    ])
    state: dict = {
        "chapter_index": 2,
        "novel_id": 1,
        "session": fake_session,
        # no explicit target → derived from median
    }
    ctx = await nodes._build_writing_context(state)

    assert fake_session.executed == 2
    assert "【前文背景】" in ctx
    assert "第1章《第一章》" in ctx and "第2章《第二章》" in ctx
    # P1-2 regression: derived median target is written back into state so
    # the post-check uses the same number as the prompt.
    assert state["target_word_count"] == 2000
    assert "1700-2300" in ctx


@pytest.mark.asyncio
async def test_writing_context_execute_without_await_would_drop_blocks() -> None:
    """Documents the failure mode P1-1 fixed: a sync-execute fake session
    (returning a coroutine-like object) must NOT silently produce context
    without the DB blocks — i.e. the fixed code awaits, so blocks appear."""
    fake_session = _FakeAsyncSession([
        _FakeResult([_FakeChapter(0, "第一章", summary="梗概")]),
        _FakeResult([2000]),
    ])
    ctx = await nodes._build_writing_context({"novel_id": 1, "session": fake_session})
    assert "【前文背景】" in ctx  # would be absent pre-fix


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
    # Accept verdict: 1600/1500 ≈ 1.07 → within [0.9, 1.2] → retry cleared.
    assert out["word_count_retry"] == ""


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


@pytest.mark.asyncio
async def test_post_check_clears_stale_verdict() -> None:
    """P2-1: once within range the verdict is explicitly cleared (empty
    string), so refine_node won't keep appending top-up instructions."""
    from unittest.mock import AsyncMock, patch

    state: dict = {
        "topic": "t",
        "task_type": "generate",
        "target_word_count": 1000,
        "word_count_retry": "continue",  # stale from previous iteration
    }

    with patch.object(nodes, "llm_draft", AsyncMock(return_value=_as_async_iter([_chunk("字" * 1000)]))):
        out = await nodes.draft_node(state)

    assert out["word_count_retry"] == ""


def test_chat_request_rejects_out_of_bounds_chapter_fields() -> None:
    """P1-3: unbounded/absurd client values are rejected with 422."""
    from pydantic import ValidationError

    from app.api.chat import ChatRequest

    def _req(**kwargs):
        return ChatRequest(messages=[{"role": "user", "content": "x"}], **kwargs)

    # absurd / negative numerics
    with pytest.raises(ValidationError):
        _req(chapter_index=-3)
    with pytest.raises(ValidationError):
        _req(total_chapters=999999999)
    with pytest.raises(ValidationError):
        _req(target_word_count=-5)
    with pytest.raises(ValidationError):
        _req(target_word_count=0)
    # unbounded title text
    with pytest.raises(ValidationError):
        _req(chapter_title="长" * 500)
    # sane values pass and defaults hold
    ok = _req(chapter_index=0, total_chapters=10, chapter_title="风起", target_word_count=2000)
    assert ok.chapter_title == "风起"
    base = _req()
    assert base.chapter_index is None and base.chapter_title == ""


# ── helpers ──────────────────────────────────────────────────────────────


def _as_async_iter(items):
    async def _gen():
        for item in items:
            yield item

    return _gen()
