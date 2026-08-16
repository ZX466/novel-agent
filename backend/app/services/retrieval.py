"""Unified vector retrieval over the four memory collections.

Single entry point: `retrieve(query, ...)` returns RetrievalHit[]
sorted by descending similarity score, merged across collections.

Uses pgvector's cosine distance operator `<=>`. Score = 1 - distance,
clamped to [0, 1]. Higher = more similar.

The embedding step uses app.llm.embedding.embed_text, which honors
BYOK stage_config (same StageConfig the chat pipeline uses). When None,
falls back to .env embedding credentials.

Important: the query text is NOT logged. Embeddings of user prompts are
sensitive (may contain story premises, character secrets).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.embedding import embed_text
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.plot_event import PlotEvent
from app.models.world_setting import WorldSetting
from app.schemas.chat import StageConfig
from app.schemas.novel_memory import RetrievalHit

logger = logging.getLogger(__name__)

# Default per-collection limit. Total result count = k_per_collection * 4.
DEFAULT_K_PER_COLLECTION = 3

# Cosine distance threshold below which results are considered irrelevant.
# pgvector cosine distance: 0 = identical, 2 = opposite. We keep results
# with distance < 1.0 (similarity > 0.0). Tune via env if needed.
DEFAULT_MAX_DISTANCE = 1.0


async def _search_one(
    session: AsyncSession,
    model: type,
    query_embedding: list[float],
    *,
    novel_id: int | None,
    k: int,
    max_distance: float,
) -> list[tuple[Any, float]]:
    """Generic cosine-similarity search on a single collection.

    Returns [(orm_instance, score)] sorted by descending score. Each
    ORM instance must have `embedding`, `id`, and `novel_id` columns.

    The score is `(1 - cosine_distance)` clamped to [0, 1].
    """
    distance_expr = model.embedding.cosine_distance(query_embedding).label("distance")
    stmt = (
        select(model, distance_expr)
        .where(model.embedding.is_not(None))
        .order_by(distance_expr.asc())
        .limit(k)
    )
    if novel_id is not None:
        stmt = stmt.where(model.novel_id == novel_id)
    result = await session.execute(stmt)
    hits: list[tuple[Any, float]] = []
    for row in result.all():
        instance, distance = row[0], row[1]
        if distance is None:
            continue
        if distance > max_distance:
            continue
        score = max(0.0, min(1.0, 1.0 - float(distance)))
        hits.append((instance, score))
    return hits


def _chapter_payload(ch: Chapter) -> dict[str, Any]:
    return {
        "chapter_index": ch.chapter_index,
        "title": ch.title,
        "summary": ch.summary,
        "status": ch.status,
        "word_count": ch.word_count,
    }


def _character_payload(c: Character) -> dict[str, Any]:
    return {
        "name": c.name,
        "role": c.role,
        "description": c.description,
        "attributes": c.attributes,
        "arc_summary": c.arc_summary,
    }


def _world_setting_payload(ws: WorldSetting) -> dict[str, Any]:
    return {
        "category": ws.category,
        "title": ws.title,
        "content_text": ws.content_text,
    }


def _plot_event_payload(pe: PlotEvent) -> dict[str, Any]:
    return {
        "chapter_index": pe.chapter_index,
        "event_type": pe.event_type,
        "summary": pe.summary,
        "involved_character_ids": pe.involved_character_ids,
    }


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    novel_id: int | None = None,
    k_per_collection: int = DEFAULT_K_PER_COLLECTION,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    stage_config: StageConfig | None = None,
) -> list[RetrievalHit]:
    """Embed the query and search all four collections.

    Returns RetrievalHit[] sorted by descending score, capped at
    `k_per_collection * 4` total entries.

    `novel_id` is REQUIRED for novel scope protection — a None value would
    search across ALL novels, leaking characters/worlds from one story into
    another's retrieval results. Raises ValueError when novel_id is None.

    Raises ValueError on empty query (propagated from embed_text).
    """
    if novel_id is None:
        raise ValueError(
            "retrieve() requires novel_id to be set — cross-novel retrieval "
            "is forbidden to prevent memory leakage between stories"
        )
    query_embedding = await embed_text(query, stage_config=stage_config)

    # Run the four collection searches. When the caller's session is bound to
    # a real engine, each collection search opens its own short-lived
    # read-only session and all four run concurrently. asyncpg cannot have two
    # queries in flight on a single connection, so sharing the caller's one
    # session would serialize the searches (or raise InterfaceError). Falls
    # back to sequential on the caller's session when `bind` is unavailable
    # (e.g. unit-test doubles without an engine).
    bind = getattr(session, "bind", None)
    if bind is not None:
        maker = async_sessionmaker(
            bind=bind, class_=AsyncSession,
            expire_on_commit=False, autoflush=False,
        )

        async def _search(model: type) -> list[tuple[Any, float]]:
            async with maker() as s:
                return await _search_one(
                    s, model, query_embedding,
                    novel_id=novel_id, k=k_per_collection,
                    max_distance=max_distance,
                )

        chapter_hits, character_hits, world_hits, event_hits = await asyncio.gather(
            _search(Chapter), _search(Character),
            _search(WorldSetting), _search(PlotEvent),
        )
    else:
        chapter_hits = await _search_one(
            session, Chapter, query_embedding,
            novel_id=novel_id, k=k_per_collection, max_distance=max_distance,
        )
        character_hits = await _search_one(
            session, Character, query_embedding,
            novel_id=novel_id, k=k_per_collection, max_distance=max_distance,
        )
        world_hits = await _search_one(
            session, WorldSetting, query_embedding,
            novel_id=novel_id, k=k_per_collection, max_distance=max_distance,
        )
        event_hits = await _search_one(
            session, PlotEvent, query_embedding,
            novel_id=novel_id, k=k_per_collection, max_distance=max_distance,
        )

    all_hits: list[RetrievalHit] = []
    for ch, score in chapter_hits:
        all_hits.append(RetrievalHit(
            entity_type="chapter", entity_id=ch.id, score=score,
            payload=_chapter_payload(ch),
        ))
    for c, score in character_hits:
        all_hits.append(RetrievalHit(
            entity_type="character", entity_id=c.id, score=score,
            payload=_character_payload(c),
        ))
    for ws, score in world_hits:
        all_hits.append(RetrievalHit(
            entity_type="world_setting", entity_id=ws.id, score=score,
            payload=_world_setting_payload(ws),
        ))
    for pe, score in event_hits:
        all_hits.append(RetrievalHit(
            entity_type="plot_event", entity_id=pe.id, score=score,
            payload=_plot_event_payload(pe),
        ))

    all_hits.sort(key=lambda h: h.score, reverse=True)
    logger.info(
        "retrieval: query_len=%d hits=%d (ch=%d c=%d ws=%d pe=%d)",
        len(query), len(all_hits),
        len(chapter_hits), len(character_hits),
        len(world_hits), len(event_hits),
    )
    return all_hits


async def retrieve_chapters(
    session: AsyncSession,
    query: str,
    *,
    novel_id: int | None = None,
    k: int = DEFAULT_K_PER_COLLECTION,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    stage_config: StageConfig | None = None,
) -> list[RetrievalHit]:
    """Single-collection variant: only chapters. Useful for "find prior
    chapters similar to this prompt" in chapter-writing agents."""
    query_embedding = await embed_text(query, stage_config=stage_config)
    hits = await _search_one(
        session, Chapter, query_embedding,
        novel_id=novel_id, k=k, max_distance=max_distance,
    )
    return [
        RetrievalHit(
            entity_type="chapter", entity_id=ch.id, score=score,
            payload=_chapter_payload(ch),
        )
        for ch, score in hits
    ]


async def retrieve_characters(
    session: AsyncSession,
    query: str,
    *,
    novel_id: int | None = None,
    k: int = DEFAULT_K_PER_COLLECTION,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    stage_config: StageConfig | None = None,
) -> list[RetrievalHit]:
    """Single-collection variant: only characters."""
    query_embedding = await embed_text(query, stage_config=stage_config)
    hits = await _search_one(
        session, Character, query_embedding,
        novel_id=novel_id, k=k, max_distance=max_distance,
    )
    return [
        RetrievalHit(
            entity_type="character", entity_id=c.id, score=score,
            payload=_character_payload(c),
        )
        for c, score in hits
    ]


async def retrieve_world_settings(
    session: AsyncSession,
    query: str,
    *,
    novel_id: int | None = None,
    k: int = DEFAULT_K_PER_COLLECTION,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    stage_config: StageConfig | None = None,
) -> list[RetrievalHit]:
    """Single-collection variant: only world_settings."""
    query_embedding = await embed_text(query, stage_config=stage_config)
    hits = await _search_one(
        session, WorldSetting, query_embedding,
        novel_id=novel_id, k=k, max_distance=max_distance,
    )
    return [
        RetrievalHit(
            entity_type="world_setting", entity_id=ws.id, score=score,
            payload=_world_setting_payload(ws),
        )
        for ws, score in hits
    ]


async def retrieve_plot_events(
    session: AsyncSession,
    query: str,
    *,
    novel_id: int | None = None,
    k: int = DEFAULT_K_PER_COLLECTION,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    stage_config: StageConfig | None = None,
) -> list[RetrievalHit]:
    """Single-collection variant: only plot_events."""
    query_embedding = await embed_text(query, stage_config=stage_config)
    hits = await _search_one(
        session, PlotEvent, query_embedding,
        novel_id=novel_id, k=k, max_distance=max_distance,
    )
    return [
        RetrievalHit(
            entity_type="plot_event", entity_id=pe.id, score=score,
            payload=_plot_event_payload(pe),
        )
        for pe, score in hits
    ]
