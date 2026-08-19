"""Pydantic schemas for the novel-memory domain (Chapter / Character /
WorldSetting / PlotEvent).

All Read models use `from_attributes=True` so they can be built directly
from ORM instances. Update models use partial fields for PATCH semantics.

Vector embeddings are NOT exposed via these schemas — they are an
implementation detail of the retrieval layer and must never leak through
the API surface (would balloon response size + leak model fingerprints).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ===========================================================================
# Chapter
# ===========================================================================


class ChapterBase(BaseModel):
    novel_id: int = Field(default=0, ge=0)
    chapter_index: int = Field(..., ge=0)
    title: str = Field(..., min_length=1, max_length=500)
    content_text: str = Field(default="", max_length=1_000_000)
    summary: str = Field(default="", max_length=100_000)
    word_count: int = Field(default=0, ge=0)
    status: str = Field(default="draft", max_length=32)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ChapterCreate(ChapterBase):
    pass


class ChapterUpdate(BaseModel):
    chapter_index: int | None = Field(default=None, ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    content_text: str | None = Field(default=None, max_length=1_000_000)
    summary: str | None = Field(default=None, max_length=100_000)
    word_count: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, max_length=32)
    metadata_json: dict[str, Any] | None = None


class ChapterRead(ChapterBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ChapterListItem(BaseModel):
    """Lighter list shape — omits summary and embedding but includes
    content_text so the editor can display chapter content on selection."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    chapter_index: int
    title: str
    content_text: str
    status: str
    word_count: int
    updated_at: datetime


class ChapterListResponse(BaseModel):
    items: list[ChapterListItem]
    total: int


# ===========================================================================
# Character
# ===========================================================================


class CharacterBase(BaseModel):
    novel_id: int = Field(default=0, ge=0)
    name: str = Field(..., min_length=1, max_length=200)
    role: str = Field(default="配角", max_length=64)
    description: str = Field(default="", max_length=100_000)
    attributes: dict[str, Any] = Field(default_factory=dict)
    arc_summary: str = Field(default="", max_length=100_000)


class CharacterCreate(CharacterBase):
    pass


class CharacterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=100_000)
    attributes: dict[str, Any] | None = None
    arc_summary: str | None = Field(default=None, max_length=100_000)


class CharacterRead(CharacterBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class CharacterListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: str
    updated_at: datetime


class CharacterListResponse(BaseModel):
    items: list[CharacterListItem]
    total: int


# ===========================================================================
# WorldSetting
# ===========================================================================


class WorldSettingBase(BaseModel):
    novel_id: int = Field(default=0, ge=0)
    category: str = Field(default="misc", max_length=64)
    title: str = Field(..., min_length=1, max_length=500)
    content_text: str = Field(default="", max_length=1_000_000)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class WorldSettingCreate(WorldSettingBase):
    pass


class WorldSettingUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    content_text: str | None = Field(default=None, max_length=1_000_000)
    metadata_json: dict[str, Any] | None = None


class WorldSettingRead(WorldSettingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class WorldSettingListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    title: str
    updated_at: datetime


class WorldSettingListResponse(BaseModel):
    items: list[WorldSettingListItem]
    total: int


# ===========================================================================
# PlotEvent
# ===========================================================================


class PlotEventBase(BaseModel):
    novel_id: int = Field(default=0, ge=0)
    chapter_id: int | None = Field(default=None, ge=1)
    chapter_index: int | None = Field(default=None, ge=0)
    event_type: str = Field(default="beat", max_length=64)
    summary: str = Field(..., min_length=1, max_length=100_000)
    in_world_date: str | None = Field(default=None, max_length=64)
    prev_event_id: int | None = Field(default=None, ge=1)
    involved_character_ids: list[int] = Field(default_factory=list)


class PlotEventCreate(PlotEventBase):
    pass


class PlotEventUpdate(BaseModel):
    chapter_id: int | None = Field(default=None, ge=1)
    chapter_index: int | None = Field(default=None, ge=0)
    event_type: str | None = Field(default=None, max_length=64)
    summary: str | None = Field(default=None, max_length=100_000)
    in_world_date: str | None = Field(default=None, max_length=64)
    prev_event_id: int | None = Field(default=None, ge=1)
    involved_character_ids: list[int] | None = None


class PlotEventRead(PlotEventBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class PlotEventListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chapter_index: int | None
    event_type: str
    summary: str
    updated_at: datetime


class PlotEventListResponse(BaseModel):
    items: list[PlotEventListItem]
    total: int


# ===========================================================================
# Retrieval query / result
# ===========================================================================


class RetrievalHit(BaseModel):
    """Generic retrieval result. `entity_type` indicates which collection
    the hit came from so callers can dispatch rendering.
    """

    entity_type: str = Field(..., description="chapter|character|world_setting|plot_event")
    entity_id: int
    score: float = Field(..., description="Similarity score in [0,1] (higher=better)")
    payload: dict[str, Any]
