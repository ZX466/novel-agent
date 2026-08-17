"""Tests for document export endpoint."""
from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

_AUTH = {"X-API-Key": "test-key"}


def test_export_returns_404_for_missing_document(app_client: TestClient) -> None:
    r = app_client.get("/v1/documents/99/export", params={"format": "md"}, headers=_AUTH)
    assert r.status_code == 404


def test_export_markdown_basic(app_client: TestClient) -> None:
    create = app_client.post("/v1/documents", json={"title": "导出测试"}, headers=_AUTH)
    assert create.status_code == 201
    doc_id = create.json()["id"]

    app_client.post(
        f"/v1/documents/{doc_id}/chapters",
        json={"chapter_index": 0, "title": "第一章", "content_text": "这是第一章正文"},
        headers=_AUTH,
    )

    r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "md"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers["content-disposition"].lower()
    assert ".md" in r.headers["content-disposition"]
    body = r.text
    assert body.startswith("# 导出测试")
    assert "## 第一章" in body
    assert "这是第一章正文" in body


def test_export_text_basic(app_client: TestClient) -> None:
    create = app_client.post("/v1/documents", json={"title": "导出测试"}, headers=_AUTH)
    assert create.status_code == 201
    doc_id = create.json()["id"]

    app_client.post(
        f"/v1/documents/{doc_id}/chapters",
        json={"chapter_index": 0, "title": "第一章", "content_text": "这是第一章正文"},
        headers=_AUTH,
    )

    r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "txt"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "attachment" in r.headers["content-disposition"].lower()
    assert ".txt" in r.headers["content-disposition"]
    body = r.text
    assert body.startswith("导出测试")
    assert "第一章" in body
    assert "这是第一章正文" in body


def test_export_epub_zip_container(app_client: TestClient) -> None:
    create = app_client.post("/v1/documents", json={"title": "EPUB 测试"}, headers=_AUTH)
    assert create.status_code == 201
    doc_id = create.json()["id"]

    app_client.post(
        f"/v1/documents/{doc_id}/chapters",
        json={"chapter_index": 0, "title": "第一章", "content_text": "正文内容"},
        headers=_AUTH,
    )

    r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "epub"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/epub+zip"
    assert "attachment" in r.headers["content-disposition"].lower()
    assert ".epub" in r.headers["content-disposition"]

    data = BytesIO(r.content)
    with zipfile.ZipFile(data) as zf:
        names = zf.namelist()
        assert "mimetype" in names
        assert "META-INF/container.xml" in names
        assert "OEBPS/content.opf" in names
        assert "OEBPS/toc.ncx" in names
        assert any(name.startswith("OEBPS/chapter-") and name.endswith(".xhtml") for name in names)

        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "EPUB 测试" in opf


def test_export_requires_api_key(app_client: TestClient) -> None:
    r = app_client.get("/v1/documents/1/export", params={"format": "md"})
    assert r.status_code == 422
