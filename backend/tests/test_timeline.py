"""Tests for the timeline-graph feature (R6-2 时间线图谱).

Covers:
  - plot_events schema fields (in_world_date / prev_event_id)
  - build_timeline_dag: node ordering, edge construction, topological order
  - predecessor validation (dangling prev pointer)
  - reverse-order warning (cause placed after effect in chapter / in-world date)
  - cycle detection warning
  - validate_chapter_write: real-time scoping on chapter write
  - chapter service hook: timeline warnings attached to metadata_json
  - HTTP timeline view endpoint

Pure DAG functions are tested without a DB; async service/API tests use
MockAsyncSession + mocked service layer following test_consistency.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.chapter import Chapter
from app.models.plot_event import PlotEvent
from app.schemas.novel_memory import PlotEventCreate
from app.services import timeline as tl
from tests.conftest import _FakeResult

_AUTH = {"X-API-Key": "test-key"}


def _ev(
    eid: int,
    summary: str,
    *,
    chapter_index: int | None = None,
    chapter_id: int | None = None,
    prev: int | None = None,
    in_world_date: str | None = None,
    event_type: str = "beat",
    novel_id: int = 5,
) -> PlotEvent:
    return PlotEvent(
        id=eid, novel_id=novel_id, chapter_id=chapter_id,
        chapter_index=chapter_index, event_type=event_type,
        summary=summary, prev_event_id=prev, in_world_date=in_world_date,
    )


# ===========================================================================
# Schemas
# ===========================================================================


def test_plot_event_create_accepts_timeline_fields():
    payload = PlotEventCreate(
        summary="主角发现宝剑",
        in_world_date="1000-03-15",
        prev_event_id=7,
    )
    assert payload.in_world_date == "1000-03-15"
    assert payload.prev_event_id == 7


# ===========================================================================
# build_timeline_dag — node/edge construction
# ===========================================================================


def test_build_dag_orders_nodes_by_in_world_date_then_chapter():
    e1 = _ev(1, "A", in_world_date="1000-01-01", chapter_index=2)
    e2 = _ev(2, "B", in_world_date="0999-12-31", chapter_index=1)
    e3 = _ev(3, "C", chapter_index=0)  # undated roots sort first
    dag = tl.build_timeline_dag([e1, e2, e3])
    assert [n.event_id for n in dag.nodes] == [3, 2, 1]


def test_build_dag_creates_edges_from_prev_pointers():
    e1 = _ev(1, "cause", chapter_index=1)
    e2 = _ev(2, "effect", chapter_index=2, prev=1)
    dag = tl.build_timeline_dag([e1, e2])
    assert dag.edges == [tl.TimelineEdge(from_id=1, to_id=2)]


def test_build_dag_topological_order_respects_causality():
    e1 = _ev(1, "A", chapter_index=1)
    e2 = _ev(2, "B", chapter_index=2, prev=1)
    e3 = _ev(3, "C", chapter_index=3, prev=2)
    e4 = _ev(4, "D", chapter_index=1)  # independent root
    dag = tl.build_timeline_dag([e3, e2, e4, e1])
    assert dag.edges == [
        tl.TimelineEdge(from_id=1, to_id=2),
        tl.TimelineEdge(from_id=2, to_id=3),
    ]
    order = dag.topological_ids
    assert order.index(1) < order.index(2) < order.index(3)
    assert set(order) == {1, 2, 3, 4}


# ===========================================================================
# Predecessor validation
# ===========================================================================


def test_build_dag_warns_on_dangling_predecessor():
    e1 = _ev(1, "orphan", chapter_index=1, prev=999)  # prev does not exist
    dag = tl.build_timeline_dag([e1])
    kinds = {w.kind for w in dag.warnings}
    assert "predecessor" in kinds
    assert dag.edges == []  # dangling prev must not create an edge


def test_build_dag_warns_reverse_order_by_chapter():
    cause = _ev(1, "cause", chapter_index=3)
    effect = _ev(2, "effect", chapter_index=1, prev=1)
    dag = tl.build_timeline_dag([cause, effect])
    rev = [w for w in dag.warnings if w.kind == "reverse_order"]
    assert len(rev) == 1
    assert rev[0].event_id == 2


def test_build_dag_warns_reverse_order_by_in_world_date():
    cause = _ev(1, "cause", in_world_date="1000-06-01")
    effect = _ev(2, "effect", in_world_date="1000-01-01", prev=1)
    dag = tl.build_timeline_dag([cause, effect])
    rev = [w for w in dag.warnings if w.kind == "reverse_order"]
    assert len(rev) == 1 and rev[0].event_id == 2


def test_build_dag_same_chapter_chain_not_reverse_order():
    """Two causally-linked events inside ONE chapter are a valid chain."""
    e1 = _ev(1, "a", chapter_index=2)
    e2 = _ev(2, "b", chapter_index=2, prev=1)
    dag = tl.build_timeline_dag([e1, e2])
    assert [w.kind for w in dag.warnings] == []


# ===========================================================================
# Cycle detection
# ===========================================================================


def test_build_dag_warns_on_cycle():
    e1 = _ev(1, "a", chapter_index=1, prev=2)
    e2 = _ev(2, "b", chapter_index=2, prev=1)
    dag = tl.build_timeline_dag([e1, e2])
    cycles = [w for w in dag.warnings if w.kind == "cycle"]
    assert len(cycles) == 1
    assert "1" in cycles[0].detail and "2" in cycles[0].detail


def test_build_dag_cycle_with_spoke():
    e1 = _ev(1, "a", prev=3)
    e2 = _ev(2, "b", chapter_index=1, prev=3)
    e3 = _ev(3, "c", prev=1)  # 1 <-> 3 cycle; e2 feeds in but is not cyclic
    dag = tl.build_timeline_dag([e1, e2, e3])
    assert [w.kind for w in dag.warnings] == ["cycle"]


# ===========================================================================
# validate_chapter_write — real-time write-time scoping
# ===========================================================================


@pytest.mark.asyncio
async def test_validate_chapter_write_returns_chapter_relevant_warnings(mock_session):
    cause = _ev(1, "cause", chapter_index=3)
    effect = _ev(2, "effect", chapter_index=1, prev=1)
    other = _ev(4, "elsewhere", chapter_index=9, prev=1)
    mock_session.set_execute_results([_FakeResult(scalars=[cause, effect, other])])

    warnings = await tl.validate_chapter_write(
        mock_session, novel_id=5, chapter_index=1,
    )
    assert [w.event_id for w in warnings] == [2]


@pytest.mark.asyncio
async def test_validate_chapter_write_includes_cycles_always(mock_session):
    e1 = _ev(1, "a", chapter_index=1, prev=2)
    e2 = _ev(2, "b", chapter_index=2, prev=1)
    mock_session.set_execute_results([_FakeResult(scalars=[e1, e2])])

    warnings = await tl.validate_chapter_write(
        mock_session, novel_id=5, chapter_index=8,  # chapter not in the cycle
    )
    assert any(w.kind == "cycle" for w in warnings)


# ===========================================================================
# Chapter service hook — real-time conflict warnings on write
# ===========================================================================


@pytest.mark.asyncio
async def test_create_chapter_attaches_timeline_warnings(mock_session, monkeypatch):
    async def _noop_embed(*args, **kwargs):
        return [0.0] * 8

    monkeypatch.setattr("app.llm.embedding.embed_text", _noop_embed)
    cause = _ev(1, "cause", chapter_index=3)
    effect = _ev(2, "effect", chapter_index=1, prev=1)
    mock_session.set_execute_results([_FakeResult(scalars=[cause, effect])])

    from app.schemas.novel_memory import ChapterCreate
    from app.services.chapter import create_chapter

    ch = await create_chapter(
        mock_session,
        ChapterCreate(novel_id=5, chapter_index=1, title="第一章", content_text="正文"),
    )
    warnings = (ch.metadata_json or {}).get("timeline_warnings")
    assert warnings and warnings[0]["kind"] == "reverse_order"


@pytest.mark.asyncio
async def test_create_chapter_no_warning_keeps_metadata_untouched(mock_session, monkeypatch):
    async def _noop_embed(*args, **kwargs):
        return [0.0] * 8

    monkeypatch.setattr("app.llm.embedding.embed_text", _noop_embed)
    mock_session.set_execute_results([_FakeResult(scalars=[])])

    from app.schemas.novel_memory import ChapterCreate
    from app.services.chapter import create_chapter

    ch = await create_chapter(
        mock_session,
        ChapterCreate(
            novel_id=5, chapter_index=1, title="第一章",
            content_text="正文", metadata_json={"theme": "成长"},
        ),
    )
    assert ch.metadata_json == {"theme": "成长"}


@pytest.mark.asyncio
async def test_update_chapter_attaches_timeline_warnings(mock_session, monkeypatch):
    async def _noop_embed(*args, **kwargs):
        return [0.0] * 8

    monkeypatch.setattr("app.llm.embedding.embed_text", _noop_embed)
    ch = Chapter(id=9, novel_id=5, chapter_index=1, title="x", content_text="abc")
    mock_session.set_scalar_results([ch])
    e1 = _ev(1, "cause", chapter_index=3)
    e2 = _ev(2, "effect", chapter_index=1, prev=1)
    mock_session.set_execute_results([_FakeResult(scalars=[e1, e2])])

    from app.schemas.novel_memory import ChapterUpdate
    from app.services.chapter import update_chapter

    updated = await update_chapter(mock_session, 9, ChapterUpdate(title="new"))
    warnings = (updated.metadata_json or {}).get("timeline_warnings")
    assert warnings and warnings[0]["kind"] == "reverse_order"


# ===========================================================================
# Timeline view API
# ===========================================================================


def _dag() -> tl.TimelineDag:
    return tl.TimelineDag(
        nodes=[
            tl.TimelineNode(
                event_id=1, event_type="beat", summary="cause",
                chapter_id=None, chapter_index=1,
                in_world_date=None, prev_event_id=None,
            ),
            tl.TimelineNode(
                event_id=2, event_type="twist", summary="effect",
                chapter_id=None, chapter_index=2,
                in_world_date=None, prev_event_id=1,
            ),
        ],
        edges=[tl.TimelineEdge(from_id=1, to_id=2)],
        warnings=[
            tl.TimelineWarning(
                kind="reverse_order", event_id=2,
                detail="事件 2 的前置事件 1 排在更后",
            )
        ],
        topological_ids=[1, 2],
    )


def test_timeline_endpoint_returns_graph(app_client: TestClient) -> None:
    with patch("app.api.timeline.load_parent", new=AsyncMock()), \
            patch("app.api.timeline.get_timeline",
                  new=AsyncMock(return_value=_dag())):
        r = app_client.get("/v1/documents/5/timeline", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert [n["event_id"] for n in body["nodes"]] == [1, 2]
    assert body["edges"] == [{"from_id": 1, "to_id": 2}]
    assert body["warnings"][0]["kind"] == "reverse_order"
    assert body["topological_order"] == [1, 2]


def test_timeline_endpoint_requires_auth(app_client: TestClient) -> None:
    r = app_client.get("/v1/documents/5/timeline")
    assert r.status_code == 422


def test_timeline_endpoint_404_when_novel_missing(app_client: TestClient) -> None:
    from fastapi import HTTPException

    async def _raise(*a, **k):
        raise HTTPException(status_code=404, detail="作品不存在")

    with patch("app.api.timeline.load_parent", new=_raise):
        r = app_client.get("/v1/documents/999/timeline", headers=_AUTH)
    assert r.status_code == 404


# ===========================================================================
# Review fixes (R6-2 评审 P1/P2)
# ===========================================================================


def test_build_dag_orders_non_iso_dates_by_normalized_value():
    """1000/3/5, 1000-03-05, 1000年3月6日 must all parse to (y,m,d)."""
    e1 = _ev(1, "A", in_world_date="1000/3/5")
    e2 = _ev(2, "B", in_world_date="1000-03-05")
    e3 = _ev(3, "C", in_world_date="1000年3月6日")
    dag = tl.build_timeline_dag([e3, e1, e2])
    assert [n.event_id for n in dag.nodes] == [1, 2, 3]


def test_build_dag_unparseable_dates_sort_after_real_dates():
    e1 = _ev(1, "A", in_world_date="1000-01-01")
    e2 = _ev(2, "B", in_world_date="第二年春天")
    dag = tl.build_timeline_dag([e2, e1])
    assert [n.event_id for n in dag.nodes] == [1, 2]


def test_build_dag_reverse_order_with_non_iso_dates():
    cause = _ev(1, "cause", in_world_date="1000/6/1")
    effect = _ev(2, "effect", in_world_date="1000-01-01", prev=1)
    dag = tl.build_timeline_dag([cause, effect])
    rev = [w for w in dag.warnings if w.kind == "reverse_order"]
    assert len(rev) == 1 and rev[0].event_id == 2


def test_timeline_endpoint_limit_slices_nodes_and_derived(app_client: TestClient) -> None:
    with patch("app.api.timeline.load_parent", new=AsyncMock()), \
            patch("app.api.timeline.get_timeline",
                  new=AsyncMock(return_value=_dag())):
        r = app_client.get(
            "/v1/documents/5/timeline", params={"limit": 1}, headers=_AUTH,
        )
    assert r.status_code == 200
    body = r.json()
    assert [n["event_id"] for n in body["nodes"]] == [1]
    assert body["edges"] == []
    assert body["warnings"] == []
    assert body["topological_order"] == [1]


def test_timeline_endpoint_rejects_oversized_limit(app_client: TestClient) -> None:
    r = app_client.get(
        "/v1/documents/5/timeline", params={"limit": 1001}, headers=_AUTH,
    )
    assert r.status_code == 422


# --- P1: prev_event_id must belong to the same novel (service boundary) ----


@pytest.mark.asyncio
async def test_create_plot_event_rejects_missing_predecessor(mock_session):
    from app.schemas.novel_memory import PlotEventCreate
    from app.services.plot_event import (
        PlotEventPredecessorNotFound,
        create_plot_event,
    )

    mock_session.set_scalar_results([None])  # prev id=999 not found
    payload = PlotEventCreate(novel_id=5, summary="effect", prev_event_id=999)
    with pytest.raises(PlotEventPredecessorNotFound, match="不属于当前作品"):
        await create_plot_event(mock_session, payload)
    assert mock_session.added == []


@pytest.mark.asyncio
async def test_create_plot_event_accepts_same_novel_predecessor(mock_session, monkeypatch):
    async def _noop_embed(*args, **kwargs):
        return [0.0] * 8

    monkeypatch.setattr("app.llm.embedding.embed_text", _noop_embed)
    from app.schemas.novel_memory import PlotEventCreate
    from app.services.plot_event import create_plot_event

    prev = _ev(1, "cause", chapter_index=1, novel_id=5)
    mock_session.set_scalar_results([prev])
    payload = PlotEventCreate(
        novel_id=5, summary="effect", prev_event_id=1, chapter_index=2,
    )
    pe = await create_plot_event(mock_session, payload)
    assert pe.prev_event_id == 1


@pytest.mark.asyncio
async def test_update_plot_event_rejects_foreign_predecessor(mock_session):
    from app.schemas.novel_memory import PlotEventUpdate
    from app.services.plot_event import (
        PlotEventPredecessorNotFound,
        update_plot_event,
    )

    existing = _ev(1, "old", novel_id=5)
    mock_session.set_scalar_results([existing, None])  # get, then prev resolve
    with pytest.raises(PlotEventPredecessorNotFound, match="不属于当前作品"):
        await update_plot_event(
            mock_session, 1, PlotEventUpdate(prev_event_id=999),
        )


def test_create_plot_event_endpoint_400_on_foreign_predecessor(
    app_client: TestClient,
) -> None:
    from app.services.plot_event import PlotEventPredecessorNotFound

    async def _raise_prev(*a, **k):
        raise PlotEventPredecessorNotFound(999)

    with patch("app.api.plot_events.load_parent", new=AsyncMock()), \
            patch("app.api.plot_events.create_plot_event", new=_raise_prev):
        r = app_client.post(
            "/v1/documents/5/plot-events",
            json={"summary": "effect", "prev_event_id": 999},
            headers=_AUTH,
        )
    assert r.status_code == 400
    assert "不属于当前作品" in r.json()["detail"]


# --- P2: stored timeline_warnings refresh / residual cleanup ---------------


@pytest.mark.asyncio
async def test_refresh_chapter_warnings_clears_stale_key(mock_session):
    from app.services.plot_event import _refresh_chapter_warnings

    ch = Chapter(
        id=9, novel_id=5, chapter_index=1, title="t",
        metadata_json={"timeline_warnings": [{"kind": "cycle", "event_id": 1, "detail": "stale"}]},
    )
    mock_session.set_execute_results([
        _FakeResult(scalars=[ch]),  # select Chapter
        _FakeResult(scalars=[]),    # select PlotEvent -> no events -> no warnings
    ])
    await _refresh_chapter_warnings(mock_session, novel_id=5, chapter_indexes={1})
    assert "timeline_warnings" not in (ch.metadata_json or {})
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_refresh_chapter_warnings_writes_fresh(mock_session):
    from app.services.plot_event import _refresh_chapter_warnings

    ch = Chapter(id=9, novel_id=5, chapter_index=1, title="t")
    cause = _ev(1, "cause", chapter_index=3, novel_id=5)
    effect = _ev(2, "effect", chapter_index=1, prev=1, novel_id=5)
    mock_session.set_execute_results([
        _FakeResult(scalars=[ch]),
        _FakeResult(scalars=[cause, effect]),
    ])
    await _refresh_chapter_warnings(mock_session, novel_id=5, chapter_indexes={1})
    warnings = (ch.metadata_json or {}).get("timeline_warnings")
    assert warnings and warnings[0]["kind"] == "reverse_order"
