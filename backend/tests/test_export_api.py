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


def _create_doc_with_chapter(app_client: TestClient, title: str, chapter_title: str, body: str) -> int:
    create = app_client.post("/v1/documents", json={"title": title}, headers=_AUTH)
    assert create.status_code == 201
    doc_id = create.json()["id"]
    app_client.post(
        f"/v1/documents/{doc_id}/chapters",
        json={"chapter_index": 0, "title": chapter_title, "content_text": body},
        headers=_AUTH,
    )
    return doc_id


def test_export_qidian_renders_platform_markdown(app_client: TestClient) -> None:
    doc_id = _create_doc_with_chapter(app_client, "导出平台", "第一章", "正文")
    r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "qidian"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert ".md" in r.headers["content-disposition"]
    body = r.text
    assert "第1章 第一章" in body
    assert "起点" in body


def test_export_jj_renders_platform_markdown(app_client: TestClient) -> None:
    doc_id = _create_doc_with_chapter(app_client, "导出平台", "第一章", "正文")
    r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "jj"}, headers=_AUTH)
    assert r.status_code == 200
    assert "晋江" in r.text
    assert "谢绝转载" in r.text


def test_export_zhihu_renders_platform_markdown(app_client: TestClient) -> None:
    doc_id = _create_doc_with_chapter(app_client, "导出平台", "第一章", "正文")
    r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "zhihu"}, headers=_AUTH)
    assert r.status_code == 200
    assert "知乎专栏" in r.text


def test_export_wechat_renders_platform_markdown(app_client: TestClient) -> None:
    doc_id = _create_doc_with_chapter(app_client, "导出平台", "第一章", "正文")
    r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "wechat"}, headers=_AUTH)
    assert r.status_code == 200
    assert "原创" in r.text


def test_export_invalid_platform_returns_422(app_client: TestClient) -> None:
    r = app_client.get("/v1/documents/1/export", params={"format": "medium"}, headers=_AUTH)
    assert r.status_code == 422


def test_export_epub_escapes_special_chars_in_titles(app_client: TestClient) -> None:
    create = app_client.post(
        "/v1/documents",
        json={"title": 'A & B <C> "D" \'E\''},
        headers=_AUTH,
    )
    assert create.status_code == 201
    doc_id = create.json()["id"]

    app_client.post(
        f"/v1/documents/{doc_id}/chapters",
        json={"chapter_index": 0, "title": 'Ch & <X> "Y" \'Z\'' , "content_text": "body"},
        headers=_AUTH,
    )

    r = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "epub"}, headers=_AUTH)
    assert r.status_code == 200

    data = BytesIO(r.content)
    with zipfile.ZipFile(data) as zf:
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:title>A &amp; B &lt;C&gt; &quot;D&quot; &apos;E&apos;</dc:title>" in opf

        toc = zf.read("OEBPS/toc.ncx").decode("utf-8")
        assert "<text>A &amp; B &lt;C&gt; &quot;D&quot; &apos;E&apos;</text>" in toc

        chapter_name = [n for n in zf.namelist() if n.startswith("OEBPS/chapter-") and n.endswith(".xhtml")][0]
        chapter_xml = zf.read(chapter_name).decode("utf-8")
        assert "<h1>Ch &amp; &lt;X&gt; &quot;Y&quot; &apos;Z&apos;</h1>" in chapter_xml
        assert "<title>Ch &amp; &lt;X&gt; &quot;Y&quot; &apos;Z&apos;</title>" in chapter_xml
