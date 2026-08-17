"""Semantic retrieval endpoints for novel memory collections.

Provides vector similarity search across chapters, characters, world
settings, plot events, and knowledge-base docs, scoped to a single
document (novel).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import extract_embedding_stage, load_parent, owner_key_hash, require_api_key
from app.db.session import get_db
from app.schemas.novel_memory import RetrievalHit
from app.services.retrieval import retrieve

router = APIRouter(prefix="/v1/documents/{doc_id}/retrieve", tags=["retrieval"])

logger = logging.getLogger(__name__)

_VALID_ENTITY_TYPES = {
    "chapter", "character", "world_setting", "plot_event", "knowledge_doc",
}


class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    entity_types: list[str] = Field(default_factory=lambda: ["chapter", "character", "world_setting", "plot_event", "knowledge_doc"])
    top_k: int = Field(default=5, ge=1, le=20)


class RetrievalResponse(BaseModel):
    hits: list[RetrievalHit]
    total: int


@router.post("", response_model=RetrievalResponse)
async def retrieve_endpoint(
    doc_id: int,
    request: RetrievalRequest,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
    embedding_stage=Depends(extract_embedding_stage),
) -> RetrievalResponse:
    """Perform semantic similarity search over the document's memory collections."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(_api_key))

    for et in request.entity_types:
        if et not in _VALID_ENTITY_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效的实体类型: {et}",
            )

    hits = await retrieve(
        session,
        request.query,
        novel_id=doc_id,
        k_per_collection=request.top_k,
        stage_config=embedding_stage,
    )

    filtered = [h for h in hits if h.entity_type in request.entity_types]

    logger.debug(
        "retrieval: doc_id=%d query_len=%d entity_types=%s hit_count=%d",
        doc_id,
        len(request.query),
        request.entity_types,
        len(filtered),
    )

    return RetrievalResponse(hits=filtered, total=len(filtered))
