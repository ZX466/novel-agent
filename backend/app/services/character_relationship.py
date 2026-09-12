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


class CharacterRelationshipConflict(Exception):
    """Raised when a DB constraint fails at commit (e.g. concurrent import
    raced an unique key). API layer maps this to 409."""

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


# R9-④⑥ P2-2: prompt-injection serialization limits (Pi evaluation §2 —
# keep the injected relationship block light: ≤10 characters, ≤2000 chars).
_SER_MAX_CHARS = 10
_SER_MAX_TOTAL = 2000


async def serialize_relationships(
    session: AsyncSession, *, novel_id: int
) -> str:
    """Render the relationship graph as a single compact line for the
    chapter-writing system prompt (R9-④⑥ P2-2).

    Format: "- 甲（主角）：弧线…；关系：乙（师徒）、丙（宿敌）" per character,
    capped at the 10 most-connected characters and 2000 chars overall.
    Returns "" when the novel has no characters/edges (caller skips the block).
    """
    graph = await get_graph(session, novel_id=novel_id)
    if not graph.nodes:
        return ""

    id_to_node = {n.id: n for n in graph.nodes}
    # adjacency: id -> [(other_name, relation_type)]
    adj: dict[int, list[tuple[str, str]]] = {}
    for e in graph.edges:
        s, o = id_to_node.get(e.subject_id), id_to_node.get(e.object_id)
        if s is None or o is None:
            continue
        adj.setdefault(e.subject_id, []).append((o.name, e.relation_type))
        adj.setdefault(e.object_id, []).append((s.name, e.relation_type))

    # Prioritize most-connected characters (they matter most to continuity).
    ranked = sorted(
        graph.nodes,
        key=lambda n: (len(adj.get(n.id, [])), n.name),
        reverse=True,
    )[:_SER_MAX_CHARS]
    # Restore stable display order (by name) after ranking.
    ranked = sorted(ranked, key=lambda n: n.name)

    lines: list[str] = []
    total = 0
    for n in ranked:
        rels = sorted(adj.get(n.id, []))
        rel_txt = "、".join(f"{other}（{rel}）" for other, rel in rels[:4])
        line = f"- {n.name}（{n.role}）"
        if rel_txt:
            line += f"：关系 {rel_txt}"
        if total + len(line) > _SER_MAX_TOTAL:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


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

    Same-batch duplicates are merged in memory via a pending dict: the
    session uses autoflush=False (db/session.py), so rows added earlier in
    this request are NOT visible to a subsequent select — without the dict,
    a repeated (subject, object) pair would be added twice and blow up the
    unique constraint at commit (R9-③ review P1-A).
    """
    rows = await session.execute(
        select(Character).where(Character.novel_id == novel_id)
    )
    chars = list(rows.scalars().all())
    name_to_id = {c.name: c.id for c in chars}

    # (subject_id, object_id) -> (edge ORM object, is_new). Covers both
    # DB-backed edges (loaded on first sight) and pending adds within this
    # batch (subsequent duplicates merge onto the same object).
    pending: dict[tuple[int, int], tuple[CharacterRelationship, bool]] = {}

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
        key = (subj, obj)
        if key not in pending:
            existing = await session.scalar(
                select(CharacterRelationship).where(
                    CharacterRelationship.novel_id == novel_id,
                    CharacterRelationship.subject_id == subj,
                    CharacterRelationship.object_id == obj,
                )
            )
            if existing is not None:
                pending[key] = (existing, False)
            else:
                rel = CharacterRelationship(
                    novel_id=novel_id,
                    subject_id=subj,
                    object_id=obj,
                    relation_type=item.relation_type,
                    description=item.description,
                    strength=item.strength,
                )
                session.add(rel)
                pending[key] = (rel, True)
                result.created += 1
                continue
        rel, is_new = pending[key]
        rel.relation_type = item.relation_type
        rel.description = item.description
        rel.strength = item.strength
        if not is_new:
            result.updated += 1

    try:
        await session.commit()
    except IntegrityError:
        # DB-level backstop (e.g. a concurrent import raced us to the same
        # unique key): roll back and surface a mapped 409, not a raw 500.
        await session.rollback()
        raise CharacterRelationshipConflict(
            "concurrent modification detected during import"
        )
    return result
