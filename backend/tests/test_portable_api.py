"""Tests for the portable data gateway (R6-4): NDJSON export + idempotent import.

Covers full export, idempotent re-import (created -> unchanged), update-on-change,
document metadata sync, and incremental sync via the last_sync cursor.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

_AUTH = {"X-API-Key": "test-key"}
_NDJSON = "application/x-ndjson"


def _create_doc_with_chapters(app_client: TestClient, title: str, chapters: list[tuple[int, str, str]]) -> int:
    create = app_client.post("/v1/documents", json={"title": title}, headers=_AUTH)
    assert create.status_code == 201
    doc_id = create.json()["id"]
    for idx, ch_title, body in chapters:
        r = app_client.post(
            f"/v1/documents/{doc_id}/chapters",
            json={"chapter_index": idx, "title": ch_title, "content_text": body},
            headers=_AUTH,
        )
        assert r.status_code == 201
    return doc_id


def _create_empty_doc(app_client: TestClient, title: str) -> int:
    create = app_client.post("/v1/documents", json={"title": title}, headers=_AUTH)
    assert create.status_code == 201
    return create.json()["id"]


def _parse_ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_export_ndjson_full(app_client: TestClient) -> None:
    doc_id = _create_doc_with_chapters(
        app_client, "可移植作品", [(0, "第一章", "正文一"), (1, "第二章", "正文二")],
    )
    r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "ndjson"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(_NDJSON)
    assert ".ndjson" in r.headers["content-disposition"].lower()

    records = _parse_ndjson(r.text)
    assert records[0]["_type"] == "document"
    assert records[0]["id"] == doc_id
    assert records[0]["title"] == "可移植作品"
    assert records[1]["_type"] == "chapter"
    assert records[1]["content_text"] == "正文一"
    assert records[2]["_type"] == "chapter"
    assert records[2]["content_text"] == "正文二"
    assert all(rec["schema_version"] == 1 for rec in records)


def test_export_ndjson_requires_api_key(app_client: TestClient) -> None:
    r = app_client.get("/v1/documents/1/export", params={"format": "ndjson"})
    assert r.status_code == 422


def test_import_creates_chapters(app_client: TestClient) -> None:
    src = _create_doc_with_chapters(
        app_client, "源作品", [(0, "第一章", "正文一"), (1, "第二章", "正文二")],
    )
    ndjson = app_client.get(
        f"/v1/documents/{src}/export", params={"format": "ndjson"}, headers=_AUTH,
    ).text

    dst = _create_empty_doc(app_client, "目标作品")
    r = app_client.post(
        "/v1/documents/import",
        params={"doc_id": dst},
        content=ndjson,
        headers={**_AUTH, "Content-Type": _NDJSON},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 2
    assert body["updated"] == 0
    assert body["unchanged"] == 0

    listing = app_client.get(f"/v1/documents/{dst}/chapters", headers=_AUTH).json()
    assert listing["total"] == 2
    titles = {c["title"] for c in listing["items"]}
    assert titles == {"第一章", "第二章"}


def test_import_is_idempotent(app_client: TestClient) -> None:
    src = _create_doc_with_chapters(app_client, "源作品", [(0, "第一章", "正文一")])
    ndjson = app_client.get(
        f"/v1/documents/{src}/export", params={"format": "ndjson"}, headers=_AUTH,
    ).text
    dst = _create_empty_doc(app_client, "目标作品")
    app_client.post(
        "/v1/documents/import", params={"doc_id": dst}, content=ndjson,
        headers={**_AUTH, "Content-Type": _NDJSON},
    )
    # Re-import the exact same payload -> everything unchanged, nothing created.
    again = app_client.post(
        "/v1/documents/import", params={"doc_id": dst}, content=ndjson,
        headers={**_AUTH, "Content-Type": _NDJSON},
    ).json()
    assert again["created"] == 0
    assert again["updated"] == 0
    assert again["unchanged"] == 1


def test_import_updates_on_change(app_client: TestClient) -> None:
    src = _create_doc_with_chapters(app_client, "源作品", [(0, "第一章", "正文一")])
    ndjson = app_client.get(
        f"/v1/documents/{src}/export", params={"format": "ndjson"}, headers=_AUTH,
    ).text
    dst = _create_empty_doc(app_client, "目标作品")
    app_client.post(
        "/v1/documents/import", params={"doc_id": dst}, content=ndjson,
        headers={**_AUTH, "Content-Type": _NDJSON},
    )

    # Change a chapter title and re-export from source, then re-import.
    src_chapters = app_client.get(f"/v1/documents/{src}/chapters", headers=_AUTH).json()["items"]
    src_ch_id = src_chapters[0]["id"]
    patch_resp = app_client.patch(
        f"/v1/documents/{src}/chapters/{src_ch_id}",
        json={"title": "第一章(修订)"}, headers=_AUTH,
    )
    assert patch_resp.status_code == 200
    ndjson2 = app_client.get(
        f"/v1/documents/{src}/export", params={"format": "ndjson"}, headers=_AUTH,
    ).text
    res = app_client.post(
        "/v1/documents/import", params={"doc_id": dst}, content=ndjson2,
        headers={**_AUTH, "Content-Type": _NDJSON},
    ).json()
    assert res["updated"] == 1
    assert res["created"] == 0

    listing = app_client.get(f"/v1/documents/{dst}/chapters", headers=_AUTH).json()
    assert listing["items"][0]["title"] == "第一章(修订)"


def test_import_syncs_document_metadata(app_client: TestClient) -> None:
    src = _create_doc_with_chapters(app_client, "源标题", [(0, "第一章", "正文一")])
    ndjson = app_client.get(
        f"/v1/documents/{src}/export", params={"format": "ndjson"}, headers=_AUTH,
    ).text
    dst = _create_empty_doc(app_client, "旧标题")
    res = app_client.post(
        "/v1/documents/import", params={"doc_id": dst}, content=ndjson,
        headers={**_AUTH, "Content-Type": _NDJSON},
    ).json()
    assert res["doc_updated"] is True
    refreshed = app_client.get(f"/v1/documents/{dst}", headers=_AUTH).json()
    assert refreshed["title"] == "源标题"


def test_import_incremental_sync_via_cursor(app_client: TestClient) -> None:
    src = _create_doc_with_chapters(
        app_client, "源作品", [(0, "第一章", "正文一"), (1, "第二章", "正文二")],
    )
    # First full export + import establishes the cursor.
    ndjson = app_client.get(
        f"/v1/documents/{src}/export", params={"format": "ndjson"}, headers=_AUTH,
    ).text
    dst = _create_empty_doc(app_client, "目标作品")
    first = app_client.post(
        "/v1/documents/import", params={"doc_id": dst}, content=ndjson,
        headers={**_AUTH, "Content-Type": _NDJSON},
    ).json()
    last_sync = first["last_sync"]
    assert last_sync is not None

    # Export with since=last_sync yields only the document line (no newer chapters).
    since_export = app_client.get(
        f"/v1/documents/{src}/export",
        params={"format": "ndjson", "since": last_sync},
        headers=_AUTH,
    )
    assert since_export.status_code == 200
    records = _parse_ndjson(since_export.text)
    assert records[0]["_type"] == "document"
    assert all(rec["_type"] != "chapter" for rec in records)


def test_import_missing_document_returns_404(app_client: TestClient) -> None:
    r = app_client.post(
        "/v1/documents/import",
        params={"doc_id": 99999},
        content='{"_type":"document","schema_version":1}',
        headers={**_AUTH, "Content-Type": _NDJSON},
    )
    assert r.status_code == 404


def test_import_requires_api_key(app_client: TestClient) -> None:
    r = app_client.post(
        "/v1/documents/import",
        params={"doc_id": 1},
        content='{"_type":"document","schema_version":1}',
    )
    assert r.status_code == 422


def test_import_invalid_ndjson_returns_400(app_client: TestClient) -> None:
    dst = _create_empty_doc(app_client, "目标作品")
    r = app_client.post(
        "/v1/documents/import",
        params={"doc_id": dst},
        content="this is not ndjson",
        headers={**_AUTH, "Content-Type": _NDJSON},
    )
    assert r.status_code == 400


def test_export_ndjson_does_not_break_existing_formats(app_client: TestClient) -> None:
    doc_id = _create_doc_with_chapters(app_client, "回归", [(0, "第一章", "正文")])
    for fmt in ("md", "txt", "epub", "qidian"):
        r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": fmt}, headers=_AUTH)
        assert r.status_code == 200, fmt
