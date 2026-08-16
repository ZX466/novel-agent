"""Plot Event CRUD endpoints nested under a document (作品).

Plot events are scoped by novel_id, which is the parent document's id. The
parent must exist and be non-deleted; a deleted work cannot have plot events
edited.

Wire format mirrors the novel-memory schemas (PlotEventCreate/Update/Read)
so the existing PlotEvent service can be reused unchanged.

Uses X-API-Key header authentication (same scheme as documents/chapters).
Accepts optional X-Provider-Config header (same as chat) to thread an
embedding BYOK stage into auto-embedding on create/update.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import extract_embedding_stage, load_parent, require_api_key
from app.db.session import get_db
from app.schemas.chat import StageConfig
from app.schemas.novel_memory import (
    PlotEventCreate,
    PlotEventListResponse,
    PlotEventRead,
    PlotEventUpdate,
)
from app.services.plot_event import (
    PlotEventNotFound,
    create_plot_event,
    delete_plot_event,
    get_plot_event,
    list_plot_events,
    update_plot_event,
)

router = APIRouter(prefix="/v1/documents/{doc_id}/plot-events", tags=["plot-events"])

logger = logging.getLogger(__name__)


@router.get("", response_model=PlotEventListResponse)
async def list_plot_events_endpoint(
    doc_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10000),
    chapter_index: int | None = Query(None, ge=0),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> PlotEventListResponse:
    """List plot events of a document, ordered by chapter_index ascending."""
    await load_parent(session, doc_id)
    items, total = await list_plot_events(
        session, novel_id=doc_id, limit=limit, offset=offset, chapter_index=chapter_index
    )
    return PlotEventListResponse(items=items, total=total)  # type: ignore[arg-type]


@router.post(
    "",
    response_model=PlotEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_plot_event_endpoint(
    doc_id: int,
    payload: PlotEventCreate,
    response: Response,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
    embedding_stage: StageConfig | None = Depends(extract_embedding_stage),
) -> PlotEventRead:
    """Create a plot event under the document. Forces novel_id = doc_id.

    When X-Provider-Config carries an ``embedding`` stage, it overrides
    .env EMBEDDING_* credentials for the auto-embedding of this plot event.
    """
    await load_parent(session, doc_id)
    payload = payload.model_copy(update={"novel_id": doc_id})
    pe = await create_plot_event(session, payload, stage_config=embedding_stage)
    response.headers["Location"] = f"/v1/documents/{doc_id}/plot-events/{pe.id}"
    return pe  # type: ignore[return-value]


@router.get("/{event_id}", response_model=PlotEventRead)
async def get_plot_event_endpoint(
    doc_id: int,
    event_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> PlotEventRead:
    """Get a single plot event by id. 404 if missing or not in this document."""
    await load_parent(session, doc_id)
    try:
        pe = await get_plot_event(session, event_id)
    except PlotEventNotFound:
        raise HTTPException(status_code=404, detail="情节事件不存在")
    if pe.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="情节事件不存在")
    return pe  # type: ignore[return-value]


@router.patch("/{event_id}", response_model=PlotEventRead)
async def update_plot_event_endpoint(
    doc_id: int,
    event_id: int,
    payload: PlotEventUpdate,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
    embedding_stage: StageConfig | None = Depends(extract_embedding_stage),
) -> PlotEventRead:
    """Partial update a plot event. 404 if missing."""
    await load_parent(session, doc_id)
    try:
        existing = await get_plot_event(session, event_id)
    except PlotEventNotFound:
        raise HTTPException(status_code=404, detail="情节事件不存在")
    if existing.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="情节事件不存在")
    pe = await update_plot_event(
        session, event_id, payload, stage_config=embedding_stage,
    )
    return pe  # type: ignore[return-value]


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plot_event_endpoint(
    doc_id: int,
    event_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> Response:
    """Delete a plot event. 204 on success."""
    await load_parent(session, doc_id)
    try:
        existing = await get_plot_event(session, event_id)
    except PlotEventNotFound:
        raise HTTPException(status_code=404, detail="情节事件不存在")
    if existing.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="情节事件不存在")
    await delete_plot_event(session, event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
