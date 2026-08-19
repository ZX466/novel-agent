"""Async CRUD + vector embedding service for PlotEvent.

All mutating functions flush + commit + refresh. Embeddings are now
auto-generated on create and on summary/event_type change so the vector
index stays current. Auto-embedding is best-effort (failures logged, never
propagated) and uses .env embedding credentials.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
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


class PlotEventPredecessorNotFound(Exception):
    """prev_event_id references a missing event or one in a different novel.

    Raised at the service boundary so the API can return one unified error
    for both cases (no existence oracle / no id side-channel).
    """

    def __init__(self, prev_event_id: int) -> None:
        super().__init__(f"前置事件 id={prev_event_id} 不存在或不属于当前作品")
        self.prev_event_id = prev_event_id


async def _resolve_prev_event(
    session: AsyncSession, novel_id: int, prev_event_id: int | None,
) -> PlotEvent | None:
    """Return the predecessor when it exists AND belongs to the same novel."""
    if prev_event_id is None:
        return None
    return await session.scalar(
        select(PlotEvent).where(
            PlotEvent.id == prev_event_id,
            PlotEvent.novel_id == novel_id,
        )
    )


def _affected_chapter_refs(*events: PlotEvent | None) -> tuple[set[int], set[int]]:
    """Collect (chapter_ids, chapter_indexes) touched by the given events.

    An event may be tied to a chapter by id, by index, both, or neither —
    all non-None references are collected so `_refresh_chapter_warnings`
    recomputes every affected chapter (R6-2 复审 P2: chapter_id-only events
    must enter the affected set too).
    """
    ids: set[int] = set()
    indexes: set[int] = set()
    for e in events:
        if e is None:
            continue
        if e.chapter_id is not None:
            ids.add(e.chapter_id)
        if e.chapter_index is not None:
            indexes.add(e.chapter_index)
    return ids, indexes


async def _refresh_chapter_warnings(
    session: AsyncSession, *, novel_id: int,
    chapter_ids: set[int] | None = None,
    chapter_indexes: set[int] | None = None,
) -> None:
    """Recompute timeline warnings for affected chapters (R6-2 P2).

    Chapters can be matched by id, by chapter_index, or both; the union of
    all matches is refreshed. Keeps ``chapter.metadata_json.timeline_warnings``
    fresh when plot events change (including OLD predecessor chapters after a
    relation is removed/moved), and clears the key when the chapter no longer
    has any warning (residual cleanup). Best-effort; failures are logged,
    never raised.
    """
    chapter_ids = set(chapter_ids or ())
    chapter_indexes = set(chapter_indexes or ())
    if not chapter_ids and not chapter_indexes:
        return
    try:
        from app.services.timeline import validate_chapter_write

        conds = []
        if chapter_ids:
            conds.append(Chapter.id.in_(chapter_ids))
        if chapter_indexes:
            conds.append(Chapter.chapter_index.in_(chapter_indexes))
        result = await session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id, or_(*conds))
        )
        chapters = list(result.scalars().all())
        for ch in chapters:
            warnings = await validate_chapter_write(
                session,
                novel_id=novel_id,
                chapter_index=ch.chapter_index,
                chapter_id=ch.id,
            )
            metadata = dict(ch.metadata_json or {})
            if warnings:
                metadata["timeline_warnings"] = [
                    {"kind": w.kind, "event_id": w.event_id, "detail": w.detail}
                    for w in warnings
                ]
            else:
                metadata.pop("timeline_warnings", None)
            ch.metadata_json = metadata
        if chapters:
            await session.commit()
    except Exception:
        logger.warning(
            "plot_event: timeline warnings refresh failed for novel_id=%s — "
            "stored warnings may be stale",
            novel_id, exc_info=True,
        )


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
    prev = await _resolve_prev_event(session, payload.novel_id, payload.prev_event_id)
    if payload.prev_event_id is not None and prev is None:
        raise PlotEventPredecessorNotFound(payload.prev_event_id)
    pe = PlotEvent(**payload.model_dump())
    session.add(pe)
    await session.flush()
    await session.refresh(pe)
    await _maybe_embed_plot_event(session, pe, stage_config=stage_config)
    await session.commit()
    await session.refresh(pe)  # re-load after embedding flush expires updated_at
    ids, indexes = _affected_chapter_refs(pe, prev)
    await _refresh_chapter_warnings(
        session, novel_id=payload.novel_id,
        chapter_ids=ids, chapter_indexes=indexes,
    )
    return pe


async def update_plot_event(
    session: AsyncSession, event_id: int, payload: PlotEventUpdate, *,
    stage_config: StageConfig | None = None,
) -> PlotEvent:
    pe = await get_plot_event(session, event_id)
    updates = payload.model_dump(exclude_unset=True)
    new_prev: PlotEvent | None = None
    old_prev: PlotEvent | None = None
    if "prev_event_id" in updates and updates["prev_event_id"] is not None:
        new_prev = await _resolve_prev_event(
            session, pe.novel_id, updates["prev_event_id"]
        )
        if new_prev is None:
            raise PlotEventPredecessorNotFound(updates["prev_event_id"])
    if pe.prev_event_id is not None:
        # Refresh the OLD predecessor's chapter too when the relation is
        # removed/re-pointed — its warnings may reference this event (R6-2 复审 P2).
        old_prev = await _resolve_prev_event(session, pe.novel_id, pe.prev_event_id)
    old_chapter_id = pe.chapter_id
    old_chapter_index = pe.chapter_index
    for field, value in updates.items():
        setattr(pe, field, value)
    await session.flush()
    await session.refresh(pe)
    if updates.keys() & _EMBED_TRIGGER_FIELDS:
        await _maybe_embed_plot_event(session, pe, stage_config=stage_config)
    await session.commit()
    await session.refresh(pe)  # re-load after embedding flush expires updated_at
    ids, indexes = _affected_chapter_refs(pe, new_prev, old_prev)
    if old_chapter_id is not None:
        ids.add(old_chapter_id)
    if old_chapter_index is not None:
        indexes.add(old_chapter_index)
    await _refresh_chapter_warnings(
        session, novel_id=pe.novel_id, chapter_ids=ids, chapter_indexes=indexes,
    )
    return pe


async def update_plot_event_embedding(
    session: AsyncSession, event_id: int, embedding: list[float]
) -> None:
    pe = await get_plot_event(session, event_id)
    pe.embedding = list(embedding)
    await session.flush()


async def delete_plot_event(session: AsyncSession, event_id: int) -> None:
    """Delete a plot event, clearing successor pointers first.

    The same-novel composite FK is `(novel_id, prev_event_id)` with
    `ON DELETE SET NULL`; PostgreSQL would null BOTH local columns (including
    the NOT NULL `novel_id`), so successors are explicitly unlinked here
    within the same transaction before the row is deleted (R6-2 复审 P1).
    """
    pe = await get_plot_event(session, event_id)
    result = await session.execute(
        select(PlotEvent).where(
            PlotEvent.prev_event_id == pe.id,
            PlotEvent.novel_id == pe.novel_id,
        )
    )
    dependents = list(result.scalars().all())
    ids, indexes = _affected_chapter_refs(pe, *dependents)
    for d in dependents:
        d.prev_event_id = None
    await session.delete(pe)
    await session.commit()
    await _refresh_chapter_warnings(
        session, novel_id=pe.novel_id, chapter_ids=ids, chapter_indexes=indexes,
    )
