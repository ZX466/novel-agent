"""Async CRUD + vector embedding service for Chapter.

All mutating functions flush + commit + refresh (matches document.py
pattern). Embeddings are now auto-generated on create and on
content_text change so the vector index stays current without callers
having to invoke update_chapter_embedding explicitly. Auto-embedding is
best-effort (failures logged, never propagated) and uses .env embedding
credentials; the tool layer (SaveChapterTool) supplies BYOK stage_config
when available.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.schemas.chat import StageConfig
from app.schemas.novel_memory import ChapterCreate, ChapterUpdate

logger = logging.getLogger(__name__)


class ChapterNotFound(Exception):
    """Raised when a chapter ID does not exist."""

    def __init__(self, chapter_id: int) -> None:
        super().__init__(f"Chapter id={chapter_id} not found")
        self.chapter_id = chapter_id


async def _maybe_embed_chapter(
    session: AsyncSession, ch: Chapter, *, stage_config: StageConfig | None = None,
) -> None:
    """Best-effort auto-embedding of chapter content. Never raises.

    Embeds content_text (falling back to summary) so the chapter becomes
    immediately searchable via search_lore. ``stage_config`` overrides .env
    embedding credentials when provided (BYOK embedding stage).
    """
    text = (ch.content_text or "").strip()
    if not text and ch.summary:
        text = ch.summary.strip()
    if not text:
        return
    try:
        from app.llm.embedding import embed_text
        embedding = await embed_text(text, stage_config=stage_config)
        await update_chapter_embedding(session, ch.id, embedding)
    except Exception:
        logger.warning(
            "chapter: auto-embedding failed for chapter_id=%s — "
            "memory/RAG disabled for this row (check EMBEDDING_* in backend/.env)",
            ch.id, exc_info=True,
        )


async def list_chapters(
    session: AsyncSession,
    *,
    novel_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Chapter], int]:
    """Returns (items, total_count) ordered by chapter_index ascending."""
    total_stmt = select(func.count(Chapter.id))
    list_stmt = select(Chapter).order_by(Chapter.chapter_index.asc())
    if novel_id is not None:
        total_stmt = total_stmt.where(Chapter.novel_id == novel_id)
        list_stmt = list_stmt.where(Chapter.novel_id == novel_id)
    total = await session.scalar(total_stmt)
    list_stmt = list_stmt.limit(limit).offset(offset)
    result = await session.execute(list_stmt)
    return list(result.scalars().all()), int(total or 0)


async def get_chapter(session: AsyncSession, chapter_id: int) -> Chapter:
    """Returns the chapter or raises ChapterNotFound."""
    ch = await session.scalar(select(Chapter).where(Chapter.id == chapter_id))
    if ch is None:
        raise ChapterNotFound(chapter_id)
    return ch


async def get_chapter_by_index(
    session: AsyncSession, novel_id: int, chapter_index: int
) -> Chapter | None:
    """Returns the chapter with the given index within a novel, or None."""
    return await session.scalar(
        select(Chapter).where(
            Chapter.novel_id == novel_id,
            Chapter.chapter_index == chapter_index,
        )
    )


async def create_chapter(
    session: AsyncSession, payload: ChapterCreate, *, stage_config: StageConfig | None = None,
) -> Chapter:
    """Creates a new chapter and triggers best-effort embedding generation."""
    if not payload.word_count and payload.content_text:
        # Auto-compute word_count if caller didn't supply. Chinese text:
        # len() counts codepoints (close to character count). For mixed
        # CJK+Latin this slightly overestimates "words" but is good enough
        # for progress tracking.
        ch = Chapter(
            novel_id=payload.novel_id,
            chapter_index=payload.chapter_index,
            title=payload.title,
            content_text=payload.content_text,
            summary=payload.summary,
            word_count=len(payload.content_text),
            status=payload.status,
            metadata_json=payload.metadata_json,
        )
    else:
        ch = Chapter(**payload.model_dump())
    session.add(ch)
    await session.flush()
    await session.refresh(ch)
    await _maybe_embed_chapter(session, ch, stage_config=stage_config)
    await session.commit()
    await session.refresh(ch)  # re-load after embedding flush expires updated_at
    return ch


async def update_chapter(
    session: AsyncSession, chapter_id: int, payload: ChapterUpdate, *,
    stage_config: StageConfig | None = None,
) -> Chapter:
    """Partial update via model_dump(exclude_unset=True). Re-embeds if content changed."""
    ch = await get_chapter(session, chapter_id)
    updates = payload.model_dump(exclude_unset=True)
    content_changed = "content_text" in updates
    for field, value in updates.items():
        setattr(ch, field, value)
    # If content_text changed, auto-update word_count (cheap, in-process).
    if content_changed and "word_count" not in updates:
        ch.word_count = len(ch.content_text or "")
    await session.flush()
    await session.refresh(ch)
    if content_changed:
        await _maybe_embed_chapter(session, ch, stage_config=stage_config)
    await session.commit()
    await session.refresh(ch)  # re-load after embedding flush expires updated_at
    return ch


async def update_chapter_embedding(
    session: AsyncSession, chapter_id: int, embedding: list[float]
) -> None:
    """Persist a pre-computed embedding. Flushes (caller commits)."""
    ch = await get_chapter(session, chapter_id)
    ch.embedding = list(embedding)
    await session.flush()


async def delete_chapter(session: AsyncSession, chapter_id: int) -> None:
    """Deletes the chapter. Commits. Raises ChapterNotFound if missing."""
    ch = await get_chapter(session, chapter_id)
    await session.delete(ch)
    await session.commit()


async def reorder_chapters(
    session: AsyncSession, novel_id: int, ordered: list[tuple[int, int]]
) -> list[Chapter]:
    """Reassign chapter_index for a batch of chapters within one novel.

    `ordered` is a list of (chapter_id, new_index) pairs. Loads each chapter
    by id, verifies it belongs to `novel_id` (prevents cross-novel tampering),
    sets the new index, and commits in one transaction. Returns the updated
    chapters ordered by their new index.

    Raises ChapterNotFound if any id is missing.
    """
    updated: list[Chapter] = []
    index_by_id: dict[int, int] = {}
    for ch_id, new_index in ordered:
        ch = await get_chapter(session, ch_id)
        if ch.novel_id != novel_id:
            # Chapter exists but belongs to a different novel — refuse to
            # move it across novels via a reorder call.
            raise ChapterNotFound(ch_id)
        ch.chapter_index = new_index
        index_by_id[ch_id] = new_index
        updated.append(ch)
    await session.commit()
    for ch in updated:
        await session.refresh(ch)
    updated.sort(key=lambda c: c.chapter_index)
    return updated
