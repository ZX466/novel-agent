"""Setting-consistency endpoints (R5-3 设定一致性哨兵).

Scans a draft against stored character settings and lists the persisted
findings so the editor can one-click jump to the rework point (evidence
snippet + source collection row).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import (
    extract_embedding_stage,
    load_parent,
    owner_key_hash,
    require_api_key,
)
from app.db.session import get_db
from app.schemas.consistency import (
    ConsistencyCheckItem,
    ConsistencyCheckListResponse,
    ConsistencyCheckRequest,
)
from app.services.consistency import check_draft, list_checks

router = APIRouter(
    prefix="/v1/documents/{doc_id}/consistency", tags=["consistency"]
)

logger = logging.getLogger(__name__)


@router.post("/check", response_model=ConsistencyCheckListResponse)
async def run_consistency_check(
    doc_id: int,
    request: ConsistencyCheckRequest,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
    embedding_stage=Depends(extract_embedding_stage),
) -> ConsistencyCheckListResponse:
    """Scan a draft (stored chapter or raw text) and persist the findings."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(_api_key))
    try:
        rows = await check_draft(
            session,
            novel_id=doc_id,
            owner_key_hash=owner_key_hash(_api_key),
            chapter_id=request.chapter_id,
            content_text=request.content_text,
            stage_config=embedding_stage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    items = [ConsistencyCheckItem.model_validate(r) for r in rows]
    logger.info(
        "consistency: check doc_id=%d chapter_id=%s created=%d",
        doc_id, request.chapter_id, len(items),
    )
    return ConsistencyCheckListResponse(items=items, total=len(items))


@router.get("/checks", response_model=ConsistencyCheckListResponse)
async def consistency_check_list(
    doc_id: int,
    chapter_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
) -> ConsistencyCheckListResponse:
    """List the novel's persisted consistency checks (newest first)."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(_api_key))
    rows, total = await list_checks(
        session,
        novel_id=doc_id,
        owner_key_hash=owner_key_hash(_api_key),
        chapter_id=chapter_id,
        limit=limit,
        offset=offset,
    )
    items = [ConsistencyCheckItem.model_validate(r) for r in rows]
    return ConsistencyCheckListResponse(items=items, total=total)