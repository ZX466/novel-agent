"""Async CRUD + vector embedding service for WorldSetting.

All mutating functions flush + commit + refresh. Embeddings are now
auto-generated on create and on content/category/title change so the
vector index stays current. Auto-embedding is best-effort (failures
logged, never propagated) and uses .env embedding credentials.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.world_setting import WorldSetting
from app.schemas.chat import StageConfig
from app.schemas.novel_memory import (
    WorldSettingCreate,
    WorldSettingUpdate,
)

logger = logging.getLogger(__name__)


# Fields whose change should trigger a re-embedding of the world setting.
_EMBED_TRIGGER_FIELDS = {"category", "title", "content_text"}


async def _maybe_embed_world_setting(
    session: AsyncSession, ws: WorldSetting, *, stage_config: StageConfig | None = None,
) -> None:
    """Best-effort auto-embedding. Never raises — logs on failure."""
    parts = [ws.category or "", ws.title or "", ws.content_text or ""]
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        return
    try:
        from app.llm.embedding import embed_text
        embedding = await embed_text(text, stage_config=stage_config)
        await update_world_setting_embedding(session, ws.id, embedding)
    except Exception:
        logger.warning(
            "world_setting: auto-embedding failed for setting_id=%s — "
            "memory/RAG disabled for this row (check EMBEDDING_* in backend/.env)",
            ws.id, exc_info=True,
        )


class WorldSettingNotFound(Exception):
    def __init__(self, setting_id: int) -> None:
        super().__init__(f"WorldSetting id={setting_id} not found")
        self.setting_id = setting_id


async def list_world_settings(
    session: AsyncSession,
    *,
    novel_id: int | None = None,
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[WorldSetting], int]:
    """Returns (items, total_count) ordered by category then title."""
    total_stmt = select(func.count(WorldSetting.id))
    list_stmt = select(WorldSetting).order_by(
        WorldSetting.category.asc(),
        WorldSetting.title.asc(),
    )
    if novel_id is not None:
        total_stmt = total_stmt.where(WorldSetting.novel_id == novel_id)
        list_stmt = list_stmt.where(WorldSetting.novel_id == novel_id)
    if category is not None:
        total_stmt = total_stmt.where(WorldSetting.category == category)
        list_stmt = list_stmt.where(WorldSetting.category == category)
    total = await session.scalar(total_stmt)
    list_stmt = list_stmt.limit(limit).offset(offset)
    result = await session.execute(list_stmt)
    return list(result.scalars().all()), int(total or 0)


async def get_world_setting(
    session: AsyncSession, setting_id: int
) -> WorldSetting:
    ws = await session.scalar(
        select(WorldSetting).where(WorldSetting.id == setting_id)
    )
    if ws is None:
        raise WorldSettingNotFound(setting_id)
    return ws


async def create_world_setting(
    session: AsyncSession, payload: WorldSettingCreate, *, stage_config: StageConfig | None = None,
) -> WorldSetting:
    ws = WorldSetting(**payload.model_dump())
    session.add(ws)
    await session.flush()
    await session.refresh(ws)
    await _maybe_embed_world_setting(session, ws, stage_config=stage_config)
    await session.commit()
    await session.refresh(ws)  # re-load after embedding flush expires updated_at
    return ws


async def update_world_setting(
    session: AsyncSession, setting_id: int, payload: WorldSettingUpdate, *,
    stage_config: StageConfig | None = None,
) -> WorldSetting:
    ws = await get_world_setting(session, setting_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(ws, field, value)
    await session.flush()
    await session.refresh(ws)
    if updates.keys() & _EMBED_TRIGGER_FIELDS:
        await _maybe_embed_world_setting(session, ws, stage_config=stage_config)
    await session.commit()
    await session.refresh(ws)  # re-load after embedding flush expires updated_at
    return ws


async def update_world_setting_embedding(
    session: AsyncSession, setting_id: int, embedding: list[float]
) -> None:
    ws = await get_world_setting(session, setting_id)
    ws.embedding = list(embedding)
    await session.flush()


async def delete_world_setting(session: AsyncSession, setting_id: int) -> None:
    ws = await get_world_setting(session, setting_id)
    await session.delete(ws)
    await session.commit()
