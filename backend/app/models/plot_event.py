"""PlotEvent ORM model.

Stores discrete plot events / beats for timeline tracking. Each event
links to a chapter (optional — foreshadowing can exist before chapter
assignment) and to the characters involved.

`event_type` is free-form String: foreshadow / payoff / twist / cliffhanger /
character_death / revelation / etc.

`involved_character_ids` is a JSONB array of Character.id values. JSONB
(not relation table) keeps the schema simple for v1; a many-to-many
table can be added later if join queries become necessary.
"""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.chapter import EMBEDDING_DIM


class PlotEvent(Base):
    """A discrete plot event in the novel timeline."""

    __tablename__ = "plot_events"
    __table_args__ = (
        # Predecessor must live in the SAME novel (R6-2 P1): composite FK
        # (novel_id, prev_event_id) -> (novel_id, id) + unique target.
        UniqueConstraint("novel_id", "id", name="uq_plot_events_novel_id_id"),
        ForeignKeyConstraint(
            ["novel_id", "prev_event_id"],
            ["plot_events.novel_id", "plot_events.id"],
            name="fk_plot_events_prev_same_novel",
            ondelete="SET NULL",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    chapter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("chapters.id"), nullable=True, index=True
    )
    chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="beat", index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    in_world_date: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        comment="In-world date (free-form, e.g. YYYY-MM-DD) for the timeline",
    )
    prev_event_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="Causal predecessor event id (timeline DAG edge source, same novel)",
    )
    involved_character_ids: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
        comment="Array of Character.id values",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<PlotEvent id={self.id} type={self.event_type!r} "
            f"ch={self.chapter_index}>"
        )
