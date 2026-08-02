"""Async CRUD for Evaluation records.

Mirrors the chapter.py / document.py service contract: mutating
functions flush + commit + refresh. Evaluations are append-only — there
is no update path; each evaluation point writes a new row so the history
is preserved for trend analysis.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import Evaluation


async def create_evaluation(
    session: AsyncSession,
    *,
    novel_id: int,
    stage: str,
    score: float,
    feedback: str = "",
    chapter_id: int | None = None,
    source: str = "",
) -> Evaluation:
    """Append a new evaluation record. Commits immediately.

    `score` is clamped to [0.0, 1.0] here so callers (agents / pipeline
    nodes) don't each have to repeat the clamp.
    """
    clamped = max(0.0, min(1.0, float(score)))
    ev = Evaluation(
        novel_id=novel_id,
        chapter_id=chapter_id,
        stage=stage,
        score=clamped,
        feedback=feedback,
        source=source,
    )
    session.add(ev)
    await session.flush()
    await session.commit()
    await session.refresh(ev)
    return ev


async def list_evaluations(
    session: AsyncSession,
    *,
    novel_id: int | None = None,
    chapter_id: int | None = None,
    stage: str | None = None,
    limit: int = 200,
) -> list[Evaluation]:
    """Returns evaluations ordered newest-first for trend analysis.

    Any of novel_id / chapter_id / stage may be omitted to broaden the
    query. Defaults to the most recent 200 rows.
    """
    stmt = select(Evaluation).order_by(Evaluation.created_at.desc())
    if novel_id is not None:
        stmt = stmt.where(Evaluation.novel_id == novel_id)
    if chapter_id is not None:
        stmt = stmt.where(Evaluation.chapter_id == chapter_id)
    if stage is not None:
        stmt = stmt.where(Evaluation.stage == stage)
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
