"""Unit tests for app.services.chapter.

Uses MockAsyncSession to avoid needing a real PostgreSQL+pgvector
instance. Verifies that:
  - create_chapter auto-computes word_count when content_text is non-empty
  - get_chapter raises ChapterNotFound when scalar returns None
  - update_chapter applies only sent fields and bumps word_count on content change
  - delete_chapter calls session.delete
"""
from __future__ import annotations

import pytest

from app.models.chapter import Chapter
from app.schemas.novel_memory import ChapterCreate, ChapterUpdate
from app.services.chapter import (
    ChapterNotFound,
    create_chapter,
    delete_chapter,
    get_chapter,
    get_chapter_by_index,
    list_chapters,
    reorder_chapters,
    update_chapter,
    update_chapter_embedding,
)


@pytest.mark.asyncio
async def test_create_chapter_auto_computes_word_count(mock_session, monkeypatch):
    # Stub auto-embedding — the test targets CRUD, not the embedding API.
    async def _noop_embed(*args, **kwargs):
        return [0.0] * 8

    monkeypatch.setattr("app.llm.embedding.embed_text", _noop_embed)

    payload = ChapterCreate(
        chapter_index=1,
        title="第一章",
        content_text="这是第一章的内容，长度大于零。",
    )
    ch = await create_chapter(mock_session, payload)
    assert ch.word_count == len(payload.content_text)
    assert ch.status == "draft"
    assert mock_session.added == [ch]
    assert mock_session.commits == 1
    # create_chapter refreshes twice: once after flush, once post-commit
    # (re-loads after the embedding flush expires updated_at).
    assert mock_session.refreshes == 2


@pytest.mark.asyncio
async def test_create_chapter_keeps_explicit_word_count(mock_session):
    """If caller supplies word_count, do not override it."""
    payload = ChapterCreate(
        chapter_index=1,
        title="Ch1",
        content_text="abc",
        word_count=999,
    )
    ch = await create_chapter(mock_session, payload)
    assert ch.word_count == 999


@pytest.mark.asyncio
async def test_list_chapters_returns_items_and_total(mock_session):
    fake_items = [Chapter(id=1, chapter_index=1, title="A")]
    from tests.conftest import _FakeResult
    mock_session.set_execute_results([_FakeResult(scalars=fake_items)])
    mock_session.set_scalar_results([42])

    items, total = await list_chapters(mock_session)
    assert items == fake_items
    assert total == 42


@pytest.mark.asyncio
async def test_list_chapters_filters_by_novel_id(mock_session):
    """When novel_id is supplied, both queries must receive the filter."""
    from tests.conftest import _FakeResult
    mock_session.set_execute_results([_FakeResult(scalars=[])])
    mock_session.set_scalar_results([0])

    await list_chapters(mock_session, novel_id=5)
    # No assertion on the SQL itself — mock_session discards the stmt.
    # Test only verifies no exception and one execute + one scalar.
    assert mock_session._execute_idx == 1
    assert mock_session._scalar_idx == 1


@pytest.mark.asyncio
async def test_get_chapter_returns_instance(mock_session):
    ch = Chapter(id=7, chapter_index=2, title="Ch2")
    mock_session.set_scalar_results([ch])
    result = await get_chapter(mock_session, 7)
    assert result is ch


@pytest.mark.asyncio
async def test_get_chapter_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(ChapterNotFound):
        await get_chapter(mock_session, 999)


@pytest.mark.asyncio
async def test_get_chapter_by_index_returns_none_when_absent(mock_session):
    mock_session.set_scalar_results([None])
    result = await get_chapter_by_index(mock_session, 0, 5)
    assert result is None


@pytest.mark.asyncio
async def test_update_chapter_applies_sent_fields_only(mock_session):
    ch = Chapter(id=1, chapter_index=1, title="old", content_text="abc", word_count=3)
    mock_session.set_scalar_results([ch])

    payload = ChapterUpdate(title="new title", status="refined")
    updated = await update_chapter(mock_session, 1, payload)
    assert updated.title == "new title"
    assert updated.status == "refined"
    # chapter_index NOT in payload — must remain unchanged.
    assert updated.chapter_index == 1
    # content_text NOT in payload — word_count must remain unchanged.
    assert updated.word_count == 3
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_update_chapter_auto_updates_word_count_on_content_change(mock_session, monkeypatch):
    # Stub auto-embedding — the test targets word_count logic, not the API.
    async def _noop_embed(*args, **kwargs):
        return [0.0] * 8

    monkeypatch.setattr("app.llm.embedding.embed_text", _noop_embed)

    ch = Chapter(id=1, chapter_index=1, title="x", content_text="abc", word_count=3)
    mock_session.set_scalar_results([ch])

    payload = ChapterUpdate(content_text="更长的新内容")
    updated = await update_chapter(mock_session, 1, payload)
    assert updated.word_count == len("更长的新内容")


@pytest.mark.asyncio
async def test_update_chapter_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(ChapterNotFound):
        await update_chapter(mock_session, 1, ChapterUpdate(title="x"))


@pytest.mark.asyncio
async def test_update_chapter_embedding_persists_vector(mock_session):
    ch = Chapter(id=1, chapter_index=1, title="x")
    mock_session.set_scalar_results([ch])
    vec = [0.1] * 1536
    await update_chapter_embedding(mock_session, 1, vec)
    assert ch.embedding == vec
    # update_chapter_embedding only flushes — the caller (create_chapter /
    # update_chapter) commits.  This matches the session-embed-order rule.
    assert mock_session.commits == 0


@pytest.mark.asyncio
async def test_delete_chapter_calls_session_delete(mock_session):
    ch = Chapter(id=1, chapter_index=1, title="x")
    mock_session.set_scalar_results([ch])
    await delete_chapter(mock_session, 1)
    assert mock_session.deleted == [ch]
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_delete_chapter_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(ChapterNotFound):
        await delete_chapter(mock_session, 1)


@pytest.mark.asyncio
async def test_reorder_chapters_single_query_and_sorts(mock_session):
    """Reorder must load chapters with ONE query (IN clause), not one per row."""
    from tests.conftest import _FakeResult

    ch1 = Chapter(id=1, chapter_index=1, title="A", novel_id=5)
    ch2 = Chapter(id=2, chapter_index=2, title="B", novel_id=5)
    mock_session.set_execute_results([_FakeResult(scalars=[ch1, ch2])])

    ordered = await reorder_chapters(
        mock_session, novel_id=5, ordered=[(2, 1), (1, 2)]
    )

    assert mock_session._execute_idx == 1  # single IN query, no per-row fetch
    assert mock_session.commits == 1
    assert ordered[0].id == 2 and ordered[0].chapter_index == 1
    assert ordered[1].id == 1 and ordered[1].chapter_index == 2


@pytest.mark.asyncio
async def test_reorder_chapters_raises_when_missing(mock_session):
    from tests.conftest import _FakeResult

    mock_session.set_execute_results([_FakeResult(scalars=[])])
    with pytest.raises(ChapterNotFound):
        await reorder_chapters(mock_session, novel_id=5, ordered=[(1, 1)])
