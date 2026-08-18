"""晋江文学城 export adapter (R5-5)."""
from __future__ import annotations

from app.schemas.novel_memory import ChapterListItem

from .base import PlatformAdapter


class JinjiangAdapter(PlatformAdapter):
    name = "jj"
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
        lines: list[str] = [f"# {title}", "", "[晋江文学城独家发表]", ""]
        for ch in chapters:
            lines.append(f"## {self._chapter_heading(ch)}")
            lines.append("")
            lines.append(ch.content_text or "")
            lines.append("")
        lines.append("---")
        lines.append(f"晋江独家连载，作者{author}。谢绝转载。")
        return "\n".join(lines)
