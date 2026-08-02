"""Chapter ORM model.

Stores novel chapters with text content, summary, and a pgvector embedding
column for semantic retrieval (RAG over prior chapters).

`novel_id` is reserved for future multi-novel support; v1 single-novel
setup leaves it at 0 (default) for all chapters.

`status` lifecycle: draft → refined → final. Agents transition the value
as the pipeline progresses; never mutate in place — use service-layer
update that builds a new copy.
"""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Default embedding dimension. OpenAI text-embedding-3-small = 1536.
# Change via migration if a different embedding provider is used.
EMBEDDING_DIM = 1536


class Chapter(Base):
    """A novel chapter with vector embedding for semantic search."""

    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft"
    )
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
            f"<Chapter id={self.id} idx={self.chapter_index} "
            f"title={self.title!r} status={self.status}>"
        )
