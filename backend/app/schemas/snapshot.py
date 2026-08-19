"""Pydantic schemas for chapter snapshots (R5-4 ????)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Canonical auto-snapshot triggers. Kept loose (not an enum) so future
# callers can add reasons without an API change.
SNAPSHOT_REASONS = ("save", "insert", "replace", "export", "manual")


class SnapshotCreate(BaseModel):
    """POST body: the text to snapshot (current editor content)."""

    content_text: str = Field(..., max_length=1_000_000)
    title: str | None = Field(default=None, max_length=500)
    reason: str = Field(default="save", max_length=32)


class SnapshotRead(BaseModel):
    """Snapshot metadata + content.

    Content is included so the history panel can preview/compare without
    a second round-trip; snapshots are tenant-scoped so this only leaks
    the caller's own drafts.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    chapter_id: int
    title: str
    content_text: str
    word_count: int
    reason: str
    created_at: datetime


class SnapshotListResponse(BaseModel):
    """Newest-first page of snapshots for one chapter."""

    items: list[SnapshotRead]
    total: int
