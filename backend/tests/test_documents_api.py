"""API contract tests for /v1/documents.

Service layer is mocked with AsyncMock — no database required. Verifies
HTTP status codes, headers, response shape, and routing logic only; the
real DB round-trip is covered by E2E manual testing (see plan).

Every endpoint requires the `X-API-Key` header (see
`app.api.documents._require_api_key`), so each request passes `headers=_AUTH`.
The header is deliberately NOT baked into the shared `app_client` fixture:
that fixture is session-scoped and shared with other test modules, and a
default header there would mask auth regressions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.document import DocumentNotFound

# Any non-empty key is accepted by _require_api_key and used as the owner scope.
_AUTH = {"X-API-Key": "test-key"}


def _fake_doc(
    doc_id: int = 1,
    *,
    title: str = "Hello",
    content_html: str = "<p>hi</p>",
    content_text: str = "hi",
    version: int = 1,
) -> SimpleNamespace:
    """Build a Document ORM-like object that Pydantic can serialize via from_attributes.

    Must include every field required by DocumentRead, DocumentListItem, and
    DocumentListResponse (see schemas/document.py).
    """
    ts = datetime(2026, 7, 19, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=doc_id,
        title=title,
        content_html=content_html,
        content_text=content_text,
        version=version,
        doc_type="novel",
        category="",
        metadata_json={},
        status="active",
        cover_url="",
        word_count=0,
        created_at=ts,
        updated_at=ts,
    )


def test_list_returns_empty(app_client: TestClient) -> None:
    with patch("app.api.documents.list_documents", new=AsyncMock(return_value=([], 0))):
        r = app_client.get("/v1/documents", headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


def test_list_returns_items_without_content(app_client: TestClient) -> None:
    fake = _fake_doc(7, title="Seven")
    with patch("app.api.documents.list_documents", new=AsyncMock(return_value=([fake], 1))):
        r = app_client.get("/v1/documents", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == 7
    assert item["title"] == "Seven"
    # List items must NOT include content fields.
    assert "content_html" not in item
    assert "content_text" not in item


def test_create_returns_201_with_location(app_client: TestClient) -> None:
    fake = _fake_doc(7, title="New")
    with patch("app.api.documents.create_document", new=AsyncMock(return_value=fake)):
        r = app_client.post(
            "/v1/documents",
            json={"title": "New", "content_html": "<p></p>", "content_text": ""},
            headers=_AUTH,
        )
    assert r.status_code == 201
    assert r.headers["location"] == "/v1/documents/7"
    body = r.json()
    assert body["id"] == 7
    assert body["title"] == "New"


def test_create_rejects_empty_title(app_client: TestClient) -> None:
    r = app_client.post("/v1/documents", json={"title": ""}, headers=_AUTH)
    assert r.status_code == 422


def test_get_returns_404_for_missing(app_client: TestClient) -> None:
    with patch(
        "app.api.documents.get_document",
        new=AsyncMock(side_effect=DocumentNotFound(99)),
    ):
        r = app_client.get("/v1/documents/99", headers=_AUTH)
    assert r.status_code == 404
    assert r.json()["detail"] == "作品不存在"


def test_get_returns_full_document(app_client: TestClient) -> None:
    fake = _fake_doc(1, title="Hello", content_html="<p>body</p>", content_text="body")
    with patch("app.api.documents.get_document", new=AsyncMock(return_value=fake)):
        r = app_client.get("/v1/documents/1", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["content_html"] == "<p>body</p>"
    assert body["content_text"] == "body"
    assert body["version"] == 1


def test_patch_is_partial(app_client: TestClient) -> None:
    # Service should be called with a DocumentUpdate that only has title set.
    fake = _fake_doc(1, title="New title", version=2)
    with patch(
        "app.api.documents.update_document",
        new=AsyncMock(return_value=fake),
    ) as mock_update:
        r = app_client.patch("/v1/documents/1", json={"title": "New title"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["title"] == "New title"
    # Verify only `title` was passed (partial update).
    # update_document is called as update_document(session, doc_id, payload),
    # so payload is args[2] (positional) or kwargs["payload"].
    args, kwargs = mock_update.call_args
    payload = args[2] if len(args) > 2 else kwargs.get("payload")
    assert payload.title == "New title"
    assert payload.content_html is None
    assert payload.content_text is None


def test_delete_returns_204(app_client: TestClient) -> None:
    with patch("app.api.documents.delete_document", new=AsyncMock(return_value=None)):
        r = app_client.delete("/v1/documents/1", headers=_AUTH)
    assert r.status_code == 204
    assert r.content == b""


def test_delete_returns_404_for_missing(app_client: TestClient) -> None:
    with patch(
        "app.api.documents.delete_document",
        new=AsyncMock(side_effect=DocumentNotFound(99)),
    ):
        r = app_client.delete("/v1/documents/99", headers=_AUTH)
    assert r.status_code == 404


# --- Auth contract -----------------------------------------------------------
# These lock in the behavior of `app.api.documents._require_api_key`: the
# header is declared `Header(...)` (required), so FastAPI rejects a missing
# header during request validation, while a present-but-blank value reaches
# the dependency body and is rejected as unauthorized.


def test_missing_api_key_returns_422(app_client: TestClient) -> None:
    """No X-API-Key at all → FastAPI's missing-required-header validation error."""
    # Patch the service so a routing/DB failure can't be mistaken for auth working.
    with patch("app.api.documents.list_documents", new=AsyncMock(return_value=([], 0))):
        r = app_client.get("/v1/documents")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(err["loc"] == ["header", "X-API-Key"] for err in detail)


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_api_key_returns_401(app_client: TestClient, blank: str) -> None:
    """Present but empty/whitespace X-API-Key → 401, not 422."""
    with patch("app.api.documents.list_documents", new=AsyncMock(return_value=([], 0))):
        r = app_client.get("/v1/documents", headers={"X-API-Key": blank})
    assert r.status_code == 401
    assert r.json()["detail"] == "缺少或空的 X-API-Key 头"
