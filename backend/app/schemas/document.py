"""Pydantic schemas for Document CRUD.

List endpoint returns DocumentListItem (no content) to avoid transferring
N full documents. Single GET returns DocumentRead with full content.

A document is also a "work" (作品): doc_type / category / metadata_json
(writing settings) / status (soft delete) / cover_url / word_count are
carried through the API surface.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Allowed work types and categories. Kept loose (no enum enforcement) so
# future types can be added without a migration; the frontend defines the
# canonical Tab set.
DOC_TYPES = {"novel", "short", "script", "video", "generic"}
CATEGORIES = {"", "长篇", "短篇", "剧本", "视频"}
STATUS_ACTIVE = "active"
STATUS_DELETED = "deleted"


class DocumentBase(BaseModel):
    """Shared fields for create/update payloads."""

    title: str = Field(..., min_length=1, max_length=500)
    content_html: str = Field(default="", max_length=1_000_000)
    content_text: str = Field(default="", max_length=1_000_000)


class DocumentCreate(DocumentBase):
    """POST /v1/documents body."""

    doc_type: str = Field(default="novel", max_length=32)
    category: str = Field(default="", max_length=32)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    cover_url: str = Field(default="", max_length=500)


class DocumentUpdate(BaseModel):
    """PATCH /v1/documents/{id} body. All fields optional for partial update."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    content_html: str | None = Field(default=None, max_length=1_000_000)
    content_text: str | None = Field(default=None, max_length=1_000_000)
    doc_type: str | None = Field(default=None, max_length=32)
    category: str | None = Field(default=None, max_length=32)
    metadata_json: dict[str, Any] | None = None
    cover_url: str | None = Field(default=None, max_length=500)
    # word_count is derived from content_text on update; not directly settable.


class DocumentPatch(DocumentUpdate):
    """PATCH body plus a merge hint. When ``merge_metadata`` is true, the
    service PATCH-merges ``metadata_json`` into the current value instead of
    replacing it — used by the editor save / Creative Kit flows so concurrent
    writes never clobber unrelated keys like ``outline``."""

    merge_metadata: bool = False


class DocumentRead(BaseModel):
    """Full document returned by GET one / POST / PATCH."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content_html: str
    content_text: str
    version: int
    doc_type: str
    category: str
    metadata_json: dict[str, Any]
    status: str
    cover_url: str
    word_count: int
    created_at: datetime
    updated_at: datetime


class DocumentListItem(BaseModel):
    """Lighter shape for list endpoint — omits content_html/content_text."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    version: int
    doc_type: str
    category: str
    status: str
    cover_url: str
    word_count: int
    updated_at: datetime


class DocumentListResponse(BaseModel):
    """Envelope for paginated list response."""

    items: list[DocumentListItem]
    total: int


class ChapterReorderItem(BaseModel):
    """One entry of a chapter reorder payload."""

    id: int
    chapter_index: int = Field(..., ge=0)


class ChapterReorderRequest(BaseModel):
    """PUT /v1/documents/{id}/chapters/reorder body."""

    chapters: list[ChapterReorderItem]
