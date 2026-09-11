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
    assert r.json() == {"created": 0, "updated": 0, "skipped": 0}


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
