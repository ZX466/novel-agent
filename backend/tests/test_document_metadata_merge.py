"""Tests for update_document metadata_json merge semantics (R7-2 P0 fix).

update_document merges metadata_json only when merge_metadata=True (used by the
editor-save / Creative Kit flows); the default keeps the original replace
behaviour so unrelated callers are unaffected.

The merge path holds a row lock (SELECT ... FOR UPDATE) so concurrent merges
serialize and read each other's committed values — no lost updates.
"""
from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.models.document import Document
from app.schemas.document import DocumentUpdate
from app.services.document import update_document


def _doc(metadata=None) -> Document:
    return Document(
        id=1,
        title="T",
        content_text="",
        word_count=0,
        metadata_json=metadata or {},
        version=0,
    )


def _compile(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class _RecordingSession:
    """Wraps the mock_session to capture the SELECT statement issued by
    get_document so tests can assert the row lock is (or is not) applied."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.statements: list = []
        self._orig_scalar = inner.scalar

    async def scalar(self, stmt):
        self.statements.append(stmt)
        return await self._orig_scalar(stmt)

    def __getattr__(self, name):
        return getattr(self.inner, name)


@pytest.mark.asyncio
async def test_merge_true_merges_preserving_unrelated_keys(mock_session) -> None:
    doc = _doc({"outline": "v1", "genre": "x"})
    mock_session.set_scalar_results([doc])
    await update_document(
        mock_session, 1, DocumentUpdate(metadata_json={"theme": "y"}),
        merge_metadata=True,
    )
    assert doc.metadata_json == {"outline": "v1", "genre": "x", "theme": "y"}


@pytest.mark.asyncio
async def test_merge_true_payload_key_wins_on_conflict(mock_session) -> None:
    doc = _doc({"outline": "old", "genre": "x"})
    mock_session.set_scalar_results([doc])
    await update_document(
        mock_session, 1, DocumentUpdate(metadata_json={"outline": "new"}),
        merge_metadata=True,
    )
    assert doc.metadata_json == {"outline": "new", "genre": "x"}


@pytest.mark.asyncio
async def test_default_false_replaces_wholesale(mock_session) -> None:
    doc = _doc({"outline": "drop-me", "genre": "x"})
    mock_session.set_scalar_results([doc])
    await update_document(
        mock_session, 1, DocumentUpdate(metadata_json={"theme": "y"}),
    )
    assert doc.metadata_json == {"theme": "y"}


@pytest.mark.asyncio
async def test_merge_true_locks_row_for_update(mock_session) -> None:
    """P0: the merge path issues SELECT ... FOR UPDATE so concurrent merges
    serialize on the row — the second writer re-reads the committed value
    before merging instead of overwriting from a stale base."""
    doc = _doc({"settings": "s1"})
    mock_session.set_scalar_results([doc])
    recorder = _RecordingSession(mock_session)
    await update_document(
        recorder, 1, DocumentUpdate(metadata_json={"theme": "y"}),
        merge_metadata=True,
    )
    assert recorder.statements, "expected a SELECT on the document"
    assert "FOR UPDATE" in _compile(recorder.statements[0])


@pytest.mark.asyncio
async def test_replace_path_does_not_lock(mock_session) -> None:
    """Default replace semantics must NOT lock — read-only callers and plain
    PATCHes keep their current behaviour."""
    doc = _doc({"settings": "s1"})
    mock_session.set_scalar_results([doc])
    recorder = _RecordingSession(mock_session)
    await update_document(
        recorder, 1, DocumentUpdate(metadata_json={"theme": "y"}),
    )
    assert recorder.statements
    assert "FOR UPDATE" not in _compile(recorder.statements[0])