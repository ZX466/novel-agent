"""Unified vector retrieval over the memory collections.

Single entry point: `retrieve(query, ...)` returns RetrievalHit[]
sorted by descending similarity score, merged across collections.

Uses pgvector's cosine distance operator `<=>`. Score = 1 - distance,
clamped to [0, 1]. Higher = more similar.

World-building sources (world_settings + knowledge_docs) get a small
score boost (`SETTING_PRIORITY_BOOST`) so novel lore ranks above chapter
prose for equally-similar queries — "小说设定优先".

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
from app.models.knowledge_doc import KnowledgeDoc
from app.models.plot_event import PlotEvent
from app.models.world_setting import WorldSetting
from app.schemas.chat import StageConfig
from app.schemas.novel_memory import RetrievalHit

logger = logging.getLogger(__name__)

# Default per-collection limit. Total result count = k_per_collection * 5.
DEFAULT_K_PER_COLLECTION = 3

# Cosine distance threshold below which results are considered irrelevant.
# pgvector cosine distance: 0 = identical, 2 = opposite. We keep results
# with distance < 1.0 (similarity > 0.0). Tune via env if needed.
DEFAULT_MAX_DISTANCE = 1.0

# Novel-lore sources rank above plain prose when equally similar.
SETTING_PRIORITY_BOOST = 0.05
_SETTING_TYPES = {"world_setting", "knowledge_doc"}


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

    The `max_distance` filter is pushed down into the SQL WHERE clause
    (pgvector supports `embedding <=> :q < :max` with HNSW index) so the
    database scans only relevant rows before applying `LIMIT k`. Filtering
    only in Python after `LIMIT k` could drop rows and return fewer than
    `k` results.

    A Python-side distance check is retained as a defensive backstop: it
    guards against non-pgvector sessions / in-memory mocks that cannot
    enforce the SQL predicate, while real PostgreSQL enforces it in SQL
    and never returns out-of-range rows in the first place.
    """
    distance_expr = model.embedding.cosine_distance(query_embedding).label("distance")
    stmt = select(model, distance_expr).where(
        model.embedding.is_not(None),
        distance_expr < max_distance,
    )
    if novel_id is not None:
        stmt = stmt.where(model.novel_id == novel_id)
    stmt = stmt.order_by(distance_expr.asc()).limit(k)
    result = await session.execute(stmt)
    hits: list[tuple[Any, float]] = []
    for row in result.all():
        instance, distance = row[0], row[1]
        if distance is None:
            continue
        if distance > max_distance:
            # Defense in depth for non-pgvector sessions; real pgvector
            # already excluded these rows in SQL.
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


def _knowledge_payload(kd: KnowledgeDoc) -> dict[str, Any]:
    return {
        "title": kd.title,
        "chunk_index": kd.chunk_index,
        "content": kd.content,
    }


def _boosted_score(score: float, entity_type: str) -> float:
    """Apply the novel-settings priority bonus for world-building sources."""
    if entity_type in _SETTING_TYPES:
        return min(1.0, score + SETTING_PRIORITY_BOOST)
    return score


async def _search_knowledge(
    session: AsyncSession,
    query_embedding: list[float],
    *,
    novel_id: int | None,
    k: int,
    max_distance: float,
) -> list[tuple[Any, float]]:
    """Search the knowledge_docs collection.

    Picks the best chunk from each matching file so a single long upload
    cannot dominate the result set (knowledge chunks from one file are near
    each other in vector space and would otherwise crowd out other sources).
    """
    distance_expr = KnowledgeDoc.embedding.cosine_distance(query_embedding).label("distance")
    stmt = select(KnowledgeDoc, distance_expr).where(
        KnowledgeDoc.embedding.is_not(None),
        distance_expr < max_distance,
    )
    if novel_id is not None:
        stmt = stmt.where(KnowledgeDoc.novel_id == novel_id)
    stmt = stmt.order_by(distance_expr.asc()).limit(50)
    result = await session.execute(stmt)
    best_by_title: dict[str, tuple[KnowledgeDoc, float]] = {}
    for row in result.all():
        instance, distance = row[0], row[1]
        if distance is None or distance > max_distance:
            continue
        title = instance.title
        if title not in best_by_title or distance < best_by_title[title][1]:
            best_by_title[title] = (instance, distance)
    ranked = sorted(best_by_title.values(), key=lambda pair: pair[1])
    return [
        (instance, max(0.0, min(1.0, 1.0 - float(distance))))
        for instance, distance in ranked[:k]
    ]


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    novel_id: int | None = None,
    k_per_collection: int = DEFAULT_K_PER_COLLECTION,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    stage_config: StageConfig | None = None,
) -> list[RetrievalHit]:
    """Embed the query and search all five collections.

    Returns RetrievalHit[] sorted by descending score, capped at
    `k_per_collection * 5` total entries.

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

    # Run the five collection searches. When the caller's session is bound to
    # a real engine, each collection search opens its own short-lived
    # read-only session and all five run concurrently. asyncpg cannot have two
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

        async def _search_kn() -> list[tuple[Any, float]]:
            async with maker() as s:
                return await _search_knowledge(
                    s, query_embedding,
                    novel_id=novel_id, k=k_per_collection,
                    max_distance=max_distance,
                )

        (
            chapter_hits, character_hits, world_hits, event_hits, knowledge_hits,
        ) = await asyncio.gather(
            _search(Chapter), _search(Character),
            _search(WorldSetting), _search(PlotEvent),
            _search_kn(),
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
        knowledge_hits = await _search_knowledge(
            session, query_embedding,
            novel_id=novel_id, k=k_per_collection, max_distance=max_distance,
        )

    all_hits: list[RetrievalHit] = []
    for ch, score in chapter_hits:
        all_hits.append(RetrievalHit(
            entity_type="chapter", entity_id=ch.id, score=_boosted_score(score, "chapter"),
            payload=_chapter_payload(ch),
        ))
    for c, score in character_hits:
        all_hits.append(RetrievalHit(
            entity_type="character", entity_id=c.id, score=_boosted_score(score, "character"),
            payload=_character_payload(c),
        ))
    for ws, score in world_hits:
        all_hits.append(RetrievalHit(
            entity_type="world_setting", entity_id=ws.id,
            score=_boosted_score(score, "world_setting"),
            payload=_world_setting_payload(ws),
        ))
    for pe, score in event_hits:
        all_hits.append(RetrievalHit(
            entity_type="plot_event", entity_id=pe.id, score=_boosted_score(score, "plot_event"),
            payload=_plot_event_payload(pe),
        ))
    for kd, score in knowledge_hits:
        all_hits.append(RetrievalHit(
            entity_type="knowledge_doc", entity_id=kd.id,
            score=_boosted_score(score, "knowledge_doc"),
            payload=_knowledge_payload(kd),
        ))

    all_hits.sort(key=lambda h: h.score, reverse=True)
    logger.info(
        "retrieval: query_len=%d hits=%d (ch=%d c=%d ws=%d pe=%d kd=%d)",
        len(query), len(all_hits),
        len(chapter_hits), len(character_hits),
        len(world_hits), len(event_hits), len(knowledge_hits),
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


async def retrieve_knowledge_docs(
    session: AsyncSession,
    query: str,
    *,
    novel_id: int | None = None,
    k: int = DEFAULT_K_PER_COLLECTION,
    max_distance: float = DEFAULT_MAX_DISTANCE,
    stage_config: StageConfig | None = None,
) -> list[RetrievalHit]:
    """Single-collection variant: only knowledge_docs (uploaded lore files).

    One best chunk per file, so a single large upload cannot crowd out
    every other knowledge source.
    """
    query_embedding = await embed_text(query, stage_config=stage_config)
    hits = await _search_knowledge(
        session, query_embedding,
        novel_id=novel_id, k=k, max_distance=max_distance,
    )
    return [
        RetrievalHit(
            entity_type="knowledge_doc", entity_id=kd.id,
            score=_boosted_score(score, "knowledge_doc"),
            payload=_knowledge_payload(kd),
        )
        for kd, score in hits
    ]


async def retrieve_structured_lore(
    session: AsyncSession,
    *,
    novel_id: int,
    max_chars: int = 8000,
) -> str:
    """Structured lore fallback for draft context when vector RAG is
    unavailable (no EMBEDDING_* configured, or retrieval failed).

    Pulls the novel's characters, world settings, plot events and the most
    recent chapter summaries straight from the DB — no embeddings needed.
    Returns a formatted plain-text lore block (empty string if nothing found).
    """
    if novel_id is None:
        raise ValueError("retrieve_structured_lore() requires novel_id")

    blocks: list[str] = []

    # Characters (most prominent first: keep insertion order, cap by chars).
    char_rows = (
        await session.execute(
            select(Character)
            .where(Character.novel_id == novel_id)
            .order_by(Character.id.asc())
            .limit(50)
        )
    ).scalars().all()
    if char_rows:
        lines = ["【主要角色】"]
        for c in char_rows:
            desc = (c.description or "").strip()
            arc = (c.arc_summary or "").strip()
            parts = [f"角色：{c.name}（{c.role or '其他'}）"]
            if desc:
                parts.append(f"描述：{desc}")
            if arc:
                parts.append(f"弧线：{arc}")
            lines.append("；".join(parts))
        blocks.append("\n".join(lines))

    # World settings.
    ws_rows = (
        await session.execute(
            select(WorldSetting)
            .where(WorldSetting.novel_id == novel_id)
            .order_by(WorldSetting.id.asc())
            .limit(50)
        )
    ).scalars().all()
    if ws_rows:
        lines = ["【世界观设定】"]
        for ws in ws_rows:
            content = (getattr(ws, "content_text", "") or "").strip()
            lines.append(f"设定：{ws.title or ''}（{ws.category or '其他'}）{content}")
        blocks.append("\n".join(lines))

    # Plot events.
    pe_rows = (
        await session.execute(
            select(PlotEvent)
            .where(PlotEvent.novel_id == novel_id)
            .order_by(PlotEvent.id.asc())
            .limit(50)
        )
    ).scalars().all()
    if pe_rows:
        lines = ["【剧情事件】"]
        for pe in pe_rows:
            summary = (pe.summary or "").strip()
            lines.append(f"事件：{summary}")
        blocks.append("\n".join(lines))

    # Recent chapter summaries (tail of the story — what happened up to now).
    ch_rows = (
        await session.execute(
            select(Chapter)
            .where(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_index.desc())
            .limit(5)
        )
    ).scalars().all()
    if ch_rows:
        lines = ["【最近章节】"]
        for ch in reversed(ch_rows):
            summary = (ch.summary or "").strip()
            lines.append(f"第{ch.chapter_index}章《{ch.title or ''}》：{summary or '（无摘要）'}")
        blocks.append("\n".join(lines))

    if not blocks:
        return ""

    lore = "\n\n".join(blocks)
    return lore[:max_chars]
