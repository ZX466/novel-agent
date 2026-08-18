"""Base class for platform-specific export adapters (R5-5)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.novel_memory import ChapterListItem


class PlatformAdapter(ABC):
    """Renders a document + chapters into a platform-ready Markdown string."""

    name: str = ""
    file_ext: str = "md"

    @abstractmethod
    def render(
        self,
        *,
        title: str,
        author: str | None,
        cover_url: str | None,
        chapters: list[ChapterListItem],
    ) -> str:
        ...

    def _chapter_heading(self, ch: ChapterListItem) -> str:
        return f"第{ch.chapter_index + 1}章 {ch.title}"
