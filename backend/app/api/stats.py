"""Dashboard statistics endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import require_api_key
from app.db.session import get_db
from app.services.stats import get_dashboard_stats as _get_dashboard_stats

router = APIRouter(tags=["stats"])
logger = logging.getLogger(__name__)


@router.get("/v1/stats/dashboard")
async def get_dashboard_stats(
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> dict:
    """Return writing dashboard statistics.

    Metrics are based on document-level ``updated_at`` and ``word_count``.
    """
    return await _get_dashboard_stats(session)
