"""Async service for the character-relationship graph (R9-③).

Implements the graph contract for relationship-tree visualization and
"drag-to-rewire" editing:

- `get_graph`: two SELECTs (characters + edges scoped by novel), merged in
  memory; nodes sorted by name asc, edges by (subject_id, object_id) stable.
- `upsert_relationship`: idempotent — one directed edge per ordered pair.
- `delete_relationship`: 404 when the edge does not exist.
- `import_relationships`: batch upsert by character name within the novel,
  returning created/updated/skipped counts.

Cross-novel edges are rejected by the database's composite FKs; this layer
translates IntegrityError into a `CharacterRelationshipNotFound`-style
client error only when the FK/constraint failure maps to an unknown role.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.character_relationship import CharacterRelationship
from app.schemas.character_relationship import (
    CharacterRelationshipUpsert,
    RelationshipGraph,
    RelationshipGraphEdge,
    RelationshipGraphNode,
    RelationshipImportRequest,
    RelationshipImportResult,
)

logger = logging.getLogger(__name__)


class CharacterRelationshipNotFound(Exception):
    """Raised when a relationship edge or referenced character is missing."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def get_graph(session: AsyncSession, *, novel_id: int) -> RelationshipGraph:
    """Return the full relationship graph for a novel (one-request render).

    Per P1-3, runs two novel-scoped queries and merges in memory. The
    response excludes novel_id (scoped by the URL) and embeddings.
    """
    char_rows = await session.execute(
        select(Character)
        .where(Character.novel_id == novel_id)
        .order_by(Character.name.asc())
    )
    chars = list(char_rows.scalars().all())

    edge_rows = await session.execute(
        select(CharacterRelationship)
        .where(CharacterRelationship.novel_id == novel_id)
        .order_by(
            CharacterRelationship.subject_id.asc(),
            CharacterRelationship.object_id.asc(),
        )
    )
    edges = list(edge_rows.scalars().all())

    nodes = [RelationshipGraphNode(id=c.id, name=c.name, role=c.role) for c in chars]
    graph_edges = [
        RelationshipGraphEdge(
            subject_id=e.subject_id,
            object_id=e.object_id,
            relation_type=e.relation_type,
            description=e.description,
            strength=e.strength,
        )
        for e in edges
    ]
    return RelationshipGraph(nodes=nodes, edges=graph_edges)


async def _ensure_same_novel_characters(
    session: AsyncSession, novel_id: int, subject_id: int, object_id: int
) -> None:
    """Verify both endpoints exist in this novel before creating/updating an edge.

    The DB composite FKs are the real guard; this gives a fast, consistent
    404 message and avoids ambiguous integrity errors.
    """
    rows = await session.execute(
        select(Character.id)
        .where(Character.novel_id == novel_id, Character.id.in_([subject_id, object_id]))
    )
    found = set(rows.scalars().all())
    if len(found) != 2:
        missing = {subject_id, object_id} - found
        raise CharacterRelationshipNotFound(
            f"character id(s) {sorted(missing)} not found in novel {novel_id}"
        )


async def upsert_relationship(
    session: AsyncSession,
    *,
    novel_id: int,
    subject_id: int,
    object_id: int,
    payload: CharacterRelationshipUpsert,
) -> tuple[CharacterRelationship, bool]:
    """Create or update the single directed edge for an ordered pair.

    Idempotent (Claude constraint): a second PUT with the same pair overwrites
    instead of duplicating, thanks to the unique (novel_id, subject_id, object_id).
    Returns (relationship, created_flag).
    """
    if subject_id == object_id:
        raise CharacterRelationshipNotFound("subject and object must differ")

    await _ensure_same_novel_characters(session, novel_id, subject_id, object_id)

    existing = await session.scalar(
        select(CharacterRelationship).where(
            CharacterRelationship.novel_id == novel_id,
            CharacterRelationship.subject_id == subject_id,
            CharacterRelationship.object_id == object_id,
        )
    )

    data = payload.model_dump()
    if existing is None:
        rel = CharacterRelationship(
            novel_id=novel_id,
            subject_id=subject_id,
            object_id=object_id,
            **data,
        )
        session.add(rel)
        await session.flush()
        await session.commit()
        await session.refresh(rel)
        return rel, True

    for field, value in data.items():
        setattr(existing, field, value)
    await session.flush()
    await session.commit()
    await session.refresh(existing)
    return existing, False


async def delete_relationship(
    session: AsyncSession,
    *,
    novel_id: int,
    subject_id: int,
    object_id: int,
) -> None:
    """Delete a single edge. 404 when it does not exist."""
    rel = await session.scalar(
        select(CharacterRelationship).where(
            CharacterRelationship.novel_id == novel_id,
            CharacterRelationship.subject_id == subject_id,
            CharacterRelationship.object_id == object_id,
        )
    )
    if rel is None:
        raise CharacterRelationshipNotFound(
            f"relationship {subject_id}->{object_id} not found in novel {novel_id}"
        )
    await session.delete(rel)
    await session.commit()


async def import_relationships(
    session: AsyncSession,
    *,
    novel_id: int,
    request: RelationshipImportRequest,
) -> RelationshipImportResult:
    """Batch upsert edges by character name within the novel.

    Unknown names are skipped (not created) and counted as skipped. Edges
    already present are updated; new ones created.
    """
    rows = await session.execute(
        select(Character).where(Character.novel_id == novel_id)
    )
    chars = list(rows.scalars().all())
    name_to_id = {c.name: c.id for c in chars}

    result = RelationshipImportResult()
    for item in request.items:
        subj = name_to_id.get(item.subject_name)
        obj = name_to_id.get(item.object_name)
        if subj is None or obj is None:
            result.skipped += 1
            continue
        if subj == obj:
            result.skipped += 1
            continue
        existing = await session.scalar(
            select(CharacterRelationship).where(
                CharacterRelationship.novel_id == novel_id,
                CharacterRelationship.subject_id == subj,
                CharacterRelationship.object_id == obj,
            )
        )
        if existing is None:
            session.add(
                CharacterRelationship(
                    novel_id=novel_id,
                    subject_id=subj,
                    object_id=obj,
                    relation_type=item.relation_type,
                    description=item.description,
                    strength=item.strength,
                )
            )
            result.created += 1
        else:
            existing.relation_type = item.relation_type
            existing.description = item.description
            existing.strength = item.strength
            result.updated += 1

    await session.commit()
    return result
