"""Unit tests for app.services.retrieval.

Mocks `embed_text` so no LLM call is made. Mocks session.execute to
return pre-built rows (each row is a tuple (orm_instance, distance)).
Verifies:
  - retrieve merges 4 collections and sorts by descending score
  - max_distance filter drops irrelevant hits
  - single-collection helpers (retrieve_chapters etc.) return only that collection
  - empty query raises ValueError (propagated from embed_text)
  - a missing novel_id is rejected (cross-novel retrieval guard)

`retrieve()` REQUIRES novel_id — without it, a query would search every
novel's memory at once. Every call below passes an explicit novel_id.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.chapter import Chapter
from app.models.character import Character
from app.schemas.novel_memory import RetrievalHit
from app.services import retrieval
from tests.conftest import _FakeResult


def _ch_row(ch_id, distance):
    """Build a (Chapter, distance) row as pgvector would return."""
    return (Chapter(id=ch_id, chapter_index=1, title=f"Ch{ch_id}"), distance)


def _c_row(c_id, distance):
    return (Character(id=c_id, name=f"Char{c_id}"), distance)


# Any positive int works — _search_one is mocked at the session level, so the
# value only has to satisfy retrieve()'s "novel_id must be set" guard.
NOVEL_ID = 42


@pytest.mark.asyncio
async def test_retrieve_merges_and_sorts_by_score_desc(mock_session):
    """4 collections, each returning one row. Verify merged + sorted."""
    # Distances: chapter=0.1 (score=0.9), character=0.5 (score=0.5),
    # world=0.3 (score=0.7), plot=0.2 (score=0.8).
    mock_session.set_execute_results([
        _FakeResult(rows=[_ch_row(1, 0.1)]),       # chapters
        _FakeResult(rows=[_c_row(2, 0.5)]),         # characters
        _FakeResult(rows=[                                          # world_settings
            (type("WS", (), {"id": 3, "category": "g", "title": "T",
                              "content_text": "x"})(), 0.3),
        ]),
        _FakeResult(rows=[                                          # plot_events
            (type("PE", (), {"id": 4, "chapter_index": 1,
                              "event_type": "beat",
                              "summary": "s",
                              "involved_character_ids": []})(), 0.2),
        ]),
    ])

    with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.0] * 1536)):
        hits = await retrieval.retrieve(mock_session, "query", novel_id=NOVEL_ID)

    assert len(hits) == 4
    assert all(isinstance(h, RetrievalHit) for h in hits)
    # Sorted descending by score.
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    # Top hit should be chapter (smallest distance → highest score).
    assert hits[0].entity_type == "chapter"
    assert hits[0].entity_id == 1
    assert pytest.approx(hits[0].score, abs=1e-6) == 0.9


@pytest.mark.asyncio
async def test_retrieve_drops_hits_beyond_max_distance(mock_session):
    """A hit with distance > max_distance must be excluded."""
    # Distance = 1.5 > DEFAULT_MAX_DISTANCE (1.0) → dropped.
    mock_session.set_execute_results([
        _FakeResult(rows=[_ch_row(1, 1.5)]),       # chapters
        _FakeResult(rows=[]),                        # characters
        _FakeResult(rows=[]),                        # world_settings
        _FakeResult(rows=[]),                        # plot_events
    ])
    with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.0] * 1536)):
        hits = await retrieval.retrieve(mock_session, "q", novel_id=NOVEL_ID)
    assert hits == []


@pytest.mark.asyncio
async def test_retrieve_score_clamped_to_zero_at_distance_one(mock_session):
    """Cosine distance = 1.0 → score = 0.0 (clamped)."""
    # Only chapters collection has a hit; others return empty.
    mock_session.set_execute_results([
        _FakeResult(rows=[_ch_row(1, 1.0)]),
        _FakeResult(rows=[]),
        _FakeResult(rows=[]),
        _FakeResult(rows=[]),
    ])
    with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.0] * 1536)):
        hits = await retrieval.retrieve(
            mock_session, "q", novel_id=NOVEL_ID, k_per_collection=1
        )
    assert len(hits) == 1
    assert hits[0].score == 0.0


@pytest.mark.asyncio
async def test_retrieve_chapters_single_collection(mock_session):
    mock_session.set_execute_results([
        _FakeResult(rows=[_ch_row(1, 0.1), _ch_row(2, 0.4)]),
    ])
    with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.0] * 1536)):
        hits = await retrieval.retrieve_chapters(mock_session, "q", novel_id=NOVEL_ID)
    assert len(hits) == 2
    assert all(h.entity_type == "chapter" for h in hits)
    assert hits[0].score > hits[1].score


@pytest.mark.asyncio
async def test_retrieve_characters_single_collection(mock_session):
    mock_session.set_execute_results([
        _FakeResult(rows=[_c_row(5, 0.2)]),
    ])
    with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.0] * 1536)):
        hits = await retrieval.retrieve_characters(mock_session, "q", novel_id=NOVEL_ID)
    assert len(hits) == 1
    assert hits[0].entity_type == "character"
    assert hits[0].entity_id == 5


@pytest.mark.asyncio
async def test_retrieve_world_settings_single_collection(mock_session):
    mock_session.set_execute_results([
        _FakeResult(rows=[
            (type("WS", (), {"id": 9, "category": "g", "title": "T",
                              "content_text": "x"})(), 0.3),
        ]),
    ])
    with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.0] * 1536)):
        hits = await retrieval.retrieve_world_settings(mock_session, "q", novel_id=NOVEL_ID)
    assert len(hits) == 1
    assert hits[0].entity_type == "world_setting"


@pytest.mark.asyncio
async def test_retrieve_plot_events_single_collection(mock_session):
    mock_session.set_execute_results([
        _FakeResult(rows=[
            (type("PE", (), {"id": 8, "chapter_index": 1,
                              "event_type": "twist",
                              "summary": "x",
                              "involved_character_ids": [1]})(), 0.4),
        ]),
    ])
    with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.0] * 1536)):
        hits = await retrieval.retrieve_plot_events(mock_session, "q", novel_id=NOVEL_ID)
    assert len(hits) == 1
    assert hits[0].entity_type == "plot_event"


@pytest.mark.asyncio
async def test_retrieve_propagates_embed_text_errors():
    """If embed_text raises (e.g. empty query), retrieve must propagate."""
    session = type("S", (), {"execute": AsyncMock()})()
    async def _raise(*a, **k):
        raise ValueError("empty")
    with patch.object(retrieval, "embed_text", _raise):
        with pytest.raises(ValueError, match="empty"):
            await retrieval.retrieve(session, "", novel_id=NOVEL_ID)


@pytest.mark.asyncio
async def test_retrieve_rejects_missing_novel_id():
    """Calling retrieve without novel_id must raise a clear ValueError."""
    session = type("S", (), {"execute": AsyncMock()})()
    # No patching embed_text — the guard fires before we reach it.
    with pytest.raises(ValueError, match="novel_id"):
        await retrieval.retrieve(session, "query")
    # Also verify an explicit None is rejected the same way.
    with pytest.raises(ValueError, match="novel_id"):
        await retrieval.retrieve(session, "query", novel_id=None)
