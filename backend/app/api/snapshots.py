"""Chapter snapshot endpoints (R5-4 ????).

Auto-snapshots are created by the frontend right before risky operations
(AI insert / whole-chapter replace / export) and on manual save; this
router stores, lists, restores, and deletes them. Every endpoint is
tenant-scoped via owner_key_hash and document-scoped via doc_id.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import owner_key_hash, require_api_key
from app.db.session import get_db
from app.schemas.novel_memory import ChapterRead
from app.schemas.snapshot import SnapshotCreate, SnapshotListResponse, SnapshotRead
from app.services.chapter import ChapterNotFound, get_chapter
from app.services.document import DocumentNotFound, get_document
from app.services.snapshot import (
    SnapshotNotFound,
    create_snapshot,
    delete_snapshot,
    list_snapshots,
    restore_snapshot,
)

router = APIRouter(
    prefix="/v1/documents/{doc_id}/chapters/{chapter_id}/snapshots",
    tags=["snapshots"],
)


async def _load_parent(session: AsyncSession, doc_id: int, api_key: str) -> None:
    """Ensure the parent document exists and is not soft-deleted."""
    try:
        await get_document(session, doc_id, owner_key_hash=owner_key_hash(api_key))
    except DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")


async def _load_chapter(
    session: AsyncSession, doc_id: int, chapter_id: int
) -> None:
    """Ensure the chapter exists and belongs to the document."""
    try:
        ch = await get_chapter(session, chapter_id)
    except ChapterNotFound:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if ch.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="Chapter not found")


@router.post(
    "",
    response_model=SnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_snapshot_endpoint(
    doc_id: int,
    chapter_id: int,
    payload: SnapshotCreate,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> SnapshotRead:
    """Create a snapshot of the chapter's current text."""
    await _load_parent(session, doc_id, api_key)
    await _load_chapter(session, doc_id, chapter_id)
    snap = await create_snapshot(
        session,
        owner_key_hash=owner_key_hash(api_key),
        novel_id=doc_id,
        chapter_id=chapter_id,
        content_text=payload.content_text,
        title=payload.title or "",
        reason=payload.reason,
    )
    return snap  # type: ignore[return-value]


@router.get("", response_model=SnapshotListResponse)
async def list_snapshots_endpoint(
    doc_id: int,
    chapter_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> SnapshotListResponse:
    """List snapshots for a chapter, newest-first."""
    await _load_parent(session, doc_id, api_key)
    await _load_chapter(session, doc_id, chapter_id)
    items, total = await list_snapshots(
        session,
        owner_key_hash=owner_key_hash(api_key),
        novel_id=doc_id,
        chapter_id=chapter_id,
        limit=limit,
        offset=offset,
    )
    return SnapshotListResponse(items=items, total=total)  # type: ignore[arg-type]


@router.post("/{snapshot_id}/restore", response_model=ChapterRead)
async def restore_snapshot_endpoint(
    doc_id: int,
    chapter_id: int,
    snapshot_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> ChapterRead:
    """Restore a chapter's text from a snapshot."""
    await _load_parent(session, doc_id, api_key)
    await _load_chapter(session, doc_id, chapter_id)
    try:
        ch = await restore_snapshot(
            session,
            snapshot_id=snapshot_id,
            owner_key_hash=owner_key_hash(api_key),
            novel_id=doc_id,
            chapter_id=chapter_id,
        )
    except SnapshotNotFound:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    except ChapterNotFound:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return ch  # type: ignore[return-value]


@router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snapshot_endpoint(
    doc_id: int,
    chapter_id: int,
    snapshot_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> Response:
    """Delete a snapshot."""
    await _load_parent(session, doc_id, api_key)
    await _load_chapter(session, doc_id, chapter_id)
    try:
        await delete_snapshot(
            session, snapshot_id, owner_key_hash=owner_key_hash(api_key)
        )
    except SnapshotNotFound:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
