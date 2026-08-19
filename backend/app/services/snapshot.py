"""Async CRUD + restore service for ChapterSnapshot (R5-4 ????).

Snapshots are immutable point-in-time copies, scoped by owner_key_hash
(tenant) + novel_id (document) + chapter_id. The per-chapter cap
(MAX_SNAPSHOTS) drops the oldest rows once exceeded so the table can't
grow unboundedly from auto-snapshots.
"""
from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.chapter_snapshot import ChapterSnapshot
from app.schemas.novel_memory import ChapterUpdate
from app.services.chapter import ChapterNotFound, get_chapter, update_chapter

# Keep at most this many snapshots per chapter (matches the old
# localStorage cap). Oldest rows are dropped on create.
MAX_SNAPSHOTS = 50


class SnapshotNotFound(Exception):
    """Raised when a snapshot id does not exist or is out of scope."""

    def __init__(self, snapshot_id: int) -> None:
        super().__init__(f"Snapshot id={snapshot_id} not found")
        self.snapshot_id = snapshot_id


async def create_snapshot(
    session: AsyncSession,
    *,
    owner_key_hash: str,
    novel_id: int,
    chapter_id: int,
    content_text: str,
    title: str = "",
    reason: str = "save",
) -> ChapterSnapshot:
    """Persist a new snapshot and trim the per-chapter cap. Commits."""
    snap = ChapterSnapshot(
        owner_key_hash=owner_key_hash,
        novel_id=novel_id,
        chapter_id=chapter_id,
        title=title or "",
        content_text=content_text or "",
        word_count=len(content_text or ""),
        reason=reason or "save",
    )
    session.add(snap)
    await session.flush()
    # Drop the oldest rows beyond the cap (same owner + novel + chapter).
    excess = (
        await session.execute(
            select(ChapterSnapshot.id)
            .where(
                ChapterSnapshot.owner_key_hash == owner_key_hash,
                ChapterSnapshot.novel_id == novel_id,
                ChapterSnapshot.chapter_id == chapter_id,
            )
            .order_by(
                ChapterSnapshot.created_at.asc(), ChapterSnapshot.id.asc()
            )
            .offset(MAX_SNAPSHOTS)
        )
    ).scalars().all()
    if excess:
        await session.execute(
            sa_delete(ChapterSnapshot).where(
                ChapterSnapshot.id.in_(list(excess))
            )
        )
    await session.commit()
    await session.refresh(snap)
    return snap


async def list_snapshots(
    session: AsyncSession,
    *,
    owner_key_hash: str,
    novel_id: int,
    chapter_id: int,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ChapterSnapshot], int]:
    """Return (items, total) for one chapter, newest-first."""
    where = (
        ChapterSnapshot.owner_key_hash == owner_key_hash,
        ChapterSnapshot.novel_id == novel_id,
        ChapterSnapshot.chapter_id == chapter_id,
    )
    total = await session.scalar(
        select(func.count(ChapterSnapshot.id)).where(*where)
    )
    result = await session.execute(
        select(ChapterSnapshot)
        .where(*where)
        .order_by(
            ChapterSnapshot.created_at.desc(), ChapterSnapshot.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_snapshot(
    session: AsyncSession, snapshot_id: int, *, owner_key_hash: str
) -> ChapterSnapshot:
    """Return the snapshot or raise SnapshotNotFound (owner-scoped)."""
    snap = await session.scalar(
        select(ChapterSnapshot).where(
            ChapterSnapshot.id == snapshot_id,
            ChapterSnapshot.owner_key_hash == owner_key_hash,
        )
    )
    if snap is None:
        raise SnapshotNotFound(snapshot_id)
    return snap


async def delete_snapshot(
    session: AsyncSession, snapshot_id: int, *, owner_key_hash: str
) -> None:
    """Delete a snapshot (owner-scoped). Commits."""
    snap = await get_snapshot(session, snapshot_id, owner_key_hash=owner_key_hash)
    await session.delete(snap)
    await session.commit()


async def restore_snapshot(
    session: AsyncSession,
    *,
    snapshot_id: int,
    owner_key_hash: str,
    novel_id: int,
    chapter_id: int,
) -> Chapter:
    """Copy a snapshot's text back onto its chapter.

    Verifies the snapshot belongs to (novel, chapter) and the chapter
    belongs to the novel before writing; reuses update_chapter so
    word_count and best-effort embedding stay consistent.
    """
    snap = await get_snapshot(session, snapshot_id, owner_key_hash=owner_key_hash)
    if snap.novel_id != novel_id or snap.chapter_id != chapter_id:
        raise SnapshotNotFound(snapshot_id)
    try:
        ch = await get_chapter(session, chapter_id)
    except ChapterNotFound:
        raise ChapterNotFound(chapter_id)
    if ch.novel_id != novel_id:
        raise ChapterNotFound(chapter_id)
    updated = await update_chapter(
        session, chapter_id, ChapterUpdate(content_text=snap.content_text)
    )
    return updated
