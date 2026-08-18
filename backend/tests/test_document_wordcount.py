"""TDD：DocLite word_count 增量计算测试（R5-6）。

验证 `_compute_word_count_incremental`（增量词数）：
- 与全量 `_compute_word_count` 结果一致（等价性）
- 只统计变化段（同前缀/同后缀场景）
- 中文 + Latin 混合
"""
from __future__ import annotations

import pytest

from app.services.document import (
    _compute_word_count,
    _compute_word_count_incremental,
)


# --- 等价性：增量结果必须与全量结果一致 ------------------------------------


@pytest.mark.parametrize(
    "old_text,new_text",
    [
        # 尾部追加（最常见：续写）
        ("第一章 开始", "第一章 开始 他推开门走了进去"),
        # 前缀不变 + 中间插入
        ("你好世界", "你好 美丽的 世界"),
        # 删除中间段
        ("a b c d e", "a c e"),
        # 全替换
        ("旧内容", "新内容 different"),
        # 混合中英
        ("第一章 hello", "第一章 hello world 中文"),
        # 空变非空
        ("", "新文档 Hello"),
        # 非空变空
        ("有些内容 xx", ""),
    ],
)
def test_incremental_matches_full(old_text: str, new_text: str) -> None:
    """增量结果 == 全量重算结果（核心等价性）。"""
    old_count = _compute_word_count(old_text)
    inc = _compute_word_count_incremental(old_text, new_text, old_count)
    full = _compute_word_count(new_text)
    assert inc == full, f"incremental={inc} full={full}"


def test_incremental_unchanged_text() -> None:
    """文本未变 → 增量结果不变。"""
    text = "第一章 测试 123"
    old_count = _compute_word_count(text)
    assert _compute_word_count_incremental(text, text, old_count) == old_count


def test_incremental_prefix_only_change_small_middle() -> None:
    """巨大前缀相同、仅尾部小改 → 增量只算变化段（性能用例）。"""
    # 模拟 100KB 长文：前缀 8 万个相同字符 + 尾部变化
    prefix = "甲" * 80000
    old_text = prefix + "旧尾 abc"
    new_text = prefix + "新尾 xyz 扩展"
    old_count = _compute_word_count(old_text)
    inc = _compute_word_count_incremental(old_text, new_text, old_count)
    full = _compute_word_count(new_text)
    assert inc == full


def test_incremental_with_whitespace_change() -> None:
    """空白变化（换行/空格）不影响词数正确性。"""
    old_text = "第一行\n第二行  第三行"
    new_text = "第一行\n第二行\n\n第三行 "  # 换行插入
    old_count = _compute_word_count(old_text)
    assert _compute_word_count_incremental(old_text, new_text, old_count) == _compute_word_count(new_text)
