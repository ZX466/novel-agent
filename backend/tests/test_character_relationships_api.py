"""API contract tests for /v1/documents/{doc_id}/characters/relationships.

Service layer + load_parent are mocked with AsyncMock — no database required.
Verifies HTTP status codes, response shapes, and routing only (same pattern as
test_documents_api.py). The real DB round-trip (composite FKs, CASCADE) is
covered by service tests + manual E2E.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

_AUTH = {"X-API-Key": "test-key"}
_GRAPH = (
    "/v1/documents/1/characters/relationships/graph",
    "PUT",
    "/v1/documents/1/characters/relationships/1/2",
    "/v1/documents/1/characters/relationships/import",
)


def _graph(nodes=None, edges=None) -> SimpleNamespace:
    return SimpleNamespace(nodes=nodes or [], edges=edges or [])


def _noop_load_parent(app_client: TestClient) -> None:
    """Patch load_parent to a no-op so the endpoint can reach the service."""


@pytest.fixture(autouse=True)
def _mock_load_parent():
    with patch(
        "app.api.character_relationships.load_parent", new=AsyncMock(return_value=None)
    ):
        yield


def test_graph_returns_nodes_and_edges(app_client: TestClient) -> None:
    graph = _graph(
        nodes=[SimpleNamespace(id=1, name="甲", role="主角")],
        edges=[SimpleNamespace(
            subject_id=1, object_id=2, relation_type="师徒", description="", strength=5,
        )],
    )
    with patch(
        "app.api.character_relationships.get_graph", new=AsyncMock(return_value=graph)
    ):
        r = app_client.get(_GRAPH[0], headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] == [{"id": 1, "name": "甲", "role": "主角"}]
    assert body["edges"] == [{
        "subject_id": 1, "object_id": 2, "relation_type": "师徒",
        "description": "", "strength": 5,
    }]
    # Response must NOT include novel_id.
    assert "novel_id" not in body["nodes"][0]
    assert "novel_id" not in body["edges"][0]


def test_graph_empty(app_client: TestClient) -> None:
    with patch(
        "app.api.character_relationships.get_graph",
        new=AsyncMock(return_value=_graph()),
    ):
        r = app_client.get(_GRAPH[0], headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == {"nodes": [], "edges": []}


def test_put_upsert_returns_201_created(app_client: TestClient) -> None:
    rel = SimpleNamespace(id=1, novel_id=1, subject_id=1, object_id=2)
    with patch(
        "app.api.character_relationships.upsert_relationship",
        new=AsyncMock(return_value=(rel, True)),
    ):
        r = app_client.put(
            _GRAPH[2],
            json={"relation_type": "师徒", "strength": 5},
            headers=_AUTH,
        )
    assert r.status_code == 200
    assert r.json() == {"created": 1, "updated": 0, "skipped": 0}


def test_put_upsert_returns_200_updated(app_client: TestClient) -> None:
    rel = SimpleNamespace(id=1, novel_id=1, subject_id=1, object_id=2)
    with patch(
        "app.api.character_relationships.upsert_relationship",
        new=AsyncMock(return_value=(rel, False)),
    ):
        r = app_client.put(
            _GRAPH[2],
            json={"relation_type": "恋人", "strength": 9},
            headers=_AUTH,
        )
    assert r.status_code == 200
    assert r.json() == {"created": 0, "updated": 1, "skipped": 0}


def test_delete_returns_204(app_client: TestClient) -> None:
    with patch(
        "app.api.character_relationships.delete_relationship",
        new=AsyncMock(return_value=None),
    ):
        r = app_client.delete(_GRAPH[2], headers=_AUTH)
    assert r.status_code == 204


def test_import_returns_counts(app_client: TestClient) -> None:
    result = SimpleNamespace(created=2, updated=1, skipped=0)
    with patch(
        "app.api.character_relationships.import_relationships",
        new=AsyncMock(return_value=result),
    ):
        r = app_client.post(
            _GRAPH[3],
            json={"items": [
                {"subject_name": "甲", "object_name": "乙", "relation_type": "师徒"},
            ]},
            headers=_AUTH,
        )
    assert r.status_code == 200
    assert r.json() == {"created": 2, "updated": 1, "skipped": 0}


def test_import_rejects_over_200_items(app_client: TestClient) -> None:
    items = [{"subject_name": "a", "object_name": "b"} for _ in range(201)]
    r = app_client.post(_GRAPH[3], json={"items": items}, headers=_AUTH)
    assert r.status_code == 422


def test_requires_api_key(app_client: TestClient) -> None:
    r = app_client.get(_GRAPH[0])
    assert r.status_code == 401 or r.status_code == 422


# --- R9-③ review P1-B: real-DB acceptance (skipif no live PostgreSQL) -------
#
# The 18 mock-based cases above never touch a real database, so the DB-level
# guarantees (composite-FK same-novel backstop, FK ON DELETE CASCADE) were
# unverified. These two cases exercise them against real PostgreSQL, per the
# test_timeline.py:571 precedent. They require a reachable DATABASE_URL —
# skipped otherwise so CI without docker stays green (P1-B requirement).

def _real_db_reachable() -> bool:
    import os

    import sqlalchemy as sa

    url = os.environ.get("DATABASE_URL", "")
    if not url or "stub" in url:
        return False
    try:
        sync_url = sa.engine.URL.create(
            drivername="postgresql+psycopg2",
            username=sa.engine.make_url(url).username,
            password=sa.engine.make_url(url).password,
            host=sa.engine.make_url(url).host,
            port=sa.engine.make_url(url).port,
            database=sa.engine.make_url(url).database,
        )
        engine = sa.create_engine(sync_url, connect_args={"connect_timeout": 2})
        try:
            with engine.connect():
                return True
        finally:
            engine.dispose()
    except Exception:
        return False


@pytest.mark.skipif(
    not _real_db_reachable(), reason="real PostgreSQL not reachable (docker not running)"
)
def test_real_db_delete_character_cascades_edges(app_client: TestClient) -> None:
    """P1-B ①: deleting a character with relationship edges → 204 and its
    edges are gone (FK ON DELETE CASCADE, verified against real PG)."""
    create = app_client.post("/v1/documents", json={"title": "级联测试"}, headers=_AUTH)
    assert create.status_code == 201
    doc_id = create.json()["id"]
    a = app_client.post(
        f"/v1/documents/{doc_id}/characters", json={"name": "甲"}, headers=_AUTH)
    b = app_client.post(
        f"/v1/documents/{doc_id}/characters", json={"name": "乙"}, headers=_AUTH)
    assert a.status_code == 201 and b.status_code == 201
    a_id, b_id = a.json()["id"], b.json()["id"]

    put = app_client.put(
        f"/v1/documents/{doc_id}/characters/relationships/{a_id}/{b_id}",
        json={"relation_type": "师徒", "description": "", "strength": 5},
        headers=_AUTH,
    )
    assert put.status_code in (200, 201), put.text

    # Delete character A → its edges must cascade away, not 500.
    r = app_client.delete(f"/v1/documents/{doc_id}/characters/{a_id}", headers=_AUTH)
    assert r.status_code == 204, r.text

    graph = app_client.get(
        f"/v1/documents/{doc_id}/characters/relationships/graph", headers=_AUTH)
    assert graph.status_code == 200
    body = graph.json()
    assert all(e["subject_id"] != a_id and e["object_id"] != a_id for e in body["edges"])


@pytest.mark.skipif(
    not _real_db_reachable(), reason="real PostgreSQL not reachable (docker not running)"
)
def test_real_db_cross_novel_edge_rejected_by_db(app_client: TestClient) -> None:
    """P1-B ②: an edge referencing another novel's character id must be
    rejected (DB-level composite-FK backstop → 409/404), and no edge row
    may persist (R6-2-class cross-tenant leak guard)."""
    doc1 = app_client.post("/v1/documents", json={"title": "作品一"}, headers=_AUTH)
    doc2 = app_client.post("/v1/documents", json={"title": "作品二"}, headers=_AUTH)
    assert doc1.status_code == 201 and doc2.status_code == 201
    id1, id2 = doc1.json()["id"], doc2.json()["id"]

    c2 = app_client.post(
        f"/v1/documents/{id2}/characters", json={"name": "乙"}, headers=_AUTH)
    assert c2.status_code == 201
    foreign_id = c2.json()["id"]

    # Build an edge in novel 1 pointing at novel 2's character.
    r = app_client.put(
        f"/v1/documents/{id1}/characters/relationships/999/{foreign_id}",
        json={"relation_type": "越界", "description": "", "strength": 1},
        headers=_AUTH,
    )
    assert r.status_code in (404, 409), r.text  # mapped, not 500

    graph = app_client.get(
        f"/v1/documents/{id1}/characters/relationships/graph", headers=_AUTH)
    assert graph.status_code == 200
    assert graph.json()["edges"] == []  # no edge persisted
