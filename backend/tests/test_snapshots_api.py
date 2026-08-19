"""API contract tests for chapter snapshot endpoints (R5-4 ????).

Service layer is mocked with AsyncMock - no database required. Verifies
HTTP status codes, auth, tenant/document scoping, and response shape.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.chapter import ChapterNotFound
from app.services.document import DocumentNotFound
from app.services.snapshot import SnapshotNotFound

_AUTH = {"X-API-Key": "test-key"}


def _fake_doc(doc_id: int = 1) -> SimpleNamespace:
    ts = datetime(2026, 8, 18, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=doc_id,
        title="Novel",
        content_html="<p></p>",
        content_text="",
        version=1,
        doc_type="novel",
        category="",
        metadata_json={},
        status="active",
        cover_url="",
        word_count=0,
        created_at=ts,
        updated_at=ts,
    )


def _fake_chapter(
    chapter_id: int = 10, novel_id: int = 1, content_text: str = "body"
) -> SimpleNamespace:
    ts = datetime(2026, 8, 18, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=chapter_id,
        novel_id=novel_id,
        chapter_index=0,
        title="Ch 1",
        content_text=content_text,
        summary="",
        word_count=4,
        status="draft",
        metadata_json={},
        created_at=ts,
        updated_at=ts,
    )


def _fake_snap(
    snap_id: int = 5, chapter_id: int = 10, content: str = "snapshot text"
) -> SimpleNamespace:
    ts = datetime(2026, 8, 18, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=snap_id,
        chapter_id=chapter_id,
        title="Ch 1",
        content_text=content,
        word_count=len(content),
        reason="insert",
        created_at=ts,
    )


def _patch_scope():
    """Return a context manager patching doc+chapter existence checks."""
    return patch.multiple(
        "app.api.snapshots",
        get_document=AsyncMock(return_value=_fake_doc()),
        get_chapter=AsyncMock(return_value=_fake_chapter()),
    )


def test_create_snapshot_returns_201(app_client: TestClient) -> None:
    with _patch_scope(), patch(
        "app.api.snapshots.create_snapshot",
        new=AsyncMock(return_value=_fake_snap()),
    ):
        r = app_client.post(
            "/v1/documents/1/chapters/10/snapshots",
            json={"content_text": "snapshot text", "reason": "insert"},
            headers=_AUTH,
        )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == 5
    assert body["chapter_id"] == 10
    assert body["content_text"] == "snapshot text"
    assert body["reason"] == "insert"


def test_create_snapshot_requires_content(app_client: TestClient) -> None:
    with _patch_scope():
        r = app_client.post(
            "/v1/documents/1/chapters/10/snapshots",
            json={"reason": "insert"},
            headers=_AUTH,
        )
    assert r.status_code == 422


def test_create_snapshot_404_when_document_missing(app_client: TestClient) -> None:
    with patch(
        "app.api.snapshots.get_document",
        new=AsyncMock(side_effect=DocumentNotFound(1)),
    ):
        r = app_client.post(
            "/v1/documents/1/chapters/10/snapshots",
            json={"content_text": "x"},
            headers=_AUTH,
        )
    assert r.status_code == 404
    assert r.json()["detail"] == "Document not found"


def test_create_snapshot_404_when_chapter_missing(app_client: TestClient) -> None:
    with patch(
        "app.api.snapshots.get_document",
        new=AsyncMock(return_value=_fake_doc()),
    ), patch(
        "app.api.snapshots.get_chapter",
        new=AsyncMock(side_effect=ChapterNotFound(10)),
    ):
        r = app_client.post(
            "/v1/documents/1/chapters/10/snapshots",
            json={"content_text": "x"},
            headers=_AUTH,
        )
    assert r.status_code == 404
    assert r.json()["detail"] == "Chapter not found"


def test_create_snapshot_404_when_chapter_wrong_novel(app_client: TestClient) -> None:
    with patch(
        "app.api.snapshots.get_document",
        new=AsyncMock(return_value=_fake_doc()),
    ), patch(
        "app.api.snapshots.get_chapter",
        new=AsyncMock(return_value=_fake_chapter(novel_id=999)),
    ):
        r = app_client.post(
            "/v1/documents/1/chapters/10/snapshots",
            json={"content_text": "x"},
            headers=_AUTH,
        )
    assert r.status_code == 404
    assert r.json()["detail"] == "Chapter not found"


def test_list_snapshots_returns_items_and_total(app_client: TestClient) -> None:
    with _patch_scope(), patch(
        "app.api.snapshots.list_snapshots",
        new=AsyncMock(return_value=([_fake_snap()], 1)),
    ):
        r = app_client.get(
            "/v1/documents/1/chapters/10/snapshots", headers=_AUTH
        )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == 5


def test_restore_snapshot_returns_chapter(app_client: TestClient) -> None:
    with _patch_scope(), patch(
        "app.api.snapshots.restore_snapshot",
        new=AsyncMock(return_value=_fake_chapter(content_text="restored")),
    ):
        r = app_client.post(
            "/v1/documents/1/chapters/10/snapshots/5/restore",
            headers=_AUTH,
        )
    assert r.status_code == 200
    assert r.json()["id"] == 10


def test_restore_snapshot_404_when_missing(app_client: TestClient) -> None:
    with _patch_scope(), patch(
        "app.api.snapshots.restore_snapshot",
        new=AsyncMock(side_effect=SnapshotNotFound(5)),
    ):
        r = app_client.post(
            "/v1/documents/1/chapters/10/snapshots/5/restore",
            headers=_AUTH,
        )
    assert r.status_code == 404
    assert r.json()["detail"] == "Snapshot not found"


def test_delete_snapshot_returns_204(app_client: TestClient) -> None:
    with _patch_scope(), patch(
        "app.api.snapshots.delete_snapshot",
        new=AsyncMock(return_value=None),
    ):
        r = app_client.delete(
            "/v1/documents/1/chapters/10/snapshots/5", headers=_AUTH
        )
    assert r.status_code == 204


def test_snapshots_require_auth(app_client: TestClient) -> None:
    # Missing header entirely -> 422 (FastAPI required-header validation),
    # matching the documents API convention (see test_documents_api).
    r = app_client.post(
        "/v1/documents/1/chapters/10/snapshots",
        json={"content_text": "x"},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(err["loc"] == ["header", "X-API-Key"] for err in detail)
    r2 = app_client.get("/v1/documents/1/chapters/10/snapshots")
    assert r2.status_code == 422

    # Present but blank/whitespace key -> 401, not 422.
    r3 = app_client.post(
        "/v1/documents/1/chapters/10/snapshots",
        json={"content_text": "x"},
        headers={"X-API-Key": "   "},
    )
    assert r3.status_code == 401
    r4 = app_client.get(
        "/v1/documents/1/chapters/10/snapshots",
        headers={"X-API-Key": ""},
    )
    assert r4.status_code == 401
