"""Pydantic schemas for the character-relationship graph domain (R9-③).

Designed so the frontend graph component can render in one request (nodes +
edges) and rewire by dragging (PUT upsert) or disconnecting (DELETE). The
graph response intentionally excludes `novel_id` (scoped by the URL) and
never exposes embeddings.

`strength` is constrained 0..10 at both the Pydantic layer and the DB
check constraint; `relation_type` is trimmed and length-capped.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CharacterRelationshipBase(BaseModel):
    relation_type: str = Field(
        default="", min_length=0, max_length=64,
    )
    description: str = Field(default="", max_length=100_000)
    strength: int = Field(default=0, ge=0, le=10)
    metadata_json: dict = Field(default_factory=dict)


class CharacterRelationshipUpsert(CharacterRelationshipBase):
    """Payload for PUT /.../{subject_id}/{object_id} (upsert)."""

    pass


class CharacterRelationshipRead(CharacterRelationshipBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    novel_id: int
    subject_id: int
    object_id: int
    created_at: datetime
    updated_at: datetime


class CharacterRelationshipDelete(BaseModel):
    deleted: bool = True


# --- Graph (one-request render contract) ------------------------------------


class RelationshipGraphNode(BaseModel):
    id: int
    name: str
    role: str


class RelationshipGraphEdge(BaseModel):
    subject_id: int
    object_id: int
    relation_type: str
    description: str = ""
    strength: int = 0


class RelationshipGraph(BaseModel):
    nodes: list[RelationshipGraphNode] = Field(default_factory=list)
    edges: list[RelationshipGraphEdge] = Field(default_factory=list)


# --- Batch import (outline -> graph) ----------------------------------------


class RelationshipImportItem(BaseModel):
    subject_name: str = Field(..., min_length=1, max_length=200)
    object_name: str = Field(..., min_length=1, max_length=200)
    relation_type: str = Field(
        default="", min_length=0, max_length=64,
    )
    description: str = Field(default="", max_length=100_000)
    strength: int = Field(default=0, ge=0, le=10)


class RelationshipImportRequest(BaseModel):
    items: list[RelationshipImportItem] = Field(..., max_length=200)


class RelationshipImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
