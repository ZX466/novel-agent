"""微信公众号 export adapter (R5-5)."""
from __future__ import annotations

from app.schemas.novel_memory import ChapterListItem

from .base import PlatformAdapter


class WechatAdapter(PlatformAdapter):
    name = "wechat"
    file_ext = "md"

    def render(
        self,
        *,
        title: str,
        author: str | None,
        cover_url: str | None,
        chapters: list[ChapterListItem],
    ) -> str:
        author = author or "佚名"
        lines: list[str] = []
        if cover_url:
            lines.append(f"![封面]({cover_url})")
            lines.append("")
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"作者：{author}")
        lines.append("")
        for ch in chapters:
            lines.append(f"## {self._chapter_heading(ch)}")
            lines.append("")
            lines.append(ch.content_text or "")
            lines.append("")
        lines.append("---")
        lines.append(f"原创声明：本文为{author}原创作品，转载请联系授权。")
        return "\n".join(lines)
