"""Tests for retrieval-query purification (09-14 第三项).

retrieval_node previously embedded the ENTIRE topic as the vector query.
For the rewrite family the topic is "请重写以下段落…要求：一、二、三…
待重写内容：<3000 chars>" — instruction boilerplate diluted the query
vector and dragged retrieval recall down. The purified query is:

  1. chapter_title (densest semantic signal) when present
  2. + the tail of the source text found after the
     待扩写内容/待重写内容/待处理内容/当前内容： marker (~500 chars)
  3. no marker & no title → whole topic (assistant etc. unchanged)
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline import nodes


# ── _retrieval_query unit tests ──────────────────────────────────────────


def test_query_prefers_title_plus_source_tail() -> None:
    topic = (
        "请重写以下段落（章节：第3章 夜行）。要求：\n"
        "- 保持情节不变\n- 只改进文笔\n"
        "直接输出重写后的完整段落。\n\n待重写内容：\n"
        + "林昭把剑横在膝上，盯着火堆。" * 60  # ~600 chars source
    )
    q = nodes._retrieval_query(topic, {"chapter_title": "夜行"})
    assert "夜行" in q
    assert "林昭" in q                     # source tail captured
    assert "保持情节不变" not in q          # instruction boilerplate dropped
    assert "待重写内容" not in q
    assert len(q) <= 600                   # title + ~500-char tail


def test_query_without_title_uses_source_tail_only() -> None:
    topic = "请将以下段落扩写。\n\n待扩写内容：\n" + "雪落无声。" * 80
    q = nodes._retrieval_query(topic, {})
    assert "雪落无声" in q
    assert "扩写" not in q


def test_query_falls_back_to_topic_without_marker() -> None:
    """assistant-style free text has no source marker → whole topic."""
    topic = "主角在第二章的动机是否成立？"
    q = nodes._retrieval_query(topic, {"chapter_title": ""})
    assert q == topic


def test_query_deai_and_continue_markers_supported() -> None:
    for marker in ("待处理内容：", "当前内容："):
        topic = f"指令部分。\n\n{marker}\n正文片段在这里。"
        q = nodes._retrieval_query(topic, {})
        assert "正文片段在这里" in q, marker
        assert "指令部分" not in q, marker


def test_query_title_only_when_source_tiny() -> None:
    topic = "待重写内容：\n短。"
    q = nodes._retrieval_query(topic, {"chapter_title": "雪夜"})
    assert "雪夜" in q and "短" in q


# ── retrieval_node wires the purified query ──────────────────────────────


@pytest.mark.asyncio
async def test_retrieval_node_uses_purified_query_for_rewrite() -> None:
    """retrieval_node must pass the purified query — not the raw topic —
    to retrieve()."""
    topic = (
        "请重写以下段落。要求：只改进文笔。\n\n待重写内容：\n"
        + "火堆旁的对白。" * 40
    )
    state: dict = {
        "topic": topic,
        "task_type": "rewrite",
        "session": SimpleNamespace(),  # truthy → retrieval path taken
        "novel_id": 1,
        "chapter_title": "夜行",
    }
    captured: dict = {}

    async def _fake_retrieve(session, query, **kwargs):
        captured["query"] = query
        return []

    async def _fake_writing_context(state):
        return ""

    with patch("app.services.retrieval.retrieve", _fake_retrieve), \
         patch.object(nodes, "_build_writing_context", _fake_writing_context):
        await nodes.retrieval_node(state)

    q = captured["query"]
    assert "夜行" in q
    assert "火堆旁的对白" in q
    assert "只改进文笔" not in q


@pytest.mark.asyncio
async def test_retrieval_node_assistant_keeps_raw_topic() -> None:
    """No title, no marker → the raw topic still reaches retrieve()."""
    topic = "怎么把伏笔埋得更自然？"
    state: dict = {
        "topic": topic,
        "task_type": "assistant",
        "session": SimpleNamespace(),
        "novel_id": 1,
    }
    captured: dict = {}

    async def _fake_retrieve(session, query, **kwargs):
        captured["query"] = query
        return []

    with patch("app.services.retrieval.retrieve", _fake_retrieve), \
         patch.object(nodes, "_build_writing_context", AsyncMock(return_value="")):
        await nodes.retrieval_node(state)

    assert captured["query"] == topic
