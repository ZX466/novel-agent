"""Portable data gateway (R6-4): NDJSON export + idempotent import.

Wire format: newline-delimited JSON. The first line is the document record
(``_type="document"``); each subsequent line is a chapter (``_type="chapter"``).
Stable chapter ids enable idempotent upserts by ``chapter_id`` and incremental
sync via the ``updated_at`` cursor (``last_sync``). "Export-once, import-anywhere."
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.document import Document
from app.schemas.document import DocumentUpdate
from app.schemas.novel_memory import ChapterCreate, ChapterUpdate
from app.services.chapter import (
    ChapterNotFound,
    create_chapter,
    get_chapter,
    get_chapter_by_index,
    update_chapter,
)
from app.services.document import get_document, update_document

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DOC_TYPE = "document"
CHAPTER_TYPE = "chapter"

# Fields carried across the gateway for each entity.
_DOC_FIELDS = ("title", "content_text", "doc_type", "category", "cover_url", "metadata_json")
_CHAPTER_FIELDS = (
    "chapter_index", "title", "content_text", "summary", "word_count", "status", "metadata_json",
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_document(doc: Document) -> dict:
    return {
        "_type": DOC_TYPE,
        "schema_version": SCHEMA_VERSION,
        "id": doc.id,
        "title": doc.title,
        "content_text": doc.content_text,
        "doc_type": doc.doc_type,
        "category": doc.category,
        "cover_url": doc.cover_url,
        "metadata_json": doc.metadata_json,
        "updated_at": _iso(doc.updated_at),
    }


def serialize_chapter(ch: Chapter) -> dict:
    return {
        "_type": CHAPTER_TYPE,
        "schema_version": SCHEMA_VERSION,
        "id": ch.id,
        "chapter_index": ch.chapter_index,
        "title": ch.title,
        "content_text": ch.content_text,
        "summary": ch.summary,
        "word_count": ch.word_count,
        "status": ch.status,
        "metadata_json": ch.metadata_json,
        "updated_at": _iso(ch.updated_at),
    }


def build_export_ndjson(doc: Document, chapters: list[Chapter], *, since: datetime | None = None) -> str:
    """Build the portable NDJSON payload.

    The document line is always emitted. Chapters whose ``updated_at`` is at or
    before ``since`` are skipped, enabling incremental sync exports.
    """
    lines = [serialize_document(doc)]
    for ch in chapters:
        if since is not None and ch.updated_at is not None and ch.updated_at <= since:
            continue
        lines.append(serialize_chapter(ch))
    return "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n"


def parse_ndjson(text: str) -> list[dict]:
    """Parse NDJSON into records, raising ``ValueError`` on a malformed line."""
    records: list[dict] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid NDJSON line: {exc}") from exc
    return records


def _parse_ts(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


@dataclass
class ImportReport:
    """Result of an idempotent import: per-state counts + the sync cursor."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    doc_updated: bool = False
    errors: list[str] = field(default_factory=list)
    last_sync: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "doc_updated": self.doc_updated,
            "last_sync": _iso(self.last_sync),
            "errors": self.errors,
        }


async def import_portable(session: AsyncSession, doc_id: int, ndjson_text: str) -> ImportReport:
    """Idempotently import an NDJSON payload into ``doc_id``.

    Chapters are upserted by ``id`` (only when the existing row belongs to this
    document, preventing cross-document tampering). Re-importing an unchanged
    record counts as ``unchanged`` with no write. The document metadata is
    synced only for fields that actually differ.
    """
    records = parse_ndjson(ndjson_text)
    report = ImportReport()

    doc_record = None
    chapter_records: list[dict] = []
    for rec in records:
        rtype = rec.get("_type")
        if rtype == DOC_TYPE:
            doc_record = rec
        elif rtype == CHAPTER_TYPE:
            chapter_records.append(rec)
        else:
            report.skipped += 1
            report.errors.append(f"unknown record type: {rtype!r}")

    # Sync document metadata (only changed fields -> idempotent).
    if doc_record:
        existing_doc = await get_document(session, doc_id)
        updates = {
            f: doc_record[f]
            for f in _DOC_FIELDS
            if f in doc_record and doc_record[f] is not None
            and getattr(existing_doc, f, None) != doc_record[f]
        }
        if updates:
            await update_document(session, doc_id, DocumentUpdate(**updates))
            report.doc_updated = True

    max_ts: datetime | None = None
    for rec in chapter_records:
        rec_id = rec.get("id")
        existing: Chapter | None = None
        # Primary key: the portable chapter id, but only when it already belongs
        # to this document (prevents cross-document tampering / wrong-target writes).
        if rec_id is not None:
            try:
                candidate = await get_chapter(session, rec_id)
            except ChapterNotFound:
                candidate = None
            if candidate is not None and candidate.novel_id == doc_id:
                existing = candidate
        # Fallback key for migration idempotency: the source DB id does not exist
        # in the target document after a cross-DB import, so match by chapter_index
        # (stable across migration) to make re-imports idempotent.
        if existing is None and rec.get("chapter_index") is not None:
            existing = await get_chapter_by_index(session, doc_id, rec["chapter_index"])

        if existing is None:
            payload = ChapterCreate(
                novel_id=doc_id,
                **{k: rec[k] for k in _CHAPTER_FIELDS if k in rec and rec[k] is not None},
            )
            await create_chapter(session, payload)
            report.created += 1
        else:
            updates = {
                k: rec[k]
                for k in _CHAPTER_FIELDS
                if k in rec and rec[k] is not None and getattr(existing, k, None) != rec[k]
            }
            if updates:
                await update_chapter(session, existing.id, ChapterUpdate(**updates))
                report.updated += 1
            else:
                report.unchanged += 1

        ts = _parse_ts(rec.get("updated_at"))
        if ts is not None and (max_ts is None or ts > max_ts):
            max_ts = ts

    report.last_sync = max_ts
    return report


async def list_full_chapters(session: AsyncSession, doc_id: int) -> list[Chapter]:
    """Return all chapters of a document as full ORM rows (incl. summary)."""
    result = await session.execute(
        select(Chapter).where(Chapter.novel_id == doc_id).order_by(Chapter.chapter_index.asc())
    )
    return list(result.scalars().all())
