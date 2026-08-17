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

    max_bytes = settings.knowledge_upload_max_bytes
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件过大（上限 {max_bytes} 字节）",
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
