"""Pydantic schemas for the knowledge base (F4 本地知识库).

Vector embeddings are NEVER exposed through these schemas — they are an
implementation detail of the retrieval layer (same rule as the other memory
collections). Upload responses return chunk summaries (id/order/content),
list responses return per-file summaries with chunk counts.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocChunkRead(BaseModel):
    """One stored chunk of an uploaded file."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    chunk_index: int
    content: str
    created_at: datetime


class KnowledgeDocListResponse(BaseModel):
    """Uploaded files (grouped by title) with chunk counts."""

    items: list["KnowledgeFileSummary"]
    total: int


class KnowledgeFileSummary(BaseModel):
    """One uploaded file: display title, chunk count, first-seen time."""

    title: str
    chunk_count: int
    created_at: datetime


class KnowledgeUploadResponse(BaseModel):
    """Result of an upload: the created chunks and how many were embedded."""

    items: list[KnowledgeDocChunkRead]
    total: int
    file_size_bytes: int
