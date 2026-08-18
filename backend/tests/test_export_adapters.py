"""Unit tests for platform export adapters (R5-5)."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.schemas.novel_memory import ChapterListItem
from app.services.export_adapters import (
    ADAPTERS,
    get_adapter,
    render_platform,
)


def _chapter(index: int, title: str, body: str) -> ChapterListItem:
    return ChapterListItem(
        id=index + 1,
        chapter_index=index,
        title=title,
        content_text=body,
        status="draft",
        word_count=len(body),
        updated_at=datetime(2026, 1, 1),
    )


def test_registry_contains_four_platforms() -> None:
    assert set(ADAPTERS) == {"qidian", "jj", "zhihu", "wechat"}


def test_get_adapter_unknown_platform_raises() -> None:
    with pytest.raises(ValueError):
        get_adapter("unknown")


def test_qidian_renders_chapter_and_signature() -> None:
    chapters = [_chapter(0, "第一章 苏醒", "正文内容")]
    out = render_platform("qidian", title="我的小说", author="墨白", cover_url=None, chapters=chapters)
    assert "我的小说" in out
    assert "第1章 第一章 苏醒" in out
    assert "正文内容" in out
    assert "起点" in out
    assert "墨白" in out
    assert "版权" in out


def test_jj_renders_exclusive_disclaimer() -> None:
    chapters = [_chapter(0, "第一章 苏醒", "正文内容")]
    out = render_platform("jj", title="我的小说", author="墨白", cover_url=None, chapters=chapters)
    assert "晋江" in out
    assert "第1章 第一章 苏醒" in out
    assert "谢绝转载" in out


def test_zhihu_includes_cover_when_present() -> None:
    chapters = [_chapter(0, "第一章 苏醒", "正文内容")]
    out = render_platform("zhihu", title="我的小说", author="墨白", cover_url="https://x/c.jpg", chapters=chapters)
    assert "![封面](https://x/c.jpg)" in out
    assert "作者：墨白" in out
    assert "知乎专栏" in out


def test_zhihu_omits_cover_when_absent() -> None:
    chapters = [_chapter(0, "第一章 苏醒", "正文内容")]
    out = render_platform("zhihu", title="我的小说", author=None, cover_url="", chapters=chapters)
    assert "![封面]" not in out
    assert "作者：佚名" in out


def test_wechat_renders_original_statement() -> None:
    chapters = [_chapter(0, "第一章 苏醒", "正文内容")]
    out = render_platform("wechat", title="我的小说", author="墨白", cover_url="https://x/c.jpg", chapters=chapters)
    assert "![封面](https://x/c.jpg)" in out
    assert "原创" in out
    assert "墨白" in out
