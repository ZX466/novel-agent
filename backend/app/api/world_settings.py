"""World Setting CRUD endpoints nested under a document (作品).

World settings are scoped by novel_id, which is the parent document's id.
The parent must exist and be non-deleted.

Wire format mirrors the novel-memory schemas (WorldSettingCreate/Update/Read)
so the existing WorldSetting service can be reused unchanged.

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
    WorldSettingCreate,
    WorldSettingListResponse,
    WorldSettingRead,
    WorldSettingUpdate,
)
from app.services.world_setting import (
    WorldSettingNotFound,
    create_world_setting,
    delete_world_setting,
    get_world_setting,
    list_world_settings,
    update_world_setting,
)

router = APIRouter(prefix="/v1/documents/{doc_id}/world-settings", tags=["world-settings"])

logger = logging.getLogger(__name__)


@router.get("", response_model=WorldSettingListResponse)
async def list_world_settings_endpoint(
    doc_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10000),
    category: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> WorldSettingListResponse:
    """List world settings of a document, ordered by category then title."""
    await load_parent(session, doc_id)
    items, total = await list_world_settings(
        session, novel_id=doc_id, category=category, limit=limit, offset=offset
    )
    return WorldSettingListResponse(items=items, total=total)  # type: ignore[arg-type]


@router.post(
    "",
    response_model=WorldSettingRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_world_setting_endpoint(
    doc_id: int,
    payload: WorldSettingCreate,
    response: Response,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
    embedding_stage: StageConfig | None = Depends(extract_embedding_stage),
) -> WorldSettingRead:
    """Create a world setting under the document. Forces novel_id = doc_id.

    When X-Provider-Config carries an ``embedding`` stage, it overrides
    .env EMBEDDING_* credentials for the auto-embedding of this setting.
    """
    await load_parent(session, doc_id)
    payload = payload.model_copy(update={"novel_id": doc_id})
    ws = await create_world_setting(session, payload, stage_config=embedding_stage)
    response.headers["Location"] = f"/v1/documents/{doc_id}/world-settings/{ws.id}"
    return ws  # type: ignore[return-value]


@router.get("/{ws_id}", response_model=WorldSettingRead)
async def get_world_setting_endpoint(
    doc_id: int,
    ws_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> WorldSettingRead:
    """Get a single world setting by ID. 404 if missing or wrong novel."""
    await load_parent(session, doc_id)
    try:
        ws = await get_world_setting(session, ws_id)
    except WorldSettingNotFound:
        raise HTTPException(status_code=404, detail="世界设定不存在")
    if ws.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="世界设定不存在")
    return ws  # type: ignore[return-value]


@router.patch("/{ws_id}", response_model=WorldSettingRead)
async def update_world_setting_endpoint(
    doc_id: int,
    ws_id: int,
    payload: WorldSettingUpdate,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
    embedding_stage: StageConfig | None = Depends(extract_embedding_stage),
) -> WorldSettingRead:
    """Partial update a world setting. 404 if missing or wrong novel."""
    await load_parent(session, doc_id)
    try:
        ws = await update_world_setting(
            session, ws_id, payload, stage_config=embedding_stage,
        )
    except WorldSettingNotFound:
        raise HTTPException(status_code=404, detail="世界设定不存在")
    if ws.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="世界设定不存在")
    return ws  # type: ignore[return-value]


@router.delete("/{ws_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_world_setting_endpoint(
    doc_id: int,
    ws_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> Response:
    """Delete a world setting. 204 on success."""
    await load_parent(session, doc_id)
    try:
        existing = await get_world_setting(session, ws_id)
    except WorldSettingNotFound:
        raise HTTPException(status_code=404, detail="世界设定不存在")
    if existing.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="世界设定不存在")
    await delete_world_setting(session, ws_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
