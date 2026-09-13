"""Creative Kit batch-apply service (R7-2; R10-⑦ unique-protagonist + web).

Applies a generated kit (world settings + characters + relationships +
outline) to a novel in ONE transaction:

- the document row is locked SELECT ... FOR UPDATE, serializing this apply
  against concurrent document writers that also lock (editor-save metadata
  merge, other applies) so the outline merge can never clobber a concurrent
  ``settings`` write and vice versa;
- world settings / characters are inserted with INSERT ... ON CONFLICT DO
  NOTHING under the (novel_id, title|name) unique constraints, so re-applies
  and concurrent applies are idempotent — no duplicate rows ever;
- R10-⑦: a kit's 主角 is demoted to 配角 when the novel already has one
  (kits are brainstorm material; the author's existing cast wins), and the
  proposed relationship web is resolved against the kit's own characters
  plus the novel's existing cast — unknown pairs are skipped, never
  fabricated; strength maps kit 1-5 → stored 2-10;
- the outline is PATCH-merged into ``metadata_json`` touching only the
  ``outline`` / ``outline_updated_at`` keys;
- any failure rolls the whole batch back (no partial applies).

Embeddings are deliberately NOT generated for batch-inserted rows — mirroring
the portable import path — so a large apply never blocks on embedding calls;
such rows simply aren't in the vector index until a later edit re-embeds them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.character_relationship import CharacterRelationship
from app.models.world_setting import WorldSetting
from app.schemas.creative_kit import (
    CreativeKitApplyRequest,
    CreativeKitApplyResponse,
)
from app.services.document import get_document


async def apply_creative_kit(
    session: AsyncSession,
    doc_id: int,
    payload: CreativeKitApplyRequest,
    *,
    owner_key_hash: str | None = None,
) -> CreativeKitApplyResponse:
    """Apply a creative kit atomically. Raises DocumentNotFound if missing."""
    # Lock the document row for the whole transaction: any other locked
    # writer (metadata merge under merge_metadata) waits for us, and we wait
    # for it, so the outline merge below always merges onto the freshest value.
    doc = await get_document(
        session, doc_id, owner_key_hash=owner_key_hash, lock=True,
    )

    try:
        # ── World settings: dedupe within the kit, then insert; the unique
        #    constraint (novel_id, title) silently skips existing titles.
        seen_titles: set[str] = set()
        ws_rows: list[dict] = []
        for item in payload.world_settings:
            title = item.title.strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            ws_rows.append(
                {
                    "novel_id": doc_id,
                    "category": item.category,
                    "title": title,
                    "content_text": item.content_text,
                    "metadata_json": item.metadata_json,
                }
            )
        created_ws = 0
        if ws_rows:
            result = await session.execute(
                pg_insert(WorldSetting)
                .values(ws_rows)
                .on_conflict_do_nothing(constraint="uq_world_settings_novel_title")
            )
            created_ws = int(result.rowcount or 0)

        # ── Characters: same pattern under (novel_id, name). R10-⑦: the
        #    novel's existing cast wins — if a 主角 already exists, an
        #    incoming kit 主角 is demoted to 配角 (kits brainstorm; unique
        #    protagonists are the author's call, not the generator's).
        existing_roles: dict[str, str] = {}
        rows_result = await session.execute(
            select(Character.name, Character.role).where(Character.novel_id == doc_id)
        )
        for name, role in rows_result.all():
            existing_roles[str(name)] = str(role or "")
        kit_protagonists = [i for i in payload.characters if i.role == "主角"]
        # A protagonist must be demoted only when one ALREADY exists in the
        # novel AND the kit row isn't that very protagonist. The kit's own
        # single 主角 is legitimate — it just can't collide with a stored one,
        # and a second in-kit 主角 collides with the first.
        has_stored_protagonist = any(r == "主角" for r in existing_roles.values())
        demoted = 0
        seen_names: set[str] = set()
        ch_rows: list[dict] = []
        for item in payload.characters:
            name = item.name.strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            role = item.role
            if role == "主角" and (
                # stored protagonist exists and this row isn't it, or an
                # earlier row in this same kit already claimed 主角
                (has_stored_protagonist and existing_roles.get(name) != "主角")
                or any(
                    r["role"] == "主角" and r["name"] != name for r in ch_rows
                )
            ):
                role = "配角"
                demoted += 1
            ch_rows.append(
                {
                    "novel_id": doc_id,
                    "name": name,
                    "role": role,
                    "description": item.description,
                    "attributes": item.attributes,
                    "arc_summary": item.arc_summary,
                }
            )
        created_ch = 0
        if ch_rows:
            result = await session.execute(
                pg_insert(Character)
                .values(ch_rows)
                .on_conflict_do_nothing(constraint="uq_characters_novel_name")
            )
            created_ch = int(result.rowcount or 0)
        # ── R10-⑦: relationship web. Resolve names against the novel's full
        #    cast (existing rows + this kit's inserts); unknown endpoints are
        #    skipped, never fabricated. Duplicate pairs within the kit keep
        #    the last proposal; strength maps kit 1-5 → stored 2-10.
        created_rel = 0
        skipped_rel = 0
        proposed = payload.relationships or []
        if proposed:
            cast_result = await session.execute(
                select(Character.id, Character.name).where(Character.novel_id == doc_id)
            )
            id_by_name: dict[str, int] = {
                str(name): int(cid) for cid, name in cast_result.all()
            }
            seen_pairs: set[tuple[int, int]] = set()
            rel_rows: list[dict] = []
            for rel in proposed:
                sid = id_by_name.get(rel.subject.strip())
                oid = id_by_name.get(rel.object.strip())
                if sid is None or oid is None or sid == oid:
                    continue
                if (sid, oid) in seen_pairs:
                    continue
                seen_pairs.add((sid, oid))
                rel_rows.append(
                    {
                        "novel_id": doc_id,
                        "subject_id": sid,
                        "object_id": oid,
                        "relation_type": rel.relation_type,
                        "description": "",
                        "strength": rel.strength * 2,
                    }
                )
            if rel_rows:
                result = await session.execute(
                    pg_insert(CharacterRelationship)
                    .values(rel_rows)
                    .on_conflict_do_nothing(constraint="uq_character_relationships_novel_subj_obj")
                )
                created_rel = int(result.rowcount or 0)
            skipped_rel = sum(
                1 for rel in proposed
                if id_by_name.get(rel.subject.strip()) is None
                or id_by_name.get(rel.object.strip()) is None
            )

        # ── Outline: PATCH-merge ONLY the changed keys onto the locked row,
        #    so concurrent writes to unrelated keys (settings, ...) survive.
        outline_applied = False
        if payload.outline.strip():
            merged = dict(doc.metadata_json or {})
            merged["outline"] = payload.outline
            merged["outline_updated_at"] = datetime.now(timezone.utc).isoformat()
            doc.metadata_json = merged
            doc.version = doc.version + 1
            outline_applied = True

        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(doc)

    return CreativeKitApplyResponse(
        created_world_settings=created_ws,
        skipped_world_settings=len(ws_rows) - created_ws,
        created_characters=created_ch,
        skipped_characters=len(ch_rows) - created_ch,
        created_relationships=created_rel,
        skipped_relationships=skipped_rel,
        outline_applied=outline_applied,
        document=doc,  # type: ignore[arg-type]
    )