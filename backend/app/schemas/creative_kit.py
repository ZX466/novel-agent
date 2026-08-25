"""Creative Kit batch-apply schemas (R7-2 P1).

The apply endpoint performs the whole kit write (world settings + characters
+ outline) in ONE transaction so a partial failure rolls back everything —
the frontend no longer loops per-item POST calls. Reuses the novel-memory
create shapes so payload semantics match the per-item create endpoints.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.document import DocumentRead
from app.schemas.novel_memory import CharacterCreate, WorldSettingCreate


class CreativeKitApplyRequest(BaseModel):
    """Body of POST /v1/documents/{id}/creative-kit/apply.

    ``novel_id`` on nested items is ignored server-side and forced to the
    path's doc_id; the outline PATCH-merges into document metadata_json.
    """

    world_settings: list[WorldSettingCreate] = Field(default_factory=list, max_length=20)
    characters: list[CharacterCreate] = Field(default_factory=list, max_length=20)
    outline: str = Field(default="", max_length=200_000)


class CreativeKitApplyResponse(BaseModel):
    """Outcome of one apply: created/skipped counts, whether the outline was
    applied, and the freshest document (for the caller to refresh its copy —
    prevents stale-metadata overwrites downstream)."""

    created_world_settings: int
    skipped_world_settings: int
    created_characters: int
    skipped_characters: int
    outline_applied: bool
    document: DocumentRead