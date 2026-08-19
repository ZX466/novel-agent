"""Timeline view endpoints (R6-2 时间线图谱).

Exposes the novel's plot events as a causal DAG so the editor can render the
timeline (nodes sorted by in-world date / chapter, edges following
prev_event_id, plus structural warnings). Read-only; the DAG itself is built
from the plot events the author already manages via the plot-events CRUD.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import load_parent, owner_key_hash, require_api_key
from app.db.session import get_db
from app.schemas.timeline import TimelineResponse
from app.services.timeline import get_timeline

router = APIRouter(prefix="/v1/documents/{doc_id}/timeline", tags=["timeline"])

logger = logging.getLogger(__name__)


@router.get("", response_model=TimelineResponse)
async def get_timeline_endpoint(
    doc_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> TimelineResponse:
    """Return the novel's timeline graph (nodes, edges, warnings)."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    dag = await get_timeline(session, novel_id=doc_id)
    return TimelineResponse(
        nodes=dag.nodes,
        edges=dag.edges,
        warnings=dag.warnings,
        topological_order=dag.topological_ids,
    )