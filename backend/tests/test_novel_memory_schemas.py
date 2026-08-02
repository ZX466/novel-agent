"""Pydantic schema validation tests for the novel-memory domain.

Pure data validation, no DB / no LLM. Exercises field constraints,
default values, partial-update semantics, and `from_attributes` ORM
projection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.novel_memory import (
    ChapterCreate,
    ChapterListItem,
    ChapterRead,
    ChapterUpdate,
    CharacterCreate,
    CharacterListItem,
    CharacterRead,
    CharacterUpdate,
    PlotEventCreate,
    PlotEventListItem,
    PlotEventRead,
    PlotEventUpdate,
    RetrievalHit,
    WorldSettingCreate,
    WorldSettingListItem,
    WorldSettingRead,
    WorldSettingUpdate,
)


# --- Chapter -----------------------------------------------------------------


def test_chapter_create_minimal_uses_defaults():
    c = ChapterCreate(chapter_index=1, title="Ch1")
    assert c.novel_id == 0
    assert c.content_text == ""
    assert c.summary == ""
    assert c.word_count == 0
    assert c.status == "draft"
    assert c.metadata_json == {}


def test_chapter_create_rejects_missing_title():
    with pytest.raises(ValidationError):
        ChapterCreate(chapter_index=1)


def test_chapter_create_rejects_negative_chapter_index():
    with pytest.raises(ValidationError):
        ChapterCreate(chapter_index=-1, title="x")


def test_chapter_create_rejects_negative_word_count():
    with pytest.raises(ValidationError):
        ChapterCreate(chapter_index=0, title="x", word_count=-1)


def test_chapter_update_partial_only_sent_fields():
    u = ChapterUpdate(title="new")
    assert u.model_dump(exclude_unset=True) == {"title": "new"}


def test_chapter_update_all_none_allowed():
    u = ChapterUpdate()
    assert u.model_dump(exclude_unset=True) == {}


def test_chapter_read_from_attributes_orm_like():
    orm = SimpleNamespace(
        id=1, novel_id=0, chapter_index=1, title="Ch1",
        content_text="abc", summary="s", word_count=3,
        status="draft", metadata_json={"k": "v"},
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    r = ChapterRead.model_validate(orm, from_attributes=True)
    assert r.id == 1
    assert r.metadata_json == {"k": "v"}


def test_chapter_list_item_includes_content_text():
    """ChapterListItem carries content_text (editor renders it on selection)
    but still omits the heavier `summary` / `embedding` fields."""
    orm = SimpleNamespace(
        id=1, chapter_index=1, title="Ch1", status="draft",
        content_text="body text", summary="s", embedding=[0.1, 0.2],
        word_count=0, updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    item = ChapterListItem.model_validate(orm, from_attributes=True)
    assert item.content_text == "body text"
    assert not hasattr(item, "summary")
    assert not hasattr(item, "embedding")


# --- Character ---------------------------------------------------------------


def test_character_create_defaults_role_to_peijiao():
    c = CharacterCreate(name="Alice")
    assert c.role == "配角"
    assert c.attributes == {}
    assert c.arc_summary == ""


def test_character_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        CharacterCreate(name="")


def test_character_update_partial_only_role():
    u = CharacterUpdate(role="主角")
    assert u.model_dump(exclude_unset=True) == {"role": "主角"}


def test_character_read_from_attributes():
    orm = SimpleNamespace(
        id=2, novel_id=0, name="Bob", role="反派",
        description="d", attributes={"age": 30}, arc_summary="",
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    r = CharacterRead.model_validate(orm, from_attributes=True)
    assert r.id == 2
    assert r.attributes == {"age": 30}


def test_character_list_item_omits_attributes_and_description():
    orm = SimpleNamespace(
        id=2, name="Bob", role="反派",
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    item = CharacterListItem.model_validate(orm, from_attributes=True)
    assert not hasattr(item, "attributes")
    assert not hasattr(item, "description")


# --- WorldSetting ------------------------------------------------------------


def test_world_setting_create_defaults_category_misc():
    w = WorldSettingCreate(title="魔法系统")
    assert w.category == "misc"


def test_world_setting_create_rejects_missing_title():
    with pytest.raises(ValidationError):
        WorldSettingCreate()


def test_world_setting_update_partial_only_category():
    u = WorldSettingUpdate(category="history")
    assert u.model_dump(exclude_unset=True) == {"category": "history"}


def test_world_setting_read_from_attributes():
    orm = SimpleNamespace(
        id=3, novel_id=0, category="geography",
        title="山脉", content_text="...",
        metadata_json={"region": "north"},
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    r = WorldSettingRead.model_validate(orm, from_attributes=True)
    assert r.id == 3
    assert r.metadata_json == {"region": "north"}


def test_world_setting_list_item_omits_content_text():
    orm = SimpleNamespace(
        id=3, category="geography", title="山脉",
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    item = WorldSettingListItem.model_validate(orm, from_attributes=True)
    assert not hasattr(item, "content_text")


# --- PlotEvent ---------------------------------------------------------------


def test_plot_event_create_defaults():
    p = PlotEventCreate(summary="主角发现宝剑")
    assert p.event_type == "beat"
    assert p.involved_character_ids == []
    assert p.chapter_id is None
    assert p.chapter_index is None


def test_plot_event_create_rejects_empty_summary():
    with pytest.raises(ValidationError):
        PlotEventCreate(summary="")


def test_plot_event_create_accepts_character_ids():
    p = PlotEventCreate(summary="x", involved_character_ids=[1, 2, 3])
    assert p.involved_character_ids == [1, 2, 3]


def test_plot_event_update_partial_only_event_type():
    u = PlotEventUpdate(event_type="twist")
    assert u.model_dump(exclude_unset=True) == {"event_type": "twist"}


def test_plot_event_read_from_attributes():
    orm = SimpleNamespace(
        id=4, novel_id=0, chapter_id=10, chapter_index=2,
        event_type="revelation", summary="...",
        involved_character_ids=[1, 5],
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    r = PlotEventRead.model_validate(orm, from_attributes=True)
    assert r.id == 4
    assert r.involved_character_ids == [1, 5]


def test_plot_event_list_item_omits_character_ids():
    orm = SimpleNamespace(
        id=4, chapter_index=2, event_type="revelation", summary="...",
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    item = PlotEventListItem.model_validate(orm, from_attributes=True)
    assert not hasattr(item, "involved_character_ids")


# --- RetrievalHit ------------------------------------------------------------


def test_retrieval_hit_accepts_arbitrary_payload():
    h = RetrievalHit(
        entity_type="chapter",
        entity_id=1,
        score=0.85,
        payload={"title": "Ch1", "summary": "..."},
    )
    assert h.entity_type == "chapter"
    assert 0.0 <= h.score <= 1.0


def test_retrieval_hit_rejects_missing_fields():
    with pytest.raises(ValidationError):
        RetrievalHit(entity_type="chapter")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        RetrievalHit(entity_type="chapter", entity_id=1, score=0.5)  # type: ignore[call-arg]
