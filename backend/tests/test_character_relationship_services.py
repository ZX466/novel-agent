"""Service tests for the character-relationship graph (R9-③).

Mirrors test_novel_memory_services.py — exercises graph / upsert / delete /
import happy paths + NotFound error paths using MockAsyncSession.
"""
from __future__ import annotations

import pytest

from app.models.character import Character
from app.models.character_relationship import CharacterRelationship
from app.schemas.character_relationship import (
    CharacterRelationshipUpsert,
    RelationshipImportItem,
    RelationshipImportRequest,
)
from app.services.character_relationship import (
    CharacterRelationshipNotFound,
    delete_relationship,
    get_graph,
    import_relationships,
    upsert_relationship,
)
from tests.conftest import _FakeResult


def _char(pid: int, name: str, role: str = "配角") -> Character:
    c = Character(id=pid, novel_id=1, name=name, role=role)
    return c


def _rel(subj: int, obj: int, rel_type: str = "师徒", strength: int = 3) -> CharacterRelationship:
    return CharacterRelationship(
        id=subj * 100 + obj,
        novel_id=1,
        subject_id=subj,
        object_id=obj,
        relation_type=rel_type,
        description="",
        strength=strength,
    )


# --- get_graph --------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_graph_merges_and_sorts(mock_session):
    # DB returns characters ordered by name asc -> ids [1(甲), 2(乙), 3(丙)]
    chars = [_char(1, "甲"), _char(2, "乙"), _char(3, "丙")]
    edges = [
        _rel(1, 2, "师徒", 5),
        _rel(3, 1, "恋人", 8),
    ]
    mock_session.set_execute_results([
        _FakeResult(scalars=chars),   # characters (already ordered by name)
        _FakeResult(scalars=edges),   # edges (already ordered)
    ])
    graph = await get_graph(mock_session, novel_id=1)
    # nodes sorted by name asc
    assert [n.id for n in graph.nodes] == [1, 2, 3]
    assert [n.name for n in graph.nodes] == ["甲", "乙", "丙"]
    # edges preserved in (subject_id, object_id) order
    assert [(e.subject_id, e.object_id) for e in graph.edges] == [(1, 2), (3, 1)]
    # response excludes novel_id / embeddings
    edge = graph.edges[0]
    assert not hasattr(edge, "novel_id")
    assert edge.relation_type == "师徒" and edge.strength == 5


@pytest.mark.asyncio
async def test_get_graph_empty_novel(mock_session):
    mock_session.set_execute_results([
        _FakeResult(scalars=[]),
        _FakeResult(scalars=[]),
    ])
    graph = await get_graph(mock_session, novel_id=9)
    assert graph.nodes == []
    assert graph.edges == []


# --- upsert_relationship ----------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_creates_edge(mock_session):
    # _ensure_same_novel_characters (execute) -> both ids exist; then scalar(existing) -> None
    mock_session.set_execute_results([
        _FakeResult(scalars=[1, 2]),
    ])
    mock_session.set_scalar_results([None])
    payload = CharacterRelationshipUpsert(relation_type="师徒", strength=4)
    rel, created = await upsert_relationship(
        mock_session, novel_id=1, subject_id=1, object_id=2, payload=payload
    )
    assert created is True
    assert rel.subject_id == 1 and rel.object_id == 2
    assert mock_session.commits == 1
    assert len(mock_session.added) == 1


@pytest.mark.asyncio
async def test_upsert_updates_existing_edge(mock_session):
    mock_session.set_execute_results([_FakeResult(scalars=[1, 2])])
    existing = _rel(1, 2, "师徒", 3)
    mock_session.set_scalar_results([existing])
    payload = CharacterRelationshipUpsert(relation_type="恋人", strength=9)
    rel, created = await upsert_relationship(
        mock_session, novel_id=1, subject_id=1, object_id=2, payload=payload
    )
    assert created is False
    assert existing.relation_type == "恋人"
    assert existing.strength == 9
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_upsert_self_loop_rejected(mock_session):
    with pytest.raises(CharacterRelationshipNotFound):
        await upsert_relationship(
            mock_session, novel_id=1, subject_id=1, object_id=1,
            payload=CharacterRelationshipUpsert(relation_type="自己"),
        )
    assert mock_session.commits == 0


@pytest.mark.asyncio
async def test_upsert_missing_character_rejected(mock_session):
    # only id=1 found, id=2 missing -> raise
    mock_session.set_execute_results([_FakeResult(scalars=[1])])
    with pytest.raises(CharacterRelationshipNotFound):
        await upsert_relationship(
            mock_session, novel_id=1, subject_id=1, object_id=2,
            payload=CharacterRelationshipUpsert(relation_type="师徒"),
        )


# --- delete_relationship ----------------------------------------------------


@pytest.mark.asyncio
async def test_delete_relationship_calls_delete(mock_session):
    rel = _rel(1, 2)
    mock_session.set_scalar_results([rel])
    await delete_relationship(mock_session, novel_id=1, subject_id=1, object_id=2)
    assert rel in mock_session.deleted
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_delete_relationship_not_found(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(CharacterRelationshipNotFound):
        await delete_relationship(mock_session, novel_id=1, subject_id=1, object_id=2)
    assert mock_session.commits == 0


# --- import_relationships ---------------------------------------------------


@pytest.mark.asyncio
async def test_import_counts_created_updated_skipped(mock_session):
    chars = [_char(1, "甲"), _char(2, "乙"), _char(3, "丙")]
    mock_session.set_execute_results([_FakeResult(scalars=chars)])
    # scalar(existing) -> None for both new edges
    mock_session.set_scalar_results([None, None])
    request = RelationshipImportRequest(items=[
        RelationshipImportItem(subject_name="甲", object_name="乙", relation_type="师徒"),
        RelationshipImportItem(subject_name="乙", object_name="丙", relation_type="朋友"),
        RelationshipImportItem(subject_name="甲", object_name="不存在", relation_type="X"),
        RelationshipImportItem(subject_name="甲", object_name="甲", relation_type="自环"),
    ])
    result = await import_relationships(mock_session, novel_id=1, request=request)
    assert result.created == 2
    assert result.updated == 0
    assert result.skipped == 2
    assert mock_session.commits == 1


@pytest.mark.asyncio
async def test_import_updates_existing(mock_session):
    chars = [_char(1, "甲"), _char(2, "乙")]
    mock_session.set_execute_results([_FakeResult(scalars=chars)])
    existing = _rel(1, 2, "师徒", 3)
    mock_session.set_scalar_results([existing])
    request = RelationshipImportRequest(items=[
        RelationshipImportItem(subject_name="甲", object_name="乙", relation_type="恋人", strength=9),
    ])
    result = await import_relationships(mock_session, novel_id=1, request=request)
    assert result.created == 0
    assert result.updated == 1
    assert existing.relation_type == "恋人"
    assert existing.strength == 9
