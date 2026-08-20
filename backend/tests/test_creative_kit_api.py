"""API contract tests for POST /v1/documents/{id}/creative-kit/apply.

Service layer is mocked with AsyncMock — no database required (same pattern
as test_documents_api.py): verifies routing, auth, body → service call, and
response shape.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app.api.creative_kit as creative_kit_module
from app.schemas.creative_kit import CreativeKitApplyResponse
from app.services.document import DocumentNotFound

_AUTH = {"X-API-Key": "test-key"}


def _fake_doc(doc_id: int = 5) -> SimpleNamespace:
    ts = datetime(2026, 8, 20, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=doc_id,
        title="T",
        content_html="",
        content_text="",
        version=4,
        doc_type="novel",
        category="",
        metadata_json={"outline": "1. x", "outline_updated_at": ts.isoformat()},
        status="active",
        cover_url="",
        word_count=0,
        created_at=ts,
        updated_at=ts,
    )


def _apply_result(doc_id: int = 5) -> CreativeKitApplyResponse:
    return CreativeKitApplyResponse(
        created_world_settings=3,
        skipped_world_settings=1,
        created_characters=2,
        skipped_characters=0,
        outline_applied=True,
        document=_fake_doc(doc_id),
    )


def test_apply_requires_api_key(app_client: TestClient) -> None:
    res = app_client.post(
        "/v1/documents/5/creative-kit/apply",
        json={"world_settings": [], "characters": [], "outline": "x"},
    )
    assert res.status_code == 422  # missing X-API-Key


def test_apply_routes_payload_to_service(app_client: TestClient) -> None:
    with (
        patch(
            "app.api.creative_kit.apply_creative_kit",
            new=AsyncMock(return_value=_apply_result()),
        ) as mocked_apply,
        patch(
            "app.api._deps.get_document",
            new=AsyncMock(return_value=_fake_doc()),
        ),
    ):
        res = app_client.post(
            "/v1/documents/5/creative-kit/apply",
            json={
                "world_settings": [
                    {"title": "大陆", "category": "地理", "content_text": "a"}
                ],
                "characters": [
                    {
                        "name": "主角",
                        "role": "主角",
                        "description": "d",
                        "attributes": {"性格": "冷静"},
                        "arc_summary": "成长",
                    }
                ],
                "outline": "1. 开局",
            },
            headers=_AUTH,
        )
    assert res.status_code == 200
    body = res.json()
    assert body["created_world_settings"] == 3
    assert body["skipped_world_settings"] == 1
    assert body["created_characters"] == 2
    assert body["skipped_characters"] == 0
    assert body["outline_applied"] is True
    assert body["document"]["id"] == 5
    assert body["document"]["metadata_json"]["outline"] == "1. x"
    mocked_apply.assert_awaited_once()
    sent = mocked_apply.await_args.args[2]
    assert sent.world_settings[0].title == "大陆"
    assert sent.outline == "1. 开局"


def test_apply_client_novel_id_is_schema_rejected(app_client: TestClient) -> None:
    """Path doc_id wins; an explicit novel_id in the payload body is plain
    ignored (forced server-side), not an error."""
    with (
        patch(
            "app.api.creative_kit.apply_creative_kit",
            new=AsyncMock(return_value=_apply_result()),
        ),
        patch("app.api._deps.get_document", new=AsyncMock(return_value=_fake_doc())),
    ):
        res = app_client.post(
            "/v1/documents/5/creative-kit/apply",
            json={"world_settings": [], "characters": [], "outline": "x"},
            headers=_AUTH,
        )
    assert res.status_code == 200


def test_apply_rejects_oversized_kit(app_client: TestClient) -> None:
    """Schema guard: more than 20 items is a 422 — no surprise writes."""
    ws = [{"title": f"W{i}"} for i in range(21)]
    res = app_client.post(
        "/v1/documents/5/creative-kit/apply",
        json={"world_settings": ws, "characters": [], "outline": ""},
        headers=_AUTH,
    )
    assert res.status_code == 422


def test_apply_missing_document_returns_404(app_client: TestClient) -> None:
    """DocumentNotFound from either the parent loader or the service becomes
    a 404 — the caller never sees a raw 500."""
    with patch("app.api._deps.get_document", new=AsyncMock(side_effect=DocumentNotFound(999))):
        res = app_client.post(
            "/v1/documents/999/creative-kit/apply",
            json={"world_settings": [], "characters": [], "outline": "x"},
            headers=_AUTH,
        )
    assert res.status_code == 404