"""Export endpoints for documents."""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import load_parent, require_api_key
from app.db.session import get_db
from app.schemas.novel_memory import ChapterListItem
from app.services.document import get_document
from app.services.chapter import list_chapters
from app.services.export_adapters import PLATFORM_FORMATS, render_platform

router = APIRouter(tags=["export"])

logger = logging.getLogger(__name__)

_MIMETYPE = "application/epub+zip"


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def _safe_chapter_filename(index: int, title: str) -> str:
    safe = _xml_escape(title.strip()).replace("/", "-").replace("\\", "-")[:64] or f"chapter-{index:03d}"
    return f"chapter-{index:03d}-{safe}.xhtml"


def _build_markdown(doc_title: str, chapters: list[ChapterListItem]) -> str:
    lines: list[str] = [f"# {doc_title}", ""]
    for ch in chapters:
        lines.append(f"## {ch.title}")
        lines.append("")
        if ch.content_text:
            lines.append(ch.content_text)
        else:
            lines.append("")
    return "\n".join(lines)


def _build_text(doc_title: str, chapters: list[ChapterListItem]) -> str:
    lines: list[str] = [doc_title, ""]
    for ch in chapters:
        lines.append(ch.title)
        lines.append("")
        if ch.content_text:
            lines.append(ch.content_text)
        else:
            lines.append("")
    return "\n".join(lines)


def _chapter_filename(index: int, title: str) -> str:
    safe_title = title.strip().replace("/", "-").replace("\\", "-")[:64] or f"chapter-{index:03d}"
    return f"chapter-{index:03d}-{safe_title}.xhtml"


def _build_epub_bytes(doc_title: str, chapters: list[ChapterListItem]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # EPUB requires mimetype as first entry, uncompressed.
        zf.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)

        zf.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )

        manifest_items: list[str] = []
        spine_items: list[str] = []
        toc_points: list[str] = []

        css = """body { font-family: serif; margin: 1em; }
h1 { font-size: 1.4em; }
h2 { font-size: 1.2em; }
p { text-indent: 2em; margin: 0; }
"""
        zf.writestr("OEBPS/styles.css", css)

        for idx, ch in enumerate(chapters, start=1):
            file_id = f"chapter-{idx:03d}"
            file_name = _safe_chapter_filename(idx, ch.title)
            escaped_title = _xml_escape(ch.title)
            manifest_items.append(f'    <item id="{file_id}" href="{file_name}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'    <itemref idref="{file_id}"/>')
            toc_points.append(f'      <navPoint id="{file_id}" playOrder="{idx}"><navLabel><text>{escaped_title}</text></navLabel><content src="{file_name}"/></navPoint>')

            body_parts = [f"<h1>{escaped_title}</h1>"]
            if ch.content_text:
                for paragraph in ch.content_text.split("\n"):
                    escaped = paragraph.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    body_parts.append(f"<p>{escaped}</p>")
            else:
                body_parts.append("<p></p>")

            xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
  <link rel="stylesheet" type="text/css" href="styles.css"/>
  <title>{escaped_title}</title>
</head>
<body>
{chr(10).join(body_parts)}
</body>
</html>
"""
            zf.writestr(f"OEBPS/{file_name}", xhtml.encode("utf-8"))

        escaped_doc_title = _xml_escape(doc_title)
        content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">novel-export</dc:identifier>
    <dc:title>{escaped_doc_title}</dc:title>
    <dc:language>zh</dc:language>
    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="style" href="styles.css" media-type="text/css"/>
{chr(10).join(manifest_items)}
  </manifest>
  <spine toc="ncx">
{chr(10).join(spine_items)}
  </spine>
  <guide>
    <reference type="toc" title="Table of Contents" href="toc.ncx"/>
  </guide>
</package>
"""
        zf.writestr("OEBPS/content.opf", content_opf.encode("utf-8"))

        toc_ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="novel-export"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{escaped_doc_title}</text></docTitle>
  <navMap>
{chr(10).join(toc_points)}
  </navMap>
</ncx>
"""
        zf.writestr("OEBPS/toc.ncx", toc_ncx.encode("utf-8"))

    buffer.seek(0)
    return buffer.read()


@router.get("/v1/documents/{doc_id}/export")
async def export_document(
    doc_id: int,
    format: str = Query(
        ...,
        pattern=f"^(md|txt|epub|{'|'.join(PLATFORM_FORMATS)})$",
        description="导出格式：md / txt / epub / qidian / jj / zhihu / wechat",
    ),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> Response:
    """Export a document with its chapters.

    Supports markdown, plain text, and EPUB (zip container), plus
    platform-specific Markdown adapters (qidian / jj / zhihu / wechat) that
    render cover/byline/copyright per the target platform. Returns the
    exported file with a Content-Disposition attachment header.
    """
    await load_parent(session, doc_id)
    doc = await get_document(session, doc_id)
    chapters, _ = await list_chapters(session, novel_id=doc_id, limit=500, offset=0)

    filename_base = doc.title or f"document-{doc_id}"
    safe_filename = filename_base.replace("/", "-").replace("\\", "-") or "export"

    if format in PLATFORM_FORMATS:
        author = (doc.metadata_json or {}).get("author")
        content = render_platform(
            format,
            title=doc.title,
            author=author,
            cover_url=doc.cover_url or None,
            chapters=chapters,
        )
        media_type = "text/markdown; charset=utf-8"
        filename = f"{safe_filename}.md"
        body = content.encode("utf-8")
    elif format == "md":
        content = _build_markdown(doc.title, chapters)
        media_type = "text/markdown; charset=utf-8"
        filename = f"{safe_filename}.md"
        body = content.encode("utf-8")
    elif format == "txt":
        content = _build_text(doc.title, chapters)
        media_type = "text/plain; charset=utf-8"
        filename = f"{safe_filename}.txt"
        body = content.encode("utf-8")
    else:
        body = _build_epub_bytes(doc.title, chapters)
        media_type = _MIMETYPE
        filename = f"{safe_filename}.epub"

    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}",
    }
    return Response(content=body, media_type=media_type, headers=headers)
