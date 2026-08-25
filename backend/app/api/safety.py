"""交稿雷达 (R6-3) — pre-export safety preflight endpoint.

Deliberately non-blocking: calling this never modifies or locks the
document, and the frontend treats findings as advisory (the author can
ignore them and export anyway). Results are cached server-side by content
hash, so repeated checks of unchanged drafts are free.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import load_parent, owner_key_hash, require_api_key
from app.db.session import get_db
from app.schemas.safety import SafetyScanReport
from app.services.safety_scan import scan_document

router = APIRouter(tags=["safety"])

logger = logging.getLogger(__name__)


@router.get(
    "/v1/documents/{doc_id}/safety-scan",
    response_model=SafetyScanReport,
)
async def safety_scan_endpoint(
    doc_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> SafetyScanReport:
    """Run the advisory pre-export safety scan for a document.

    Tenant-scoped: 404 for missing or foreign documents (no existence
    oracle). Returns findings grouped by rule, with PII evidence masked.
    """
    owner = owner_key_hash(api_key)
    await load_parent(session, doc_id, owner_hash=owner)
    report = await scan_document(session, doc_id, owner_hash=owner)
    return SafetyScanReport(**report)