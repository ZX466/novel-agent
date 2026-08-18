"""Pydantic schemas for the setting-consistency domain (R5-3).

Read models use `from_attributes=True` so they can be built directly from
`ConsistencyCheck` ORM instances. The request model requires exactly one of
`chapter_id` or `content_text` so the checker always has a draft to scan.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConsistencyCheckRequest(BaseModel):
    """Draft to scan. Provide a stored chapter_id OR raw content_text."""

    chapter_id: int | None = Field(default=None, ge=1)
    content_text: str | None = Field(default=None, max_length=1_000_000)

    @model_validator(mode="after")
    def _require_source(self) -> "ConsistencyCheckRequest":
        if self.chapter_id is None and not (self.content_text or "").strip():
            raise ValueError("需要 chapter_id 或非空 content_text")
        return self


class ConsistencyCheckItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    chapter_id: int | None
    target_type: str
    target_id: int
    target_name: str
    verdict: str
    detail: str
    evidence_type: str | None
    evidence_id: int | None
    evidence_snippet: str | None
    created_at: datetime


class ConsistencyCheckListResponse(BaseModel):
    items: list[ConsistencyCheckItem]
    total: int