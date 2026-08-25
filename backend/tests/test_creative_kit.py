"""Service-layer tests for apply_creative_kit (R7-2 P1/P0).

Uses the shared mock_session — no database required. Covers: single-
transaction semantics (one commit, rollback on failure), in-kit dedup,
conflict-skips reported via rowcount, outline PATCH-merge touching only
its own keys, document row locking, and version bumping.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.models.document import Document
from app.schemas.creative_kit import CreativeKitApplyRequest
from app.services.creative_kit import apply_creative_kit
from app.services.document import DocumentNotFound


def _doc(metadata=None) -> Document:
    now = datetime.now(timezone.utc)
    return Document(
        id=7,
        title="T",
        content_html="",
        content_text="",
        word_count=0,
        metadata_json=metadata or {"settings": {"font": 16}},
        version=3,
        doc_type="novel",
        category="",
        status="active",
        cover_url="",
        created_at=now,
        updated_at=now,
    )


class _RecordingSession:
    """Captures the SELECT issued by get_document (to assert FOR UPDATE) and
    delegates everything else to the shared mock_session."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.statements: list = []
        self._orig_scalar = inner.scalar

    async def scalar(self, stmt):
        self.statements.append(stmt)
        return await self._orig_scalar(stmt)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _rowcount(result: int) -> SimpleNamespace:
    return SimpleNamespace(rowcount=result)


@pytest.mark.asyncio
async def test_apply_locks_document_row(mock_session) -> None:
    """P0: the whole batch runs under the document row lock — concurrent
    applies and editor-save merges serialize instead of lost-updating."""
    mock_session.set_scalar_results([_doc()])
    recorder = _RecordingSession(mock_session)
    await apply_creative_kit(
        recorder, 7,
        CreativeKitApplyRequest(world_settings=[], characters=[], outline=""),
    )
    assert recorder.statements
    sql = str(recorder.statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_empty_kit_creates_nothing_and_commits(mock_session) -> None:
    doc = _doc()
    mock_session.set_scalar_results([doc])
    res = await apply_creative_kit(
        mock_session, 7,
        CreativeKitApplyRequest(world_settings=[], characters=[], outline=""),
    )
    assert res.created_world_settings == 0
    assert res.created_characters == 0
    assert res.outline_applied is False
    assert mock_session.commits == 1
    assert doc.version == 3  # unchanged — nothing touched the document


@pytest.mark.asyncio
async def test_insert_creates_and_reports_skips(mock_session) -> None:
    """Two kit world settings + one duplicate name within the kit: rows are
    deduped in-kit, then rowcount reports what the constraint allowed."""
    doc = _doc()
    mock_session.set_scalar_results([doc])
    mock_session.set_execute_results([_rowcount(1), _rowcount(0)])
    res = await apply_creative_kit(
        mock_session, 7,
        CreativeKitApplyRequest(
            world_settings=[
                {"title": "大陆", "content_text": "a"},
                {"title": "大陆", "content_text": "dupe-in-kit"},
                {"title": "宗门", "content_text": "b"},
            ],
            characters=[
                {"name": "主角", "role": "主角"},
                {"name": "配角", "role": "配角"},
            ],
            outline="1. 开局",
        ),
    )
    # ws_rows = 2 (in-kit dup dropped); DB accepted 1 → 1 created, 1 skipped.
    assert res.created_world_settings == 1
    assert res.skipped_world_settings == 1
    # characters: 2 rows attempted, DB accepted 0 → 0 created, 2 skipped.
    assert res.created_characters == 0
    assert res.skipped_characters == 2
    assert res.outline_applied is True


@pytest.mark.asyncio
async def test_outline_merges_only_own_keys(mock_session) -> None:
    """P0: merging the outline must not clobber concurrent keys (settings).
    Only outline + outline_updated_at are written to metadata_json."""
    doc = _doc({"settings": {"font": 18}, "outline": "旧大纲"})
    mock_session.set_scalar_results([doc])
    mock_session.set_execute_results([_rowcount(0), _rowcount(0)])
    res = await apply_creative_kit(
        mock_session, 7,
        CreativeKitApplyRequest(outline="全新大纲"),
    )
    merged = doc.metadata_json
    assert merged["settings"] == {"font": 18}  # untouched
    assert merged["outline"] == "全新大纲"
    assert "outline_updated_at" in merged  # server-stamped fresh timestamp
    assert doc.version == 4  # document changed → version bumped
    assert res.outline_applied is True
    # response carries the same merged document (validated into DocumentRead)
    assert res.document.metadata_json["outline"] == "全新大纲"
    assert res.document.metadata_json["settings"] == {"font": 18}


@pytest.mark.asyncio
async def test_novel_id_forced_from_path(mock_session) -> None:
    """Client-supplied novel_id is ignored; the path doc_id wins."""
    doc = _doc()
    mock_session.set_scalar_results([doc])
    mock_session.set_execute_results([_rowcount(1), _rowcount(1)])
    executed: list = []

    async def _capture(stmt):
        executed.append(stmt)
        return await mock_session._orig_execute(stmt)

    mock_session._orig_execute = mock_session.execute
    mock_session.execute = _capture
    await apply_creative_kit(
        mock_session, 7,
        CreativeKitApplyRequest(
            world_settings=[{"title": "W", "novel_id": 999}],
            characters=[{"name": "C", "novel_id": 999}],
        ),
    )

    for stmt, table in zip(executed, ("world_settings", "characters")):
        params = stmt.compile(dialect=postgresql.dialect()).params
        params = params if isinstance(params, list) else [params]
        assert table in str(stmt.compile(dialect=postgresql.dialect()))
        # executemany binds columns as "<col>_m<row>" — read all novel_id binds.
        novel_ids = [v for k, v in params[0].items() if k.startswith("novel_id")]
        assert novel_ids and all(int(v) == 7 for v in novel_ids)


@pytest.mark.asyncio
async def test_failure_rolls_back_whole_batch(mock_session) -> None:
    """P1: any failure aborts the batch — no partial applies survive."""
    doc = _doc()
    mock_session.set_scalar_results([doc])

    async def _boom(stmt):
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    mock_session.execute = _boom
    with pytest.raises(IntegrityError):
        await apply_creative_kit(
            mock_session, 7,
            CreativeKitApplyRequest(
                world_settings=[{"title": "W"}],
                characters=[{"name": "C"}],
                outline="1. x",
            ),
        )
    assert mock_session.rolled_back == 1
    assert mock_session.commits == 0


@pytest.mark.asyncio
async def test_missing_document_propagates(mock_session) -> None:
    mock_session.set_scalar_results([])
    with pytest.raises(DocumentNotFound):
        await apply_creative_kit(
            mock_session, 404,
            CreativeKitApplyRequest(world_settings=[]),
        )