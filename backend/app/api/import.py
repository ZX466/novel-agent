"""Portable data gateway import endpoint (R6-4).

Accepts the NDJSON payload produced by ``GET /v1/documents/{id}/export`` and
idempotently upserts it into a target document. Chapters are upserted by
``chapter_id``; re-importing an unchanged payload is a no-op. The response
carries an idempotency report plus the ``last_sync`` cursor for incremental
sync.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import load_parent, require_api_key
from app.db.session import get_db
from app.services import portable

router = APIRouter(tags=["portable"])

_NDJSON_MEDIA = "application/x-ndjson"


@router.post("/v1/documents/import")
async def import_document(
    doc_id: int = Query(..., description="目标文档 id"),
    ndjson: str = Body(..., media_type=_NDJSON_MEDIA, description="NDJSON 导出内容"),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> dict:
    """Idempotently import a portable NDJSON payload into ``doc_id``.

    Returns created/updated/unchanged/skipped counts, whether the document
    metadata changed, and the ``last_sync`` cursor (max chapter updated_at).
    """
    await load_parent(session, doc_id)
    try:
        report = await portable.import_portable(session, doc_id, ndjson)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return report.to_dict()
