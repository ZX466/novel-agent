"""Knowledge-base endpoints (F4 本地知识库).

Upload / list / delete text files scoped to one work (作品). Every route
requires X-API-Key and verifies the target document (novel) belongs to the
authenticated key via `load_parent` — preventing cross-tenant IDOR before
any chunk is read or written.

Upload accepts a single multipart file, enforces the extension whitelist +
byte-size limit (config: KNOWLEDGE_UPLOAD_*), and returns the created
chunks. Content is stored as plain text and is only ever served as text —
it is never rendered as HTML.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import (
    extract_embedding_stage,
    load_parent,
    owner_key_hash,
    require_api_key,
)
from app.core.redis import get_redis
from app.db.session import get_db
from app.config import settings
from app.schemas.knowledge_doc import (
    KnowledgeDocListResponse,
    KnowledgeUploadResponse,
)
from app.services.knowledge_doc import (
    KnowledgeDocError,
    KnowledgeFileNotFound,
    delete_knowledge_file,
    list_knowledge_files,
    sanitize_filename,
    upload_knowledge_doc,
)

router = APIRouter(prefix="/v1/documents/{doc_id}/knowledge", tags=["knowledge"])

logger = logging.getLogger(__name__)

# Known binary signatures — plain-text knowledge uploads must never match
# these (defense in depth beyond the extension whitelist, Codex F4 review).
_BINARY_MAGIC_PREFIXES = (
    b"%PDF",  # PDF
    b"PK\x03\x04",  # ZIP / docx / epub
    b"\x89PNG",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF8",  # GIF
    b"MZ",  # PE executable
    b"\x7fELF",  # ELF
    b"\x00\x00\x00\x18ftyp",  # MP4
    b"ID3",  # MP3
)


def _looks_like_binary(content: bytes) -> bool:
    """True if the payload starts with a known binary magic signature."""
    head = content[:8]
    return any(head.startswith(sig) for sig in _BINARY_MAGIC_PREFIXES)


async def _enforce_upload_rate_limit(owner: str) -> None:
    """Per-owner upload rate limit (Redis). Fail-open on Redis outage to keep
    uploads usable locally, consistent with the chat limiter."""
    window_seconds = 60
    key = f"rate-limit:knowledge:{owner}:{int(datetime.now(timezone.utc).timestamp() // window_seconds)}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
    except Exception as exc:  # noqa: BLE001 — Redis down: fail-open
        logger.error("Knowledge rate limiter unavailable: %s", type(exc).__name__)
        return
    if count > settings.knowledge_upload_rate_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="上传过于频繁，请稍后再试",
        )


@router.post("", response_model=KnowledgeUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_knowledge(
    doc_id: int,
    file: UploadFile,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
    embedding_stage=Depends(extract_embedding_stage),
) -> KnowledgeUploadResponse:
    """Upload a text file (md/markdown/txt) to the work's knowledge base."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))

    await _enforce_upload_rate_limit(owner_key_hash(api_key))

    max_bytes = settings.knowledge_upload_max_bytes
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件过大（上限 {max_bytes} 字节）",
        )
    if _looks_like_binary(content):
        # Generic message — never disclose what binary types are rejected.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的文件类型",
        )
    filename = file.filename or ""
    try:
        chunks, size = await upload_knowledge_doc(
            session,
            novel_id=doc_id,
            filename=filename,
            content=content,
            owner_key_hash=owner_key_hash(api_key),
            stage_config=embedding_stage,
        )
    except KnowledgeDocError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return KnowledgeUploadResponse(
        items=chunks,  # type: ignore[arg-type]
        total=len(chunks),
        file_size_bytes=size,
    )


@router.get("", response_model=KnowledgeDocListResponse)
async def list_knowledge(
    doc_id: int,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> KnowledgeDocListResponse:
    """List uploaded files (grouped by title) with per-file chunk counts."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))

    items, total = await list_knowledge_files(
        session,
        novel_id=doc_id,
        owner_key_hash=owner_key_hash(api_key),
        limit=limit,
        offset=offset,
    )
    return KnowledgeDocListResponse(items=items, total=total)  # type: ignore[arg-type]


@router.delete("/{title}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge(
    doc_id: int,
    title: str,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> None:
    """Delete every chunk of an uploaded file. 204 on success, 404 if the
    file does not exist for this work."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))

    clean_title = sanitize_filename(title)
    try:
        await delete_knowledge_file(
            session,
            novel_id=doc_id,
            title=clean_title,
            owner_key_hash=owner_key_hash(api_key),
        )
    except KnowledgeFileNotFound:
        raise HTTPException(status_code=404, detail="知识库文件不存在")
