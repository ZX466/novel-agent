"""Chapter CRUD endpoints nested under a document (作品).

Chapters are scoped by novel_id, which is the parent document's id. The
parent must exist and be non-deleted; a deleted work cannot have chapters
edited (its chapters remain in storage and surface again on restore).

Wire format mirrors the novel-memory schemas (ChapterCreate/Update/Read)
so the existing Chapter service can be reused unchanged.

Uses X-API-Key header authentication (same scheme as documents).
Accepts optional X-Provider-Config header (same as chat) to thread an
embedding BYOK stage into auto-embedding on create/update.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import owner_key_hash, require_api_key as _require_api_key
from app.db.session import get_db
from app.schemas.chat import StageConfig
from app.schemas.document import ChapterReorderRequest
from app.schemas.novel_memory import (
    ChapterCreate,
    ChapterListResponse,
    ChapterRead,
    ChapterUpdate,
)
from app.services.chapter import (
    ChapterNotFound,
    create_chapter,
    delete_chapter,
    get_chapter,
    list_chapters,
    reorder_chapters,
    update_chapter,
)
from app.services.document import DocumentNotFound, get_document

router = APIRouter(prefix="/v1/documents/{doc_id}/chapters", tags=["chapters"])

logger = logging.getLogger(__name__)


async def _extract_embedding_stage(
    x_provider_config: str | None = Header(None, alias="X-Provider-Config"),
) -> StageConfig | None:
    """Extract the embedding BYOK stage from X-Provider-Config header, if any.

    Returns None when the header is absent, malformed, or has no embedding
    stage configured — callers then fall back to .env EMBEDDING_* creds.
    """
    if not x_provider_config:
        return None
    try:
        data = json.loads(x_provider_config)
        emb = data.get("embedding")
        if emb and isinstance(emb, dict) and emb.get("api_base") and emb.get("api_key") and emb.get("model"):
            return StageConfig(**emb)
    except (json.JSONDecodeError, Exception):
        logger.debug("chapters: malformed X-Provider-Config header, ignoring")
    return None


async def _load_parent(session: AsyncSession, doc_id: int, api_key: str) -> None:
    """Ensure the parent document exists and is not soft-deleted.

    Chapter operations are blocked on a deleted work to avoid silent edits
    to 回收站 items. Raises 404 if missing or deleted.
    """
    try:
        await get_document(session, doc_id, owner_key_hash=owner_key_hash(api_key))
    except DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")


@router.get("", response_model=ChapterListResponse)
async def list_chapters_endpoint(
    doc_id: int,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10000),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> ChapterListResponse:
    """List chapters of a document, ordered by chapter_index ascending."""
    await _load_parent(session, doc_id, api_key)
    items, total = await list_chapters(
        session, novel_id=doc_id, limit=limit, offset=offset
    )
    return ChapterListResponse(items=items, total=total)  # type: ignore[arg-type]


@router.post(
    "",
    response_model=ChapterRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_chapter_endpoint(
    doc_id: int,
    payload: ChapterCreate,
    response: Response,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
    embedding_stage: StageConfig | None = Depends(_extract_embedding_stage),
) -> ChapterRead:
    """Create a chapter under the document. Forces novel_id = doc_id.

    The caller supplies chapter_index (the frontend computes "next index"
    from the current list). novel_id is pinned to the path's doc_id.

    When X-Provider-Config carries an ``embedding`` stage, it overrides
    .env EMBEDDING_* credentials for the auto-embedding of this chapter.
    """
    await _load_parent(session, doc_id, api_key)
    payload = payload.model_copy(update={"novel_id": doc_id})
    ch = await create_chapter(session, payload, stage_config=embedding_stage)
    response.headers["Location"] = f"/v1/documents/{doc_id}/chapters/{ch.id}"
    return ch  # type: ignore[return-value]


@router.patch("/{chapter_id}", response_model=ChapterRead)
async def update_chapter_endpoint(
    doc_id: int,
    chapter_id: int,
    payload: ChapterUpdate,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
    embedding_stage: StageConfig | None = Depends(_extract_embedding_stage),
) -> ChapterRead:
    """Partial update a chapter. 404 if missing."""
    await _load_parent(session, doc_id, api_key)
    try:
        ch = await update_chapter(
            session, chapter_id, payload, stage_config=embedding_stage,
        )
    except ChapterNotFound:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if ch.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return ch  # type: ignore[return-value]


@router.delete("/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chapter_endpoint(
    doc_id: int,
    chapter_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> Response:
    """Delete a chapter. 204 on success."""
    await _load_parent(session, doc_id, api_key)
    try:
        existing = await get_chapter(session, chapter_id)
    except ChapterNotFound:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if existing.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    await delete_chapter(session, chapter_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/reorder", response_model=ChapterListResponse)
async def reorder_chapters_endpoint(
    doc_id: int,
    payload: ChapterReorderRequest,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> ChapterListResponse:
    """Reorder chapters via drag-and-drop.

    Body: { chapters: [{ id, chapter_index }, ...] }. Assigns the given
    index to each chapter (within this document only) and returns the full
    re-ordered list.
    """
    await _load_parent(session, doc_id, api_key)
    ordered = [(item.id, item.chapter_index) for item in payload.chapters]
    try:
        items = await reorder_chapters(session, novel_id=doc_id, ordered=ordered)
    except ChapterNotFound:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return ChapterListResponse(items=items, total=len(items))  # type: ignore[arg-type]
