"""Async CRUD service for Document.

Each mutating function flushes (to populate auto-id without expiring ORM
state), commits, and refreshes. Read functions do not commit.

Raises DocumentNotFound for missing IDs; the API layer translates this to
HTTP 404.

list_documents supports the蛙蛙写作-style work filters: doc_type,
category, title search, soft-delete status, and pagination. DELETE is a
soft delete (status='deleted'); restore flips it back; permanent_delete
drops the row.

word_count is recomputed from content_text on every content change so the
list-card counter stays accurate without a separate aggregation pass.
"""
from __future__ import annotations

import re

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, STATUS_ACTIVE, STATUS_DELETED
from app.schemas.document import DocumentCreate, DocumentUpdate

_ALLOWED_HTML_TAGS = {
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "img", "li", "ol", "p", "pre", "s",
    "span", "strong", "sub", "sup", "table", "tbody", "td", "th",
    "thead", "tr", "u", "ul",
}
_ALLOWED_HTML_ATTRIBUTES = {
    "a": {"href", "target", "title"},
    "img": {"alt", "height", "src", "title", "width"},
    "span": {"class"},
    "table": {"class"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}


def sanitize_content_html(content_html: str) -> str:
    """Persist only safe rich-text markup; remove scripts, handlers and unsafe URLs."""
    import nh3

    return nh3.clean(
        content_html,
        tags=_ALLOWED_HTML_TAGS,
        attributes=_ALLOWED_HTML_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
    )


_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def _compute_word_count(text: str) -> int:
    """CJK + Latin mixed word count.

    Chinese characters count as one word each; Latin runs split on
    whitespace. Matches the frontend EditorStats logic so the number the
    user sees while typing equals the number persisted.
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    latin = _CJK_RE.sub(" ", text)
    latin_words = len(latin.split()) if latin.strip() else 0
    return cjk + latin_words


def _common_prefix_suffix_len(a: str, b: str) -> tuple[int, int]:
    """Return (prefix_len, suffix_len) of common chars between a and b.

    Suffix counting starts after the common prefix so overlapping
    prefix/suffix regions are not double-counted.
    """
    max_pre = min(len(a), len(b))
    pre = 0
    while pre < max_pre and a[pre] == b[pre]:
        pre += 1
    max_suf = min(len(a), len(b)) - pre
    suf = 0
    while suf < max_suf and a[len(a) - 1 - suf] == b[len(b) - 1 - suf]:
        suf += 1
    return pre, suf


def _compute_word_count_incremental(old_text: str, new_text: str, old_count: int) -> int:
    """Incremental word count for large-document edits.

    DocLite: for >100KB documents a full-text regex pass on every save is
    O(n). Instead, find the unchanged common prefix/suffix and run the
    counters only over the changed middle segment:

        new_count = old_count + count(changed_middle_new) - count(changed_middle_old)

    Equivalent to `_compute_word_count(new_text)` (guaranteed by
    tests/test_document_wordcount.py::test_incremental_matches_full) while
    touching only the edited region.
    """
    if old_text == new_text:
        return old_count
    if not old_text:
        return _compute_word_count(new_text)
    if not new_text:
        return 0

    pre, suf = _common_prefix_suffix_len(old_text, new_text)
    old_mid = old_text[pre : len(old_text) - suf if suf else len(old_text)]
    new_mid = new_text[pre : len(new_text) - suf if suf else len(new_text)]
    return old_count + _compute_word_count(new_mid) - _compute_word_count(old_mid)


class DocumentNotFound(Exception):
    """Raised when a document ID does not exist in the database."""

    def __init__(self, doc_id: int) -> None:
        super().__init__(f"Document id={doc_id} not found")
        self.doc_id = doc_id


async def list_documents(
    session: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
    doc_type: str | None = None,
    category: str | None = None,
    search: str | None = None,
    status: str | None = None,
    owner_key_hash: str | None = None,
) -> tuple[list[Document], int]:
    """Returns (items, total_count) ordered by most-recently-updated first.

    Filters (all optional, AND-combined):
        doc_type — work type (novel/short/script/video/...)
        category — 长篇/短篇/剧本/视频
        search   — case-insensitive LIKE on title
        status   — 'active' (default for list) / 'deleted' (回收站) / None (all)
    """
    effective_status = status or STATUS_ACTIVE

    conditions = []
    if owner_key_hash is not None:
        conditions.append(Document.owner_key_hash == owner_key_hash)
    if doc_type:
        conditions.append(Document.doc_type == doc_type)
    if category:
        conditions.append(Document.category == category)
    if search:
        conditions.append(Document.title.ilike(f"%{search}%"))
    conditions.append(Document.status == effective_status)

    where = and_(*conditions) if conditions else None

    total_stmt = select(func.count(Document.id))
    list_stmt = select(Document).order_by(Document.updated_at.desc())
    if where is not None:
        total_stmt = total_stmt.where(where)
        list_stmt = list_stmt.where(where)
    total = await session.scalar(total_stmt)
    list_stmt = list_stmt.limit(limit).offset(offset)
    result = await session.execute(list_stmt)
    return list(result.scalars().all()), int(total or 0)


async def get_document(
    session: AsyncSession, doc_id: int, *, include_deleted: bool = False,
    owner_key_hash: str | None = None,
) -> Document:
    """Returns the document or raises DocumentNotFound.

    By default skips soft-deleted docs so GET on a 回收站 item 404s unless
    the caller explicitly asks for it (e.g. restore preview).
    """
    stmt = select(Document).where(Document.id == doc_id)
    if owner_key_hash is not None:
        stmt = stmt.where(Document.owner_key_hash == owner_key_hash)
    if not include_deleted:
        stmt = stmt.where(Document.status == STATUS_ACTIVE)
    doc = await session.scalar(stmt)
    if doc is None:
        raise DocumentNotFound(doc_id)
    return doc


async def create_document(
    session: AsyncSession, payload: DocumentCreate, *, owner_key_hash: str = ""
) -> Document:
    """Creates a new document. Commits."""
    doc = Document(
        owner_key_hash=owner_key_hash,
        title=payload.title,
        content_html=sanitize_content_html(payload.content_html),
        content_text=payload.content_text,
        doc_type=payload.doc_type,
        category=payload.category,
        metadata_json=payload.metadata_json or {},
        cover_url=payload.cover_url,
        word_count=_compute_word_count(payload.content_text),
    )
    session.add(doc)
    await session.flush()  # populate doc.id without expiring
    await session.commit()
    await session.refresh(doc)
    return doc


async def update_document(
    session: AsyncSession, doc_id: int, payload: DocumentUpdate,
    *, owner_key_hash: str | None = None,
) -> Document:
    """Partial update via model_dump(exclude_unset=True). Bumps version.
    Commits. Raises DocumentNotFound if missing.

    Recomputes word_count when content_text changes.
    """
    doc = await get_document(session, doc_id, owner_key_hash=owner_key_hash)
    updates = payload.model_dump(exclude_unset=True)
    if "content_html" in updates and updates["content_html"] is not None:
        updates["content_html"] = sanitize_content_html(updates["content_html"])
    content_changed = "content_text" in updates
    # DocLite: capture the pre-edit text for incremental word count so
    # >100KB saves don't pay a full-text regex pass.
    old_text = doc.content_text or ""
    old_count = doc.word_count or 0
    for field, value in updates.items():
        setattr(doc, field, value)
    if content_changed:
        new_text = doc.content_text or ""
        doc.word_count = _compute_word_count_incremental(
            old_text, new_text, old_count,
        )
    if updates:
        doc.version = doc.version + 1
    await session.commit()
    await session.refresh(doc)
    return doc


async def delete_document(session: AsyncSession, doc_id: int, *, owner_key_hash: str | None = None) -> None:
    """Soft-deletes the document (status='deleted'). Commits.

    Idempotent: if already deleted, this is a no-op. Raises
    DocumentNotFound if the id does not exist at all.
    """
    doc = await get_document(session, doc_id, include_deleted=True, owner_key_hash=owner_key_hash)
    if doc.status != STATUS_DELETED:
        doc.status = STATUS_DELETED
        await session.commit()


async def restore_document(session: AsyncSession, doc_id: int, *, owner_key_hash: str | None = None) -> Document:
    """Restores a soft-deleted document. Commits. Raises DocumentNotFound."""
    doc = await get_document(session, doc_id, include_deleted=True, owner_key_hash=owner_key_hash)
    doc.status = STATUS_ACTIVE
    await session.commit()
    await session.refresh(doc)
    return doc


async def permanent_delete_document(session: AsyncSession, doc_id: int, *, owner_key_hash: str | None = None) -> None:
    """Permanently removes the document row. Commits. Raises DocumentNotFound."""
    doc = await get_document(session, doc_id, include_deleted=True, owner_key_hash=owner_key_hash)
    await session.delete(doc)
    await session.commit()
