"""Character relationship graph endpoints nested under a document (作品).

Sub-resource of the character CRUD router (prefix
`/v1/documents/{doc_id}/characters/relationships`). Provides the graph
contract for relationship-tree visualization and "drag-to-rewire" editing:

- GET /graph   — full nodes + edges in one request (frontend render)
- PUT /{subject_id}/{object_id}  — single-edge upsert (drag creates/rewires)
- DELETE /{subject_id}/{object_id} — remove an edge (drag disconnect)
- POST /import — batch upsert by character name (outline -> graph)

All endpoints enforce ownership via `load_parent` + `owner_key_hash`, follow
the existing X-API-Key scheme, and keep errors terse (no description leakage).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import load_parent, owner_key_hash, require_api_key
from app.db.session import get_db
from app.schemas.character_relationship import (
    CharacterRelationshipUpsert,
    RelationshipGraph,
    RelationshipImportRequest,
    RelationshipImportResult,
)
from app.services.character_relationship import (
    CharacterRelationshipNotFound,
    delete_relationship,
    get_graph,
    import_relationships,
    upsert_relationship,
)

router = APIRouter(
    prefix="/v1/documents/{doc_id}/characters/relationships",
    tags=["character-relationships"],
)

logger = logging.getLogger(__name__)


def _to_404(exc: CharacterRelationshipNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail=exc.message)


@router.get("/graph", response_model=RelationshipGraph)
async def get_graph_endpoint(
    doc_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> RelationshipGraph:
    """Return the full relationship graph for a document (nodes + edges)."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    return await get_graph(session, novel_id=doc_id)


@router.put("/{subject_id}/{object_id}", response_model=RelationshipImportResult)
async def upsert_relationship_endpoint(
    doc_id: int,
    subject_id: int,
    object_id: int,
    payload: CharacterRelationshipUpsert,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> RelationshipImportResult:
    """Create or update a single edge (drag-to-rewire). Idempotent."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    try:
        _, created = await upsert_relationship(
            session,
            novel_id=doc_id,
            subject_id=subject_id,
            object_id=object_id,
            payload=payload,
        )
    except CharacterRelationshipNotFound as exc:
        raise _to_404(exc)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="关系冲突或端点角色非法")
    return RelationshipImportResult(created=1 if created else 0, updated=0, skipped=0)


@router.delete(
    "/{subject_id}/{object_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_relationship_endpoint(
    doc_id: int,
    subject_id: int,
    object_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> Response:
    """Remove a single edge. 204 on success."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    try:
        await delete_relationship(
            session, novel_id=doc_id, subject_id=subject_id, object_id=object_id
        )
    except CharacterRelationshipNotFound as exc:
        raise _to_404(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import", response_model=RelationshipImportResult)
async def import_relationships_endpoint(
    doc_id: int,
    payload: RelationshipImportRequest,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> RelationshipImportResult:
    """Batch upsert edges by character name (outline -> graph)."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    return await import_relationships(session, novel_id=doc_id, request=payload)
