"""Knowledge-base document chunk ORM model (F4 本地知识库).

An uploaded lore/world-building file is split into ~800-character chunks;
each chunk becomes one `KnowledgeDoc` row with its own embedding so the
RAG layer can retrieve the most relevant snippet. `title` is the sanitized
source file name (the grouping key for list/delete); `chunk_index` preserves
document order.

`owner_key_hash` scopes every row to the API key that uploaded it and
`novel_id` scopes it to one work (作品) — retrieval over knowledge docs is
therefore double-bounded (tenant + novel), matching the other memory
collections.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db.base import Base


class KnowledgeDoc(Base):
    """One chunk of an uploaded knowledge-base file."""

    __tablename__ = "knowledge_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # SHA-256 fingerprint of the API key that uploaded this chunk (tenant scope).
    owner_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    # The work (document) this knowledge belongs to — required for RAG scope.
    novel_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Sanitized source file name — the list/delete grouping key.
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    # 0-based chunk order within the source file.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
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
            f"<KnowledgeDoc id={self.id} novel_id={self.novel_id} "
            f"title={self.title!r} chunk={self.chunk_index}>"
        )
