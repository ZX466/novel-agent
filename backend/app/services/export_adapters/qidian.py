"""起点中文网 export adapter (R5-5)."""
from __future__ import annotations

from app.schemas.novel_memory import ChapterListItem

from .base import PlatformAdapter


class QidianAdapter(PlatformAdapter):
    name = "qidian"
    file_ext = "md"

    def render(
        self,
        *,
        title: str,
        author: str | None,
        cover_url: str | None,
        chapters: list[ChapterListItem],
    ) -> str:
        author = author or "作者"
        lines: list[str] = [f"# {title}", ""]
        for ch in chapters:
            lines.append(f"## {self._chapter_heading(ch)}")
            lines.append("")
            lines.append(ch.content_text or "")
            lines.append("")
        lines.append("---")
        lines.append(f"本文由{author}发布于起点中文网。")
        lines.append("版权所有，侵权必究。")
        return "\n".join(lines)
