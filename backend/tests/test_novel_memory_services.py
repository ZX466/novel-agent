"""Unit tests for character / world_setting / plot_event services.

Mirrors test_chapter_service.py — exercises create / get / update / delete
happy paths + NotFound error paths using MockAsyncSession.
"""
from __future__ import annotations

import pytest

from app.models.character import Character
from app.models.plot_event import PlotEvent
from app.models.world_setting import WorldSetting
from app.schemas.novel_memory import (
    CharacterCreate,
    CharacterUpdate,
    PlotEventCreate,
    PlotEventUpdate,
    WorldSettingCreate,
    WorldSettingUpdate,
)
from app.services.character import (
    CharacterNotFound,
    create_character,
    delete_character,
    get_character,
    update_character,
    update_character_embedding,
)
from app.services.plot_event import (
    PlotEventNotFound,
    create_plot_event,
    delete_plot_event,
    get_plot_event,
    list_plot_events,
    update_plot_event,
    update_plot_event_embedding,
)
from app.services.world_setting import (
    WorldSettingNotFound,
    create_world_setting,
    delete_world_setting,
    get_world_setting,
    update_world_setting,
    update_world_setting_embedding,
)
from tests.conftest import _FakeResult


# --- Character ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_character_commits_and_refreshes(mock_session):
    payload = CharacterCreate(name="Alice", role="主角")
    c = await create_character(mock_session, payload)
    assert c.name == "Alice"
    assert mock_session.added == [c]
    assert mock_session.commits == 1
    assert mock_session.refreshes == 1


@pytest.mark.asyncio
async def test_get_character_returns_instance(mock_session):
    c = Character(id=5, name="Bob", role="反派")
    mock_session.set_scalar_results([c])
    result = await get_character(mock_session, 5)
    assert result is c


@pytest.mark.asyncio
async def test_get_character_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(CharacterNotFound):
        await get_character(mock_session, 999)


@pytest.mark.asyncio
async def test_update_character_applies_sent_fields(mock_session):
    c = Character(id=1, name="old", role="配角")
    mock_session.set_scalar_results([c])
    updated = await update_character(mock_session, 1, CharacterUpdate(role="主角"))
    assert updated.role == "主角"
    assert updated.name == "old"  # unchanged
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_update_character_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(CharacterNotFound):
        await update_character(mock_session, 1, CharacterUpdate(name="x"))


@pytest.mark.asyncio
async def test_update_character_embedding_persists(mock_session):
    c = Character(id=1, name="x")
    mock_session.set_scalar_results([c])
    vec = [0.2] * 1536
    await update_character_embedding(mock_session, 1, vec)
    assert c.embedding == vec


@pytest.mark.asyncio
async def test_delete_character_calls_session_delete(mock_session):
    c = Character(id=1, name="x")
    mock_session.set_scalar_results([c])
    await delete_character(mock_session, 1)
    assert mock_session.deleted == [c]


@pytest.mark.asyncio
async def test_delete_character_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(CharacterNotFound):
        await delete_character(mock_session, 1)


# --- WorldSetting ------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_world_setting_commits(mock_session):
    payload = WorldSettingCreate(title="魔法系统", category="magic")
    ws = await create_world_setting(mock_session, payload)
    assert ws.title == "魔法系统"
    assert ws.category == "magic"
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_get_world_setting_returns_instance(mock_session):
    ws = WorldSetting(id=3, title="x", category="misc")
    mock_session.set_scalar_results([ws])
    result = await get_world_setting(mock_session, 3)
    assert result is ws


@pytest.mark.asyncio
async def test_get_world_setting_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(WorldSettingNotFound):
        await get_world_setting(mock_session, 999)


@pytest.mark.asyncio
async def test_update_world_setting_applies_sent_fields(mock_session):
    ws = WorldSetting(id=1, title="old", category="misc")
    mock_session.set_scalar_results([ws])
    updated = await update_world_setting(
        mock_session, 1, WorldSettingUpdate(category="history")
    )
    assert updated.category == "history"
    assert updated.title == "old"


@pytest.mark.asyncio
async def test_update_world_setting_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(WorldSettingNotFound):
        await update_world_setting(mock_session, 1, WorldSettingUpdate(title="x"))


@pytest.mark.asyncio
async def test_update_world_setting_embedding_persists(mock_session):
    ws = WorldSetting(id=1, title="x")
    mock_session.set_scalar_results([ws])
    vec = [0.3] * 1536
    await update_world_setting_embedding(mock_session, 1, vec)
    assert ws.embedding == vec


@pytest.mark.asyncio
async def test_delete_world_setting_calls_session_delete(mock_session):
    ws = WorldSetting(id=1, title="x")
    mock_session.set_scalar_results([ws])
    await delete_world_setting(mock_session, 1)
    assert mock_session.deleted == [ws]


@pytest.mark.asyncio
async def test_delete_world_setting_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(WorldSettingNotFound):
        await delete_world_setting(mock_session, 1)


# --- PlotEvent ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_plot_event_commits(mock_session):
    payload = PlotEventCreate(summary="主角发现宝剑", event_type="revelation")
    pe = await create_plot_event(mock_session, payload)
    assert pe.summary == "主角发现宝剑"
    assert pe.event_type == "revelation"
    assert pe.involved_character_ids == []
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_get_plot_event_returns_instance(mock_session):
    pe = PlotEvent(id=4, summary="x")
    mock_session.set_scalar_results([pe])
    result = await get_plot_event(mock_session, 4)
    assert result is pe


@pytest.mark.asyncio
async def test_get_plot_event_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(PlotEventNotFound):
        await get_plot_event(mock_session, 999)


@pytest.mark.asyncio
async def test_update_plot_event_applies_sent_fields(mock_session):
    pe = PlotEvent(id=1, summary="old", event_type="beat")
    mock_session.set_scalar_results([pe])
    updated = await update_plot_event(
        mock_session, 1, PlotEventUpdate(event_type="twist")
    )
    assert updated.event_type == "twist"
    assert updated.summary == "old"


@pytest.mark.asyncio
async def test_update_plot_event_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(PlotEventNotFound):
        await update_plot_event(mock_session, 1, PlotEventUpdate(summary="x"))


@pytest.mark.asyncio
async def test_update_plot_event_embedding_persists(mock_session):
    pe = PlotEvent(id=1, summary="x")
    mock_session.set_scalar_results([pe])
    vec = [0.4] * 1536
    await update_plot_event_embedding(mock_session, 1, vec)
    assert pe.embedding == vec


@pytest.mark.asyncio
async def test_delete_plot_event_calls_session_delete(mock_session):
    pe = PlotEvent(id=1, summary="x")
    mock_session.set_scalar_results([pe])
    await delete_plot_event(mock_session, 1)
    assert mock_session.deleted == [pe]


@pytest.mark.asyncio
async def test_delete_plot_event_raises_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(PlotEventNotFound):
        await delete_plot_event(mock_session, 1)


@pytest.mark.asyncio
async def test_list_plot_events_filters(mock_session):
    """All four filters (novel_id, chapter_id, chapter_index, event_type)
    must be accepted without raising."""
    mock_session.set_execute_results([_FakeResult(scalars=[])])
    mock_session.set_scalar_results([0])
    items, total = await list_plot_events(
        mock_session,
        novel_id=1,
        chapter_id=2,
        chapter_index=3,
        event_type="twist",
    )
    assert items == []
    assert total == 0
