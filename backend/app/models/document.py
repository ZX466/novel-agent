"""Editor document ORM model.

Stores Tiptap HTML (canonical) and plain text (for future search/RAG).
The `version` column is a zero-cost placeholder for future optimistic
concurrency control; v1 uses last-write-wins.

Replaces the skeleton pgvector demo model. The RAG slice can add an
`embedding` column back via a later Alembic migration.

A document doubles as a "work" (作品) record in the novel-management
surface (蛙蛙写作-style): `doc_type`/`category` classify it, `metadata_json`
holds writing settings (writing_type / pov / genre / target_audience),
`status` implements soft-delete (active|deleted), and `word_count` is a
cached counter for list-card display so the list endpoint never loads
full content.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Soft-delete status constants
STATUS_ACTIVE = "active"
STATUS_DELETED = "deleted"


class Document(Base):
    """A Tiptap editor document."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # Work classification. `doc_type` (not `type`) to avoid shadowing the
    # Python builtin; exposed as the `type` query param at the API layer.
    doc_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="novel", server_default="novel"
    )
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="", server_default=""
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Soft-delete lifecycle: active (default) | deleted (回收站可恢复).
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    cover_url: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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
            f"<Document id={self.id} title={self.title!r} "
            f"type={self.doc_type} status={self.status} version={self.version}>"
        )
