"""Tests for the knowledge base (F4 本地知识库): chunking, upload
validation, service CRUD, retrieval integration, and the HTTP endpoints.

Service + retrieval tests use MockAsyncSession / mocked embed_batch so no
real DB or LLM call is made. API tests mock the service layer (same pattern
as test_documents_api.py) and the `load_parent` ownership guard.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.models.knowledge_doc import KnowledgeDoc
from app.services import knowledge_doc as kd_service
from app.services import retrieval
from tests.conftest import _FakeResult


# ===========================================================================
# chunk_text
# ===========================================================================


def test_chunk_text_paragraph_aware_packing():
    paras = [f"段落{i}" * 30 for i in range(1, 5)]  # each ~90 chars
    text = "\n\n".join(paras)
    chunks = kd_service.chunk_text(text, chunk_size=200)
    assert len(chunks) == 2
    assert all(len(c) <= 200 + 2 for c in chunks)
    # Packing must not split a paragraph: every chunk is a concatenation of
    # whole paragraphs.
    joined = "\n\n".join(chunks)
    for p in paras:
        assert p in joined
    assert "段落3" in chunks[1] and "段落4" in chunks[1]  # later paras packed together


def test_chunk_text_hard_splits_long_paragraph():
    text = "长" * 500
    chunks = kd_service.chunk_text(text, chunk_size=200)
    assert len(chunks) == 3  # 200 + 200 + 100
    assert chunks[0] == "长" * 200
    assert chunks[-1] == "长" * 100


def test_chunk_text_empty_input():
    assert kd_service.chunk_text("", chunk_size=200) == []
    assert kd_service.chunk_text("   \n\n  ", chunk_size=200) == []


# ===========================================================================
# sanitize_filename
# ===========================================================================


def test_sanitize_filename_strips_paths_and_controls():
    assert kd_service.sanitize_filename("../../etc/passwd") == "passwd"
    assert kd_service.sanitize_filename("C:\\Users\\evil\\notes.md") == "notes.md"
    assert kd_service.sanitize_filename("a\x00b.txt") == "ab.txt"
    assert kd_service.sanitize_filename("  lore.txt  ") == "lore.txt"
    assert kd_service.sanitize_filename("...") == "untitled.txt"


# ===========================================================================
# upload_knowledge_doc (service)
# ===========================================================================


@pytest.mark.asyncio
async def test_upload_validates_extension(mock_session):
    with patch.object(kd_service, "embed_batch", AsyncMock(return_value=[[0.1]])):
        with pytest.raises(kd_service.KnowledgeDocError, match="不支持的文件类型"):
            await kd_service.upload_knowledge_doc(
                mock_session, novel_id=7, filename="evil.exe",
                content=b"x", owner_key_hash="h",
            )


@pytest.mark.asyncio
async def test_upload_validates_size(monkeypatch, mock_session):
    monkeypatch.setattr(settings, "knowledge_upload_max_bytes", 10)
    with pytest.raises(kd_service.KnowledgeDocError, match="文件过大"):
        await kd_service.upload_knowledge_doc(
            mock_session, novel_id=7, filename="big.txt",
            content=b"0123456789A", owner_key_hash="h",
        )


@pytest.mark.asyncio
async def test_upload_rejects_invalid_utf8(mock_session):
    with pytest.raises(kd_service.KnowledgeDocError, match="UTF-8"):
        await kd_service.upload_knowledge_doc(
            mock_session, novel_id=7, filename="bad.txt",
            content=b"\xff\xfe\x00", owner_key_hash="h",
        )


@pytest.mark.asyncio
async def test_upload_rejects_empty_content(mock_session):
    with pytest.raises(kd_service.KnowledgeDocError, match="内容为空"):
        await kd_service.upload_knowledge_doc(
            mock_session, novel_id=7, filename="empty.txt",
            content=b"   ", owner_key_hash="h",
        )


@pytest.mark.asyncio
async def test_upload_chunks_embeds_and_persists(mock_session, monkeypatch):
    monkeypatch.setattr(settings, "knowledge_chunk_size", 200)
    text = "\n\n".join(["设定" * 40] * 3)  # 3 × 80 chars → 2 chunks (~162 + 80)
    vectors = [[0.1], [0.2]]
    with patch.object(kd_service, "embed_batch", AsyncMock(return_value=vectors)) as emb:
        rows, size = await kd_service.upload_knowledge_doc(
            mock_session, novel_id=7, filename="lore.md",
            content=text.encode("utf-8"), owner_key_hash="owner-hash",
        )

    emb.assert_awaited_once()
    assert len(rows) == 2
    assert size == len(text.encode("utf-8"))
    assert all(r.novel_id == 7 and r.owner_key_hash == "owner-hash" for r in rows)
    assert [r.chunk_index for r in rows] == [0, 1]
    assert rows[0].embedding == [0.1]
    assert rows[1].embedding == [0.2]
    assert mock_session.commits == 1
    assert len(mock_session.added) == 2


# ===========================================================================
# list / delete (service)
# ===========================================================================


def _kd(doc_id: int, title: str, idx: int, content: str = "x"):
    return KnowledgeDoc(
        id=doc_id, novel_id=7, owner_key_hash="h", title=title,
        chunk_index=idx, content=content,
    )


@pytest.mark.asyncio
async def test_list_groups_by_title_with_counts(mock_session):
    mock_session.set_execute_results([
        _FakeResult(scalars=[
            _kd(1, "lore.md", 0), _kd(2, "lore.md", 1),
            _kd(3, "gods.md", 0),
        ]),
    ])
    items, total = await kd_service.list_knowledge_files(
        mock_session, novel_id=7, owner_key_hash="h",
    )
    assert total == 2
    by_title = {f["title"]: f["chunk_count"] for f in items}
    assert by_title == {"lore.md": 2, "gods.md": 1}


@pytest.mark.asyncio
async def test_delete_removes_all_chunks(mock_session):
    mock_session.set_scalar_results([2])
    result = _FakeResult()
    result.rowcount = 2
    mock_session.set_execute_results([result])

    deleted = await kd_service.delete_knowledge_file(
        mock_session, novel_id=7, title="lore.md", owner_key_hash="h",
    )
    assert deleted == 2
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_delete_missing_raises(mock_session):
    mock_session.set_scalar_results([0])
    with pytest.raises(kd_service.KnowledgeFileNotFound):
        await kd_service.delete_knowledge_file(
            mock_session, novel_id=7, title="nope.md", owner_key_hash="h",
        )


# ===========================================================================
# retrieval integration
# ===========================================================================


@pytest.mark.asyncio
async def test_retrieve_knowledge_docs_single_collection(mock_session):
    mock_session.set_execute_results([
        _FakeResult(rows=[
            (type("KD", (), {"id": 11, "title": "magic.md", "chunk_index": 0,
                             "content": "魔法体系"})(), 0.2),
        ]),
    ])
    with patch.object(retrieval, "embed_text", AsyncMock(return_value=[0.0] * 1536)):
        hits = await retrieval.retrieve_knowledge_docs(
            mock_session, "魔法", novel_id=7,
        )
    assert len(hits) == 1
    h = hits[0]
    assert h.entity_type == "knowledge_doc"
    assert h.entity_id == 11
    assert h.payload["title"] == "magic.md"
    # Boosted score: 0.8 + 0.05.
    assert pytest.approx(h.score, abs=1e-6) == 0.85


@pytest.mark.asyncio
async def test_search_knowledge_picks_best_chunk_per_file(mock_session):
    """Two chunks from the same file → only the closer one survives."""
    rows = [
        (type("KD", (), {"id": 1, "title": "a.md", "chunk_index": 0,
                         "content": "x"})(), 0.9),
        (type("KD", (), {"id": 2, "title": "a.md", "chunk_index": 1,
                         "content": "y"})(), 0.2),
        (type("KD", (), {"id": 3, "title": "b.md", "chunk_index": 0,
                         "content": "z"})(), 0.5),
    ]
    mock_session.set_execute_results([_FakeResult(rows=rows)])
    hits = await retrieval._search_knowledge(
        mock_session, [0.0] * 1536, novel_id=7, k=2, max_distance=1.0,
    )
    assert [inst.id for inst, _ in hits] == [2, 3]
    # Returns SCORES (1 - distance): 0.8 for chunk 2, 0.5 for chunk 3.
    assert [score for _, score in hits] == pytest.approx([0.8, 0.5])


# ===========================================================================
# HTTP API
# ===========================================================================

_AUTH = {"X-API-Key": "test-key"}


def _fake_chunk(cid: int = 1, title: str = "lore.md", idx: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        id=cid, title=title, chunk_index=idx, content="设定内容",
        created_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )


def test_upload_requires_auth(app_client: TestClient) -> None:
    # The dependency declares a required X-API-Key header → FastAPI rejects
    # the missing header with 422 before the handler runs.
    r = app_client.post("/v1/documents/7/knowledge")
    assert r.status_code == 422


def test_upload_201_and_returns_chunks(app_client: TestClient) -> None:
    fake = _fake_chunk()
    with patch("app.api.knowledge_docs.load_parent", new=AsyncMock()), \
            patch("app.api.knowledge_docs.upload_knowledge_doc",
                  new=AsyncMock(return_value=([fake], 24))):
        r = app_client.post(
            "/v1/documents/7/knowledge",
            headers=_AUTH,
            files={"file": ("lore.md", ("# 设定\n" + "设定内容" * 10).encode("utf-8"), "text/markdown")},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["total"] == 1
    assert body["file_size_bytes"] == 24
    assert body["items"][0]["title"] == "lore.md"
    assert body["items"][0]["chunk_index"] == 0


def test_upload_rejects_bad_extension(app_client: TestClient) -> None:
    async def _raise(*a, **k):
        raise kd_service.KnowledgeDocError("不支持的文件类型: .exe（允许: markdown, md, txt）")

    with patch("app.api.knowledge_docs.load_parent", new=AsyncMock()), \
            patch("app.api.knowledge_docs.upload_knowledge_doc", new=_raise):
        r = app_client.post(
            "/v1/documents/7/knowledge",
            headers=_AUTH,
            files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
        )
    assert r.status_code == 400
    assert "不支持的文件类型" in r.json()["detail"]


def test_upload_rejects_oversized_payload(app_client: TestClient) -> None:
    with patch("app.api.knowledge_docs.load_parent", new=AsyncMock()), \
            patch.object(settings, "knowledge_upload_max_bytes", 8):
        r = app_client.post(
            "/v1/documents/7/knowledge",
            headers=_AUTH,
            files={"file": ("big.txt", b"123456789", "text/plain")},
        )
    assert r.status_code == 400
    assert "文件过大" in r.json()["detail"]


def test_upload_404_when_novel_missing(app_client: TestClient) -> None:
    async def _raise(*a, **k):
        raise HTTPException(status_code=404, detail="作品不存在")

    with patch("app.api.knowledge_docs.load_parent", new=_raise):
        r = app_client.post(
            "/v1/documents/999/knowledge",
            headers=_AUTH,
            files={"file": ("a.txt", b"hi", "text/plain")},
        )
    assert r.status_code == 404


def test_list_returns_grouped_files(app_client: TestClient) -> None:
    items = [
        {"title": "lore.md", "chunk_count": 2, "created_at": datetime(2026, 8, 17)},
    ]
    with patch("app.api.knowledge_docs.load_parent", new=AsyncMock()), \
            patch("app.api.knowledge_docs.list_knowledge_files",
                  new=AsyncMock(return_value=(items, 1))):
        r = app_client.get("/v1/documents/7/knowledge", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "lore.md"
    assert body["items"][0]["chunk_count"] == 2


def test_delete_returns_204(app_client: TestClient) -> None:
    with patch("app.api.knowledge_docs.load_parent", new=AsyncMock()), \
            patch("app.api.knowledge_docs.delete_knowledge_file",
                  new=AsyncMock(return_value=2)):
        r = app_client.delete("/v1/documents/7/knowledge/lore.md", headers=_AUTH)
    assert r.status_code == 204


def test_delete_404_when_file_missing(app_client: TestClient) -> None:
    async def _raise(*a, **k):
        raise kd_service.KnowledgeFileNotFound("nope.md")

    with patch("app.api.knowledge_docs.load_parent", new=AsyncMock()), \
            patch("app.api.knowledge_docs.delete_knowledge_file", new=_raise):
        r = app_client.delete("/v1/documents/7/knowledge/nope.md", headers=_AUTH)
    assert r.status_code == 404
