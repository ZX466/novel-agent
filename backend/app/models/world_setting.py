"""WorldSetting ORM model.

Stores world-building entries (geography, history, magic system, politics,
factions, ...) with a category tag and a pgvector embedding for semantic
retrieval ("search lore by natural-language query").

`category` is free-form String to allow runtime extension. A future
migration can add a CHECK constraint if a closed enum is desired.
"""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.chapter import EMBEDDING_DIM


class WorldSetting(Base):
    """A world-building entry (lore element)."""

    __tablename__ = "world_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, default="misc", index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
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
            f"<WorldSetting id={self.id} category={self.category!r} "
            f"title={self.title!r}>"
        )
