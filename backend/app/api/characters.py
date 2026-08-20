"""Character CRUD endpoints nested under a document (作品).

Characters are scoped by novel_id, which is the parent document's id. The
parent must exist and be non-deleted; a deleted work cannot have characters
edited (its characters remain in storage and surface again on restore).

Wire format mirrors the novel-memory schemas (CharacterCreate/Update/Read)
so the existing Character service can be reused unchanged.

Uses X-API-Key header authentication (same scheme as documents).
Accepts optional X-Provider-Config header (same as chat) to thread an
embedding BYOK stage into auto-embedding on create/update.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import extract_embedding_stage, load_parent, owner_key_hash, require_api_key
from app.db.session import get_db
from app.schemas.chat import StageConfig
from app.schemas.novel_memory import (
    CharacterCreate,
    CharacterListItem,
    CharacterListResponse,
    CharacterRead,
    CharacterUpdate,
)
from app.services.character import (
    CharacterNotFound,
    create_character,
    delete_character,
    get_character,
    list_characters,
    update_character,
)

router = APIRouter(prefix="/v1/documents/{doc_id}/characters", tags=["characters"])

logger = logging.getLogger(__name__)


@router.get("", response_model=CharacterListResponse)
async def list_characters_endpoint(
    doc_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10000),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> CharacterListResponse:
    """List characters of a document, ordered by name ascending."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    items, total = await list_characters(
        session, novel_id=doc_id, limit=limit, offset=offset
    )
    return CharacterListResponse(items=items, total=total)  # type: ignore[arg-type]


@router.post(
    "",
    response_model=CharacterRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_character_endpoint(
    doc_id: int,
    payload: CharacterCreate,
    response: Response,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
    embedding_stage: StageConfig | None = Depends(extract_embedding_stage),
) -> CharacterRead:
    """Create a character under the document. Forces novel_id = doc_id.

    When X-Provider-Config carries an ``embedding`` stage, it overrides
    .env EMBEDDING_* credentials for the auto-embedding of this character.
    """
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    payload = payload.model_copy(update={"novel_id": doc_id})
    try:
        c = await create_character(session, payload, stage_config=embedding_stage)
    except IntegrityError:
        # (novel_id, name) unique constraint — same name already exists.
        await session.rollback()
        raise HTTPException(status_code=409, detail="同名角色已存在")
    response.headers["Location"] = f"/v1/documents/{doc_id}/characters/{c.id}"
    return c  # type: ignore[return-value]


@router.get("/{char_id}", response_model=CharacterRead)
async def get_character_endpoint(
    doc_id: int,
    char_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> CharacterRead:
    """Get a single character by ID. 404 if missing or belongs to another document."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    try:
        c = await get_character(session, char_id)
    except CharacterNotFound:
        raise HTTPException(status_code=404, detail="角色不存在")
    if c.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="角色不存在")
    return c  # type: ignore[return-value]


@router.patch("/{char_id}", response_model=CharacterRead)
async def update_character_endpoint(
    doc_id: int,
    char_id: int,
    payload: CharacterUpdate,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
    embedding_stage: StageConfig | None = Depends(extract_embedding_stage),
) -> CharacterRead:
    """Partial update a character. 404 if missing or belongs to another document."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    try:
        c = await update_character(
            session, char_id, payload, stage_config=embedding_stage,
        )
    except CharacterNotFound:
        raise HTTPException(status_code=404, detail="角色不存在")
    if c.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="角色不存在")
    return c  # type: ignore[return-value]


@router.delete("/{char_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character_endpoint(
    doc_id: int,
    char_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> Response:
    """Delete a character. 204 on success."""
    await load_parent(session, doc_id, owner_hash=owner_key_hash(api_key))
    try:
        existing = await get_character(session, char_id)
    except CharacterNotFound:
        raise HTTPException(status_code=404, detail="角色不存在")
    if existing.novel_id != doc_id:
        raise HTTPException(status_code=404, detail="角色不存在")
    await delete_character(session, char_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
