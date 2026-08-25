"""Creative Kit endpoints nested under a document (作品).

Applies a generated inspiration kit (world settings + characters + outline)
in one atomic server-side transaction — the client no longer loops per-item
POST calls or round-trips the whole document metadata.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import load_parent, owner_key_hash, require_api_key
from app.db.session import get_db
from app.schemas.creative_kit import (
    CreativeKitApplyRequest,
    CreativeKitApplyResponse,
)
from app.services.creative_kit import apply_creative_kit
from app.services.document import DocumentNotFound

router = APIRouter(prefix="/v1/documents/{doc_id}/creative-kit", tags=["creative-kit"])


@router.post("/apply", response_model=CreativeKitApplyResponse)
async def apply_creative_kit_endpoint(
    doc_id: int,
    payload: CreativeKitApplyRequest,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> CreativeKitApplyResponse:
    """Apply a creative kit atomically (P0/P1: batched, rollback-safe).

    Outer document must exist and belong to the caller. Returns created /
    skipped counts plus the freshest document so the client can refresh its
    copy without re-fetching.
    """
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    try:
        return await apply_creative_kit(
            session, doc_id, payload, owner_key_hash=owner_key_hash(api_key),
        )
    except DocumentNotFound:
        raise HTTPException(status_code=404, detail="作品不存在")