"""Platform export adapter registry (R5-5)."""
from __future__ import annotations

from app.schemas.novel_memory import ChapterListItem

from .base import PlatformAdapter
from .jj import JinjiangAdapter
from .qidian import QidianAdapter
from .wechat import WechatAdapter
from .zhihu import ZhihuAdapter

ADAPTERS: dict[str, type[PlatformAdapter]] = {
    "qidian": QidianAdapter,
    "jj": JinjiangAdapter,
    "zhihu": ZhihuAdapter,
    "wechat": WechatAdapter,
}

PLATFORM_FORMATS = tuple(ADAPTERS)


def get_adapter(platform: str) -> PlatformAdapter:
    try:
        return ADAPTERS[platform]()
    except KeyError as exc:
        raise ValueError(f"unknown platform: {platform}") from exc


def render_platform(
    platform: str,
    *,
    title: str,
    author: str | None,
    cover_url: str | None,
    chapters: list[ChapterListItem],
) -> str:
    return get_adapter(platform).render(
        title=title,
        author=author,
        cover_url=cover_url,
        chapters=chapters,
    )
