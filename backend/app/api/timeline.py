"""Timeline view endpoints (R6-2 时间线图谱).

Exposes the novel's plot events as a causal DAG so the editor can render the
timeline (nodes sorted by in-world date / chapter, edges following
prev_event_id, plus structural warnings). Read-only; the DAG itself is built
from the plot events the author already manages via the plot-events CRUD.

`limit`/`offset` bound the number of returned nodes (and the edges / warnings
/ topological order derived from them) so a large novel cannot balloon the
response.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import load_parent, owner_key_hash, require_api_key
from app.db.session import get_db
from app.schemas.timeline import TimelineResponse
from app.services.timeline import TimelineDag, TimelineTooLargeError, get_timeline

router = APIRouter(prefix="/v1/documents/{doc_id}/timeline", tags=["timeline"])

logger = logging.getLogger(__name__)


def _slice_dag(dag: TimelineDag, limit: int, offset: int) -> TimelineResponse:
    """Apply pagination over the DAG's nodes and derive the rest from them."""
    nodes = dag.nodes[offset : offset + limit]
    node_ids = {n.event_id for n in nodes}
    edges = [e for e in dag.edges if e.from_id in node_ids and e.to_id in node_ids]
    warnings = [w for w in dag.warnings if w.event_id in node_ids]
    topo = [eid for eid in dag.topological_ids if eid in node_ids]
    return TimelineResponse(
        nodes=nodes,
        edges=edges,
        warnings=warnings,
        topological_order=topo,
    )


@router.get("", response_model=TimelineResponse)
async def get_timeline_endpoint(
    doc_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> TimelineResponse:
    """Return the novel's timeline graph (nodes, edges, warnings)."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    try:
        dag = await get_timeline(session, novel_id=doc_id)
    except TimelineTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        )
    return _slice_dag(dag, limit, offset)