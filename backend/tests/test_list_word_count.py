"""Tests for list_documents chapter-aggregated word_count (09-14 fix).

R10-⑨ moved stats-page aggregation to chapters, but the works LIST still
returned documents.word_count — a column the editor never writes — so every
card showed 0 字 while the stats page showed real numbers. Fix: the list
service aggregates chapters.word_count per document and fills it on the
returned rows (read-only join; no DB write, no document column touched).

Uses the shared mock_session (statement capture) — no live DB needed.
"""
import pytest

from app.models.document import Document
from app.services.document import list_documents


def _doc(doc_id: int, word_count: int = 0) -> Document:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return Document(
        id=doc_id,
        title=f"T{doc_id}",
        content_html="",
        content_text="",
        word_count=word_count,  # stale column — always 0 for real writing
        version=1,
        doc_type="novel",
        category="",
        status="active",
        cover_url="",
        created_at=now,
        updated_at=now,
    )


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)

    def all(self):
        return self._rows


def _captured_statements(mock_session):
    """Collect every SQL string the service executes (execute + scalar)."""
    statements: list[str] = []
    inner_scalar = mock_session.scalar

    async def _scalar(stmt, *a, **k):
        statements.append(str(stmt))
        return await inner_scalar(stmt, *a, **k)

    mock_session.scalar = _scalar  # type: ignore[method-assign]

    inner_execute = mock_session.execute

    async def _execute(stmt, *a, **k):
        statements.append(str(stmt))
        return await inner_execute(stmt, *a, **k)

    mock_session.execute = _execute  # type: ignore[method-assign]
    return statements


@pytest.mark.asyncio
async def test_word_count_query_joins_chapters(mock_session) -> None:
    """list_documents issues a per-document chapter word aggregation."""
    mock_session.set_scalar_results([2])  # total count
    mock_session.set_execute_results([_Result([_doc(1), _doc(2)]), _Result([(1, 500), (2, 0)])])
    statements = _captured_statements(mock_session)

    items, total = await list_documents(mock_session)

    assert total == 2
    assert [i.id for i in items] == [1, 2]
    assert any("chapters" in s and "word_count" in s for s in statements), (
        "list must aggregate chapter word counts"
    )


@pytest.mark.asyncio
async def test_word_count_filled_from_chapter_aggregate(mock_session) -> None:
    """Returned rows carry the aggregated chapter words, not the stale column."""
    mock_session.set_scalar_results([2])
    mock_session.set_execute_results([_Result([_doc(1, word_count=0), _doc(2, word_count=7)]), _Result([(1, 2050), (2, 0)])])

    items, _ = await list_documents(mock_session)

    by_id = {d.id: d for d in items}
    assert by_id[1].word_count == 2050  # chapter sum replaces stale 0
    assert by_id[2].word_count == 0  # no chapters → 0, not the stale 7


@pytest.mark.asyncio
async def test_no_chapter_rows_leaves_zero(mock_session) -> None:
    """Missing aggregation row (doc without chapters) → word_count 0."""
    mock_session.set_scalar_results([1])
    mock_session.set_execute_results([_Result([_doc(9)]), _Result([])])

    items, _ = await list_documents(mock_session)

    assert items[0].word_count == 0
