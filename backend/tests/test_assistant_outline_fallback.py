"""Tests for the assistant outline fallback (09-14 优化3).

New works with a title-only outline have no chapter content; the assistant
used to assemble an EMPTY context and answer blind. Now _load_work_context
falls back to metadata_json.outline when the chapter blocks come back empty.
"""
import pytest

from app.api.chat import ChatRequest, _load_work_context


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


class _FakeSession:
    """Call-order aware: get_document→scalar(doc), chapters rows→execute,
    count→scalar(0), outline-fallback get_document→scalar(doc)."""

    def __init__(self, doc, chapter_rows):
        self._doc = doc
        self._chapter_rows = chapter_rows
        self._scalar_seq = ["doc", "count", "doc"]

    async def scalar(self, *_a, **_k):
        kind = self._scalar_seq.pop(0) if self._scalar_seq else "count"
        return self._doc if kind == "doc" else 0

    async def execute(self, *_a, **_k):
        return _FakeResult(self._chapter_rows)


class _FakeDoc:
    id = 7
    metadata_json = {"outline": "第一卷 崛起\n第一章 入门\n第二章 突破"}


@pytest.mark.asyncio
async def test_outline_fallback_when_no_chapters() -> None:
    """Empty chapter list + outline present → outline becomes the context."""
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}], context_doc_id=7)
    session = _FakeSession(_FakeDoc(), [])
    ctx = await _load_work_context(session, req)
    assert "第一章 入门" in ctx


@pytest.mark.asyncio
async def test_chapter_context_wins_when_present() -> None:
    """Real chapter content → no outline fallback (execute returns rows)."""
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}], context_doc_id=7)
    session = _FakeSession(_FakeDoc(), [])
    # Simulate a chapter row by injecting execute results.
    row = type("R", (), {"title": "第一章 入门", "content_text": "正文内容"})()
    session._chapter_rows_override = [row]  # noqa: SLF001

    async def _execute(*_a, **_k):
        return _FakeResult(session._chapter_rows_override)

    session.execute = _execute  # type: ignore[method-assign]
    ctx = await _load_work_context(session, req)
    assert "正文内容" in ctx


@pytest.mark.asyncio
async def test_no_outline_and_no_chapters_empty_context() -> None:
    """Nothing at all → empty string (no crash)."""
    doc = type("D", (), {"id": 7, "metadata_json": {}})()
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}], context_doc_id=7)
    session = _FakeSession(doc, [])
    ctx = await _load_work_context(session, req)
    assert ctx == ""
