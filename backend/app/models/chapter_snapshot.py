"""Chapter snapshot ORM model (R5-4 ????).

Immutable point-in-time copy of a chapter's text, created automatically
before risky editing operations (AI insert / whole-chapter replace /
export) and on manual save, so the author can compare and restore.

Scope mirrors other tenant-owned collections: owner_key_hash (tenant) +
novel_id (document) + chapter_id. No FK constraints on purpose (the
chapters table is not tenant-keyed), matching knowledge_docs/plot_events.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChapterSnapshot(Base):
    """An immutable snapshot of a chapter's text."""

    __tablename__ = "chapter_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", index=True
    )
    novel_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Trigger that created the snapshot: save|insert|replace|export|manual.
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="save")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ChapterSnapshot id={self.id} chapter={self.chapter_id} "
            f"novel={self.novel_id} reason={self.reason!r}>"
        )
