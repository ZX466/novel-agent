"""Creative Kit batch-apply service (R7-2).

Applies a generated kit (world settings + characters + outline) to a novel
in ONE transaction:

- the document row is locked SELECT ... FOR UPDATE, serializing this apply
  against concurrent document writers that also lock (editor-save metadata
  merge, other applies) so the outline merge can never clobber a concurrent
  ``settings`` write and vice versa;
- world settings / characters are inserted with INSERT ... ON CONFLICT DO
  NOTHING under the (novel_id, title|name) unique constraints, so re-applies
  and concurrent applies are idempotent — no duplicate rows ever;
- the outline is PATCH-merged into ``metadata_json`` touching only the
  ``outline`` / ``outline_updated_at`` keys;
- any failure rolls the whole batch back (no partial applies).

Embeddings are deliberately NOT generated for batch-inserted rows — mirroring
the portable import path — so a large apply never blocks on embedding calls;
such rows simply aren't in the vector index until a later edit re-embeds them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
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

        # ── Characters: same pattern under (novel_id, name).
        seen_names: set[str] = set()
        ch_rows: list[dict] = []
        for item in payload.characters:
            name = item.name.strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            ch_rows.append(
                {
                    "novel_id": doc_id,
                    "name": name,
                    "role": item.role,
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
        outline_applied=outline_applied,
        document=doc,  # type: ignore[arg-type]
    )