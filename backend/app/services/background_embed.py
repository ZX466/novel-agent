"""Background embedding scheduler (R10-⑤).

Lore writes (chapters / characters / world settings / plot events) used to
await the 4096-dim embedding inside the write transaction — a slow or hung
embedding API stalled every save by seconds to ~60s (provider timeout).
Embedding is not on the write's critical path: the row is already durable;
the vector only feeds RAG retrieval, which tolerates a few seconds of lag.

`schedule_embedding` fires the embed + vector write on an independent DB
session (AsyncSessionLocal) as a detached asyncio task. Errors are logged,
never propagated — same best-effort contract as the previous inline path.
"""
from __future__ import annotations

import asyncio
import importlib
import logging

from sqlalchemy import text as sql_text, update

from app.schemas.chat import StageConfig

logger = logging.getLogger(__name__)

# Strong references to in-flight tasks (prevent GC mid-flight).
_tasks: set[asyncio.Task] = set()


async def _run(
    table: str, object_id: int, text: str, stage_config: StageConfig | None,
    persist,  # async (AsyncSession, int, list[float]) -> None
) -> None:
    try:
        from app.db.session import AsyncSessionLocal
        from app.llm.embedding import embed_text
        embedding = await embed_text(text, stage_config=stage_config)
        async with AsyncSessionLocal() as session:
            await persist(session, object_id, embedding)
            await _clear_pending_flag(session, table, object_id)
            await session.commit()
        logger.info(
            "background-embed: %s id=%s done (%d dims)", table, object_id, len(embedding),
        )
    except Exception:
        logger.warning(
            "background-embed: %s id=%s failed — memory/RAG disabled for this "
            "row (check EMBEDDING_* in backend/.env)",
            table, object_id, exc_info=True,
        )


async def _clear_pending_flag(session, table: str, object_id: int) -> None:
    """Clear metadata_json.embedding_pending after a successful embed.

    The write path set this flag (same transaction as the content change) so
    clients can show an "索引中" indicator; retrieval incorporates the new
    text only after this flag clears. Uses a jsonb_set UPDATE so the flag
    clears atomically without clobbering concurrent metadata writes.
    """
    models = {
        # Only tables that actually carry metadata_json — an UPDATE against
        # a model without the column would error (swallowed by _run's guard,
        # but noisy).
        "chapter": ("app.models.chapter", "Chapter"),
        "world_setting": ("app.models.world_setting", "WorldSetting"),
    }
    entry = models.get(table)
    if entry is None:
        return
    module = importlib.import_module(entry[0])
    model = getattr(module, entry[1])
    stmt = (
        update(model)
        .where(model.id == object_id)
        .values(
            metadata_json=sql_text(
                "jsonb_set(COALESCE(metadata_json, '{}'::jsonb), "
                "'{embedding_pending}', 'false'::jsonb)"
            )
        )
    )
    await session.execute(stmt)


def schedule_embedding(
    table: str, object_id: int, text: str, stage_config: StageConfig | None,
    persist,
) -> None:
    """Fire-and-forget: embed `text`, persist via `persist(session, id, vec)`.

    No-op when text is empty or no event loop is running.
    """
    if not (text or "").strip():
        return

    async def _runner() -> None:
        await _run(table, object_id, text, stage_config, persist)

    try:
        task = asyncio.create_task(_runner())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except RuntimeError:
        logger.warning("background-embed: no running event loop, skipped %s id=%s", table, object_id)
