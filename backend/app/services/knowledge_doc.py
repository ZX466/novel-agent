"""Knowledge-base service (F4 本地知识库).

Uploaded text files are validated against a whitelist (extension + size),
sanitized to a safe base name, split into ~800-char chunks, embedded in
one batch call, and persisted as one `KnowledgeDoc` row per chunk.

Security posture (aligned with the Codex upload spec intent):
  - extension + byte-size whitelists enforced at the boundary
  - the file name is reduced to a base name (no path traversal)
  - content is decoded as strict UTF-8 and stored as PLAIN TEXT — it is
    never rendered as HTML server-side, so there is no markup-injection
    surface (the frontend must render it as text, not innerHTML)
  - every chunk is scoped by `owner_key_hash` + `novel_id`; the API layer
    additionally verifies the novel belongs to the caller before upload
  - no outbound URL fetching on upload → no SSRF surface
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.embedding import embed_batch
from app.models.knowledge_doc import KnowledgeDoc
from app.schemas.chat import StageConfig

logger = __import__("logging").getLogger(__name__)

_ILLEGAL_FILENAME_CHARS = re.compile(r"[\x00-\x1f\x7f]")

# Reject anything that isn't a plausible file name (no path separators,
# drive letters, or directory components).
_UNSAFE_FILENAME = re.compile(r"[/\\]|[:*?\"<>|]")


class KnowledgeDocError(Exception):
    """Raised for user-facing knowledge-base validation failures.

    The API layer maps this to HTTP 400 with a safe, localized message.
    """


class KnowledgeFileNotFound(Exception):
    """Raised when the requested file has no chunks in the database."""


def sanitize_filename(name: str, max_len: int = 255) -> str:
    """Reduce a user-supplied file name to a safe, displayable base name.

    Keeps only the last path component (both slash styles), strips drive
    letters, control characters, and leading/trailing dots/spaces. Falls
    back to a generic name if nothing usable remains.
    """
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE_FILENAME.sub("", base)
    base = _ILLEGAL_FILENAME_CHARS.sub("", base).strip(" .")
    return (base[:max_len] or "untitled.txt")


def chunk_text(text: str, chunk_size: int | None = None) -> list[str]:
    """Split text into ~`chunk_size`-char chunks, preferring paragraph
    boundaries so each chunk stays semantically coherent.

    Paragraphs (separated by blank lines) are greedily packed into chunks;
    a single paragraph longer than `chunk_size` is hard-split. Empty/blank
    input yields an empty list.
    """
    size = chunk_size or settings.knowledge_chunk_size
    paragraphs = [p.strip() for p in re.split(r"\n[ \t]*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(para) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            rest = para
            while len(rest) > size:
                chunks.append(rest[:size])
                rest = rest[size:]
            buf = rest
            continue
        if buf and len(buf) + 2 + len(para) > size:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


async def upload_knowledge_doc(
    session: AsyncSession,
    *,
    novel_id: int,
    filename: str,
    content: bytes,
    owner_key_hash: str,
    stage_config: StageConfig | None = None,
) -> tuple[list[KnowledgeDoc], int]:
    """Validate, chunk, embed and persist an uploaded text file.

    Returns (created_chunks, file_size_bytes). Raises KnowledgeDocError on
    disallowed extension, oversized payload, or non-UTF-8 content.
    """
    allowed = {ext.lower() for ext in settings.knowledge_upload_extensions}
    dot = filename.rfind(".")
    ext = filename[dot + 1 :].lower() if dot != -1 else ""
    if ext not in allowed:
        # Generic client message — never disclose the allowlist or the
        # rejected extension (info-leak hygiene, Codex F4 review).
        raise KnowledgeDocError("不支持的文件类型")

    if len(content) > settings.knowledge_upload_max_bytes:
        raise KnowledgeDocError(
            f"文件过大（{len(content)} 字节，上限 {settings.knowledge_upload_max_bytes} 字节）"
        )

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise KnowledgeDocError("文件必须为 UTF-8 编码的纯文本")

    title = sanitize_filename(filename)
    chunks = chunk_text(text)
    if not chunks:
        raise KnowledgeDocError("文件内容为空")

    # Storage quota (Codex F4 follow-up): reject uploads that would push the
    # novel's knowledge base past the per-novel byte quota.
    used_stmt = (
        select(func.coalesce(func.sum(func.length(KnowledgeDoc.content)), 0))
        .where(KnowledgeDoc.novel_id == novel_id)
        .where(KnowledgeDoc.owner_key_hash == owner_key_hash)
    )
    used = (await session.execute(used_stmt)).scalar_one() or 0
    if used + len(content) > settings.knowledge_quota_bytes:
        raise KnowledgeDocError(
            f"知识库容量已达上限（每作品 {settings.knowledge_quota_bytes} 字节）"
        )

    vectors = await embed_batch(chunks, stage_config=stage_config)
    rows = [
        KnowledgeDoc(
            owner_key_hash=owner_key_hash,
            novel_id=novel_id,
            title=title,
            chunk_index=i,
            content=chunk,
            embedding=vec,
        )
        for i, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]
    session.add_all(rows)
    await session.flush()
    await session.commit()
    for row in rows:
        await session.refresh(row)
    logger.info("knowledge: uploaded novel_id=%d title=%r chunks=%d", novel_id, title, len(rows))
    return rows, len(content)


async def list_knowledge_files(
    session: AsyncSession,
    *,
    novel_id: int,
    owner_key_hash: str,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """List uploaded files (grouped by title) with per-file chunk counts.

    Returns (items, total_files). Items are dicts with keys title,
    chunk_count, created_at — a light shape that never exposes chunk
    content. Grouping is done in Python so the result is easy to unit-test
    with the MockAsyncSession double.
    """
    stmt = (
        select(KnowledgeDoc)
        .where(KnowledgeDoc.novel_id == novel_id)
        .where(KnowledgeDoc.owner_key_hash == owner_key_hash)
        .order_by(KnowledgeDoc.created_at.asc(), KnowledgeDoc.id.asc())
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    files: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = files.setdefault(
            row.title,
            {"title": row.title, "chunk_count": 0, "created_at": row.created_at},
        )
        entry["chunk_count"] += 1

    ordered = sorted(
        files.values(),
        key=lambda f: (f["created_at"] or datetime.min.replace(tzinfo=timezone.utc), f["title"]),
        reverse=True,
    )
    total = len(ordered)
    return ordered[offset : offset + limit], total


async def delete_knowledge_file(
    session: AsyncSession,
    *,
    novel_id: int,
    title: str,
    owner_key_hash: str,
) -> int:
    """Delete every chunk of a file. Returns the number of rows removed.

    Raises KnowledgeFileNotFound when nothing matched — the API layer maps
    it to HTTP 404.
    """
    stmt = (
        select(func.count(KnowledgeDoc.id))
        .where(KnowledgeDoc.novel_id == novel_id)
        .where(KnowledgeDoc.owner_key_hash == owner_key_hash)
        .where(KnowledgeDoc.title == title)
    )
    total = await session.scalar(stmt)
    if not total:
        raise KnowledgeFileNotFound(title)

    delete_stmt = (
        delete(KnowledgeDoc)
        .where(KnowledgeDoc.novel_id == novel_id)
        .where(KnowledgeDoc.owner_key_hash == owner_key_hash)
        .where(KnowledgeDoc.title == title)
    )
    result = await session.execute(delete_stmt)
    await session.commit()
    deleted = result.rowcount or 0
    logger.info("knowledge: deleted novel_id=%d title=%r rows=%d", novel_id, title, deleted)
    return deleted
