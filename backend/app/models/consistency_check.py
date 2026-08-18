"""ConsistencyCheck ORM model.

Persists the outcome of a setting-consistency scan (R5-3 设定一致性哨兵):
each row answers "was the draft consistent with the character's stored
settings, and if not, which fact conflicts and what evidence supports it".

A check is scoped by `owner_key_hash` + `novel_id` (tenant + document
isolation, same posture as knowledge_docs). `chapter_id` links the check to
the draft that triggered it so the editor can one-click navigate back.

`verdict` values:
  - pass     — no numeric/attribute conflict found (evidence may exist)
  - conflict — the draft contradicts a stored setting (detail describes it)

Evidence is denormalized (type + id + snippet) so the list UI can render
context immediately and jump to the source collection row.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConsistencyCheck(Base):
    """A single setting-consistency verdict with supporting evidence."""

    __tablename__ = "consistency_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", index=True
    )
    novel_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    chapter_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    # Which entity was checked (e.g. "character").
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, default="character")
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # pass | conflict
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, default="pass")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Source collection of the supporting evidence ("chapter" | "character" |
    # "world_setting" | "plot_event" | "knowledge_doc") + row id + short text.
    evidence_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ConsistencyCheck id={self.id} novel_id={self.novel_id} "
            f"target={self.target_type}:{self.target_id} verdict={self.verdict}>"
        )