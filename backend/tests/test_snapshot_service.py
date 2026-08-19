"""Unit tests for app.services.snapshot (R5-4 ????).

Uses MockAsyncSession so no real PostgreSQL is required. Verifies:
  - create_snapshot stores fields, computes word_count, and commits
  - create_snapshot trims the per-chapter cap (oldest rows dropped)
  - get_snapshot is owner-scoped and raises SnapshotNotFound on miss
  - list_snapshots returns (items, total)
  - delete_snapshot removes the row
  - restore_snapshot copies snapshot text onto the chapter via update_chapter
    and rejects out-of-scope snapshots/chapters
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.chapter import Chapter
from app.models.chapter_snapshot import ChapterSnapshot
from app.services.chapter import ChapterNotFound
from app.services.snapshot import (
    MAX_SNAPSHOTS,
    SnapshotNotFound,
    create_snapshot,
    delete_snapshot,
    get_snapshot,
    list_snapshots,
    restore_snapshot,
)
from tests.conftest import _FakeResult


@pytest.mark.asyncio
async def test_create_snapshot_stores_fields_and_commits(mock_session):
    snap = await create_snapshot(
        mock_session,
        owner_key_hash="hash-a",
        novel_id=7,
        chapter_id=10,
        content_text="hello world",
        title="Ch 1",
        reason="insert",
    )
    assert isinstance(snap, ChapterSnapshot)
    assert snap.owner_key_hash == "hash-a"
    assert snap.novel_id == 7
    assert snap.chapter_id == 10
    assert snap.content_text == "hello world"
    assert snap.word_count == len("hello world")
    assert snap.reason == "insert"
    assert mock_session.added == [snap]
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_create_snapshot_defaults(mock_session):
    snap = await create_snapshot(
        mock_session,
        owner_key_hash="hash-a",
        novel_id=7,
        chapter_id=10,
        content_text="",
    )
    assert snap.reason == "save"
    assert snap.title == ""
    assert snap.word_count == 0


@pytest.mark.asyncio
async def test_create_snapshot_trims_excess_to_cap(mock_session):
    # First execute -> excess ids to drop; second execute -> the delete stmt.
    mock_session.set_execute_results([_FakeResult(scalars=[99, 98]), _FakeResult()])
    snap = await create_snapshot(
        mock_session,
        owner_key_hash="hash-a",
        novel_id=7,
        chapter_id=10,
        content_text="x",
    )
    assert snap.chapter_id == 10
    assert mock_session._execute_idx == 2  # excess select + delete
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_get_snapshot_returns_row(mock_session):
    fake = ChapterSnapshot(id=5, chapter_id=10, content_text="t")
    mock_session.set_scalar_results([fake])
    snap = await get_snapshot(mock_session, 5, owner_key_hash="hash-a")
    assert snap is fake


@pytest.mark.asyncio
async def test_get_snapshot_missing_raises(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(SnapshotNotFound):
        await get_snapshot(mock_session, 5, owner_key_hash="hash-a")


@pytest.mark.asyncio
async def test_list_snapshots_returns_items_and_total(mock_session):
    fake = ChapterSnapshot(id=1, chapter_id=10, content_text="a")
    mock_session.set_execute_results([_FakeResult(scalars=[fake])])
    mock_session.set_scalar_results([3])
    items, total = await list_snapshots(
        mock_session, owner_key_hash="h", novel_id=7, chapter_id=10
    )
    assert items == [fake]
    assert total == 3


@pytest.mark.asyncio
async def test_delete_snapshot_deletes_and_commits(mock_session):
    fake = ChapterSnapshot(id=5, chapter_id=10)
    mock_session.set_scalar_results([fake])
    await delete_snapshot(mock_session, 5, owner_key_hash="hash-a")
    assert mock_session.deleted == [fake]
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_restore_snapshot_copies_text_to_chapter(mock_session, monkeypatch):
    fake_snap = ChapterSnapshot(
        id=5, novel_id=7, chapter_id=10, content_text="restored text"
    )
    fake_chapter = Chapter(id=10, novel_id=7, title="Ch")
    mock_session.set_scalar_results([fake_snap, fake_chapter])

    calls: list = []

    async def fake_update_chapter(session, chapter_id, payload):
        calls.append((chapter_id, payload))
        return fake_chapter

    monkeypatch.setattr(
        "app.services.snapshot.update_chapter", fake_update_chapter
    )

    result = await restore_snapshot(
        mock_session,
        snapshot_id=5,
        owner_key_hash="hash-a",
        novel_id=7,
        chapter_id=10,
    )
    assert result is fake_chapter
    assert len(calls) == 1
    chapter_id, payload = calls[0]
    assert chapter_id == 10
    assert payload.content_text == "restored text"


@pytest.mark.asyncio
async def test_restore_snapshot_rejects_wrong_novel(mock_session):
    fake_snap = ChapterSnapshot(
        id=5, novel_id=7, chapter_id=10, content_text="t"
    )
    mock_session.set_scalar_results([fake_snap])
    with pytest.raises(SnapshotNotFound):
        await restore_snapshot(
            mock_session,
            snapshot_id=5,
            owner_key_hash="hash-a",
            novel_id=999,
            chapter_id=10,
        )


@pytest.mark.asyncio
async def test_restore_snapshot_rejects_wrong_chapter(mock_session):
    fake_snap = ChapterSnapshot(
        id=5, novel_id=7, chapter_id=10, content_text="t"
    )
    mock_session.set_scalar_results([fake_snap])
    with pytest.raises(SnapshotNotFound):
        await restore_snapshot(
            mock_session,
            snapshot_id=5,
            owner_key_hash="hash-a",
            novel_id=7,
            chapter_id=11,
        )


@pytest.mark.asyncio
async def test_restore_snapshot_rejects_missing_chapter(mock_session):
    fake_snap = ChapterSnapshot(
        id=5, novel_id=7, chapter_id=10, content_text="t"
    )
    mock_session.set_scalar_results([fake_snap, None])
    with pytest.raises(ChapterNotFound):
        await restore_snapshot(
            mock_session,
            snapshot_id=5,
            owner_key_hash="hash-a",
            novel_id=7,
            chapter_id=10,
        )
