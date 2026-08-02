"""Async CRUD + vector embedding service for Character.

All mutating functions flush + commit + refresh. Embeddings are now
auto-generated on create and on description change so the vector index
stays current without callers having to invoke update_character_embedding
explicitly. Embedding generation is best-effort: failures are logged and
never propagate (a saved character without an embedding is still valid —
it just isn't in the vector index until the next refresh).

Auto-embedding uses .env embedding credentials (no BYOK stage_config at
the service layer). The tool layer (SaveChapterTool etc.) supplies BYOK
stage_config explicitly when available.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.schemas.chat import StageConfig
from app.schemas.novel_memory import CharacterCreate, CharacterUpdate

logger = logging.getLogger(__name__)


# Fields whose change should trigger a re-embedding of the character.
_EMBED_TRIGGER_FIELDS = {"name", "role", "description", "attributes", "arc_summary"}


async def _maybe_embed_character(
    session: AsyncSession, c: Character, *, stage_config: StageConfig | None = None,
) -> None:
    """Best-effort auto-embedding. Never raises — logs on failure."""
    # Build a representative text to embed: name + role + description +
    # arc_summary. attributes (dict) is stringified.
    parts = [c.name or "", c.role or "", c.description or ""]
    if c.arc_summary:
        parts.append(c.arc_summary)
    if c.attributes:
        parts.append(str(c.attributes))
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        return
    try:
        from app.llm.embedding import embed_text
        embedding = await embed_text(text, stage_config=stage_config)
        await update_character_embedding(session, c.id, embedding)
    except Exception:
        logger.warning(
            "character: auto-embedding failed for character_id=%s — "
            "memory/RAG disabled for this row (check EMBEDDING_* in backend/.env)",
            c.id, exc_info=True,
        )


class CharacterNotFound(Exception):
    def __init__(self, character_id: int) -> None:
        super().__init__(f"Character id={character_id} not found")
        self.character_id = character_id


async def list_characters(
    session: AsyncSession,
    *,
    novel_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Character], int]:
    """Returns (items, total_count) ordered by name."""
    total_stmt = select(func.count(Character.id))
    list_stmt = select(Character).order_by(Character.name.asc())
    if novel_id is not None:
        total_stmt = total_stmt.where(Character.novel_id == novel_id)
        list_stmt = list_stmt.where(Character.novel_id == novel_id)
    total = await session.scalar(total_stmt)
    list_stmt = list_stmt.limit(limit).offset(offset)
    result = await session.execute(list_stmt)
    return list(result.scalars().all()), int(total or 0)


async def get_character(session: AsyncSession, character_id: int) -> Character:
    c = await session.scalar(select(Character).where(Character.id == character_id))
    if c is None:
        raise CharacterNotFound(character_id)
    return c


async def get_character_by_name(
    session: AsyncSession, novel_id: int, name: str
) -> Character | None:
    """Returns the character with the given name within a novel, or None."""
    return await session.scalar(
        select(Character).where(
            Character.novel_id == novel_id,
            Character.name == name,
        )
    )


async def create_character(
    session: AsyncSession, payload: CharacterCreate, *, stage_config: StageConfig | None = None,
) -> Character:
    c = Character(**payload.model_dump())
    session.add(c)
    await session.flush()
    await session.refresh(c)
    await _maybe_embed_character(session, c, stage_config=stage_config)
    await session.commit()
    # Refresh again after commit: the embedding flush above triggers onupdate on
    # `updated_at`, which expires the attribute. Async SQLAlchemy has no lazy
    # loading, so a stale/expired attribute raises DetachedInstanceError when
    # FastAPI serialises the response. A post-commit refresh re-loads all columns.
    await session.refresh(c)
    return c


async def update_character(
    session: AsyncSession, character_id: int, payload: CharacterUpdate, *,
    stage_config: StageConfig | None = None,
) -> Character:
    c = await get_character(session, character_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(c, field, value)
    await session.flush()
    await session.refresh(c)
    # Re-embed only when an embedding-relevant field changed.
    if updates.keys() & _EMBED_TRIGGER_FIELDS:
        await _maybe_embed_character(session, c, stage_config=stage_config)
    await session.commit()
    # Same post-commit refresh as create_character (see comment there).
    await session.refresh(c)
    return c


async def update_character_embedding(
    session: AsyncSession, character_id: int, embedding: list[float]
) -> None:
    c = await get_character(session, character_id)
    c.embedding = list(embedding)
    await session.flush()


async def delete_character(session: AsyncSession, character_id: int) -> None:
    c = await get_character(session, character_id)
    await session.delete(c)
    await session.commit()
