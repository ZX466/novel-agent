"""Async CRUD + vector embedding service for PlotEvent.

All mutating functions flush + commit + refresh. Embeddings are now
auto-generated on create and on summary/event_type change so the vector
index stays current. Auto-embedding is best-effort (failures logged, never
propagated) and uses .env embedding credentials.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plot_event import PlotEvent
from app.schemas.chat import StageConfig
from app.schemas.novel_memory import PlotEventCreate, PlotEventUpdate

logger = logging.getLogger(__name__)


# Fields whose change should trigger a re-embedding of the plot event.
_EMBED_TRIGGER_FIELDS = {"event_type", "summary", "chapter_index"}


async def _maybe_embed_plot_event(
    session: AsyncSession, pe: PlotEvent, *, stage_config: StageConfig | None = None,
) -> None:
    """Best-effort auto-embedding. Never raises — logs on failure."""
    parts = [pe.event_type or "", pe.summary or ""]
    if pe.chapter_index is not None:
        parts.append(f"chapter {pe.chapter_index}")
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        return
    try:
        from app.llm.embedding import embed_text
        embedding = await embed_text(text, stage_config=stage_config)
        await update_plot_event_embedding(session, pe.id, embedding)
    except Exception:
        logger.warning(
            "plot_event: auto-embedding failed for event_id=%s — "
            "memory/RAG disabled for this row (check EMBEDDING_* in backend/.env)",
            pe.id, exc_info=True,
        )


class PlotEventNotFound(Exception):
    def __init__(self, event_id: int) -> None:
        super().__init__(f"PlotEvent id={event_id} not found")
        self.event_id = event_id


async def list_plot_events(
    session: AsyncSession,
    *,
    novel_id: int | None = None,
    chapter_id: int | None = None,
    chapter_index: int | None = None,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[PlotEvent], int]:
    """Returns (items, total_count) ordered by chapter_index ascending
    (NULLS last via COALESCE) then by id."""
    total_stmt = select(func.count(PlotEvent.id))
    list_stmt = select(PlotEvent).order_by(
        func.coalesce(PlotEvent.chapter_index, -1).asc(),
        PlotEvent.id.asc(),
    )
    if novel_id is not None:
        total_stmt = total_stmt.where(PlotEvent.novel_id == novel_id)
        list_stmt = list_stmt.where(PlotEvent.novel_id == novel_id)
    if chapter_id is not None:
        total_stmt = total_stmt.where(PlotEvent.chapter_id == chapter_id)
        list_stmt = list_stmt.where(PlotEvent.chapter_id == chapter_id)
    if chapter_index is not None:
        total_stmt = total_stmt.where(PlotEvent.chapter_index == chapter_index)
        list_stmt = list_stmt.where(PlotEvent.chapter_index == chapter_index)
    if event_type is not None:
        total_stmt = total_stmt.where(PlotEvent.event_type == event_type)
        list_stmt = list_stmt.where(PlotEvent.event_type == event_type)
    total = await session.scalar(total_stmt)
    list_stmt = list_stmt.limit(limit).offset(offset)
    result = await session.execute(list_stmt)
    return list(result.scalars().all()), int(total or 0)


async def get_plot_event(session: AsyncSession, event_id: int) -> PlotEvent:
    pe = await session.scalar(select(PlotEvent).where(PlotEvent.id == event_id))
    if pe is None:
        raise PlotEventNotFound(event_id)
    return pe


async def create_plot_event(
    session: AsyncSession, payload: PlotEventCreate, *, stage_config: StageConfig | None = None,
) -> PlotEvent:
    pe = PlotEvent(**payload.model_dump())
    session.add(pe)
    await session.flush()
    await session.refresh(pe)
    await _maybe_embed_plot_event(session, pe, stage_config=stage_config)
    await session.commit()
    await session.refresh(pe)  # re-load after embedding flush expires updated_at
    return pe


async def update_plot_event(
    session: AsyncSession, event_id: int, payload: PlotEventUpdate, *,
    stage_config: StageConfig | None = None,
) -> PlotEvent:
    pe = await get_plot_event(session, event_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(pe, field, value)
    await session.flush()
    await session.refresh(pe)
    if updates.keys() & _EMBED_TRIGGER_FIELDS:
        await _maybe_embed_plot_event(session, pe, stage_config=stage_config)
    await session.commit()
    await session.refresh(pe)  # re-load after embedding flush expires updated_at
    return pe


async def update_plot_event_embedding(
    session: AsyncSession, event_id: int, embedding: list[float]
) -> None:
    pe = await get_plot_event(session, event_id)
    pe.embedding = list(embedding)
    await session.flush()


async def delete_plot_event(session: AsyncSession, event_id: int) -> None:
    pe = await get_plot_event(session, event_id)
    await session.delete(pe)
    await session.commit()
