"""CharacterRelationship ORM model.

Stores a directed edge between two characters within a novel, used for
relationship-tree visualization and "drag-to-rewire" editing. Scoped by
novel_id (the parent document id) like every other novel-memory entity.

`relation_type` is a free-form label (师徒 / 恋人 / 宿敌 / ...) kept as
String to allow runtime extension without a migration.

Cross-novel edges are rejected at the database layer via two composite
foreign keys (novel_id, subject_id) and (novel_id, object_id) pointing at
characters(novel_id, id), mirroring the plot_events predecessor precedent.
Deleting a character cascades to its incident edges (R9-③ P1-1).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
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


class CharacterRelationship(Base):
    """A directed character relationship within a novel."""

    __tablename__ = "character_relationships"
    __table_args__ = (
        # One directed edge per ordered pair — "drag to rewire" overwrites.
        UniqueConstraint(
            "novel_id", "subject_id", "object_id",
            name="uq_character_relationships_novel_subj_obj",
        ),
        # No self-loops.
        CheckConstraint(
            "subject_id <> object_id",
            name="ck_character_relationships_no_self_loop",
        ),
        # strength in 0..10.
        CheckConstraint(
            "strength >= 0 AND strength <= 10",
            name="ck_character_relationships_strength_range",
        ),
        # Cross-novel edges rejected at DB layer: composite FKs point at
        # characters(novel_id, id); ondelete CASCADE removes incident edges.
        ForeignKeyConstraint(
            ["novel_id", "subject_id"],
            ["characters.novel_id", "characters.id"],
            name="fk_character_relationships_subject_same_novel",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["novel_id", "object_id"],
            ["characters.novel_id", "characters.id"],
            name="fk_character_relationships_object_same_novel",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    object_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Reserved for future extensibility",
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
            f"<CharacterRelationship id={self.id} "
            f"{self.subject_id}->{self.object_id} {self.relation_type!r}>"
        )
