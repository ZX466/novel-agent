"""Dashboard statistics service."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.chapter import Chapter


async def get_dashboard_stats(session: AsyncSession) -> dict:
    """Return writing dashboard statistics.

    Metrics are based on document-level ``updated_at`` and ``word_count``.
    """
    today = datetime.now(timezone.utc).date()
    thirty_days_ago = today - timedelta(days=29)

    daily_stmt = (
        select(
            cast(Document.updated_at, Date).label("day"),
            func.sum(Document.word_count).label("word_count"),
        )
        .where(
            Document.updated_at >= thirty_days_ago,
            Document.status == "active",
        )
        .group_by(cast(Document.updated_at, Date))
    )
    result = await session.execute(daily_stmt)
    daily_map = {row.day: int(row.word_count or 0) for row in result.all()}

    daily_words: list[dict] = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        daily_words.append({"date": d.isoformat(), "words": daily_map.get(d, 0)})

    today_words = daily_map.get(today, 0)
    streak_days = _compute_consecutive_days(daily_map.keys(), today)

    totals = await session.execute(
        select(
            func.count(Document.id).label("docs"),
            func.count(Chapter.id).label("chapters"),
            func.coalesce(func.sum(Document.word_count), 0).label("words"),
        )
        .select_from(Document)
        .outerjoin(Chapter, Chapter.novel_id == Document.id)
        .where(Document.status == "active")
    )
    totals_row = totals.one()
    total_documents = int(totals_row.docs or 0)
    total_chapters = int(totals_row.chapters or 0)
    total_words = int(totals_row.words or 0)

    return {
        "total_documents": total_documents,
        "total_chapters": total_chapters,
        "total_words": total_words,
        "streak_days": streak_days,
        "today_words": today_words,
        "daily_words": daily_words,
    }


def _compute_consecutive_days(update_dates: set[date], today: date) -> int:
    """Count consecutive writing days ending on ``today``."""
    if not update_dates:
        return 0

    unique = sorted(set(update_dates), reverse=True)
    expected = today
    count = 0
    for d in unique:
        if d == expected:
            count += 1
            expected -= timedelta(days=1)
        elif d < expected:
            break
    return count
