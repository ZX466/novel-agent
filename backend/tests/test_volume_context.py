"""Tests for the volume-outline context block (09-14 优化2).

Volume-style outlines (卷→章, title-only) carry NO per-chapter synopsis, so
outlineForPrompt-style extraction on the backend had nothing to inject and
chapter generation was blind to its volume. Fix: _build_writing_context
accepts outline_text/volume_context in state and renders a 【本卷脉络】block
(volume summary + previous/next chapter titles) when provided.
"""
import pytest

from app.pipeline import nodes


@pytest.mark.asyncio
async def test_volume_context_block_rendered() -> None:
    """volume_context in state → 【本卷脉络】 block with summary + neighbors."""
    state: dict = {
        "chapter_index": 155,
        "total_chapters": 1000,
        "chapter_title": "夜火之眼",
        "volume_context": {
            "volume_summary": "第二卷 陆沉进入万灵原，与白夜结伴，发现神族篡改世界之语的真相。",
            "prev_title": "第155章 夜火之誓",
            "next_title": "第157章 神庭之影",
        },
    }
    ctx = await nodes._build_writing_context(state)
    assert "【本卷脉络】" in ctx
    assert "第二卷 陆沉进入万灵原" in ctx
    assert "第155章 夜火之誓" in ctx
    assert "第157章 神庭之影" in ctx


@pytest.mark.asyncio
async def test_volume_context_absent_skips_block() -> None:
    """No volume_context → no block (backward compatible)."""
    ctx = await nodes._build_writing_context({"chapter_index": 0})
    assert "【本卷脉络】" not in ctx


@pytest.mark.asyncio
async def test_volume_context_partial_fields_ok() -> None:
    """Only a summary, no neighbor titles → block still renders."""
    state: dict = {
        "volume_context": {"volume_summary": "第三卷主线：北境夺语。"},
    }
    ctx = await nodes._build_writing_context(state)
    assert "【本卷脉络】" in ctx
    assert "北境夺语" in ctx
    assert "上一章" not in ctx
