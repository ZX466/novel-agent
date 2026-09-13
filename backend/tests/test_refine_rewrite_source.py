"""Tests for refine_node as the FIRST pipeline stage (rewrite/polish tasks).

Deployment 09-13 regression: the rewrite/polish graph runs retrieval →
refine → safety_check (no draft node), but refine_node only read
state["draft"]/["refined"]/["feedback"] — never state["topic"]. The LLM
received empty Original draft / Current version blocks and hallucinated
free-form text (an unrelated English essay), which the outline-polish
button then saved over the user's outline.

Fix: when task_type is rewrite/polish and no draft exists, send `topic`
(the full instruction + source text, tags already stripped by chat.py)
straight through with a Chinese editor system prompt.
"""
import pytest

from app.pipeline import nodes


def _chunk(content: str):
    return type(
        "Chunk",
        (),
        {"choices": [type("C", (), {"delta": type("D", (), {"content": content})()})()]},
    )()


def _as_async_iter(items):
    async def gen():
        for i in items:
            yield i
    return gen()


@pytest.mark.asyncio
async def test_rewrite_refine_sends_topic_as_user_content() -> None:
    """rewrite with no draft → the topic text reaches llm_refine verbatim."""
    from unittest.mock import AsyncMock, patch

    state: dict = {
        "topic": "请润色以下小说总纲：保持卷/章结构。\n\n第一章 张三入宗\n第二章 修炼突破",
        "task_type": "rewrite",
        "iterations": 0,
    }
    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        return _as_async_iter([_chunk("润色后的总纲")])

    with patch.object(nodes, "llm_refine", AsyncMock(side_effect=_capture_messages)):
        out = await nodes.refine_node(state)

    assert "第一章 张三入宗" in captured["user"]
    assert "第二章 修炼突破" in captured["user"]
    # Chinese editor persona — the English-only system prompt pushed the
    # model toward English output on empty input.
    assert "编辑" in captured["system"]
    assert out["refined"] == "润色后的总纲"
    assert out["iterations"] == 1


@pytest.mark.asyncio
async def test_polish_refine_sends_topic_as_user_content() -> None:
    """task_type=polish (去AI味) hits the same first-stage branch."""
    from unittest.mock import AsyncMock, patch

    state: dict = {
        "topic": "请将以下内容改写为更自然的人类写作风格。\n\n待处理内容：\n他不禁感到一丝凉意。",
        "task_type": "polish",
    }

    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["user"] = messages[1]["content"]
        return _as_async_iter([_chunk("改写后")])

    with patch.object(nodes, "llm_refine", AsyncMock(side_effect=_capture_messages)):
        await nodes.refine_node(state)

    assert "他不禁感到一丝凉意。" in captured["user"]


@pytest.mark.asyncio
async def test_generate_loop_refine_keeps_draft_machinery() -> None:
    """generate loop (draft exists) keeps the Original-draft/feedback prompt."""
    from unittest.mock import AsyncMock, patch

    state: dict = {
        "topic": "写一段",
        "draft": "初稿正文",
        "task_type": "generate",
        "iterations": 0,
    }
    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["user"] = messages[1]["content"]
        return _as_async_iter([_chunk("改进版")])

    with patch.object(nodes, "llm_refine", AsyncMock(side_effect=_capture_messages)):
        await nodes.refine_node(state)

    assert "Original draft:" in captured["user"]
    assert "初稿正文" in captured["user"]


@pytest.mark.asyncio
async def test_rewrite_refine_includes_retrieved_lore() -> None:
    """retrieved_context still lands in the system prompt for rewrite."""
    from unittest.mock import AsyncMock, patch

    state: dict = {
        "topic": "请重写以下段落",
        "task_type": "rewrite",
        "retrieved_context": "1. [character] 陈默 (主角): 冷静理智",
    }
    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return _as_async_iter([_chunk("重写后")])

    with patch.object(nodes, "llm_refine", AsyncMock(side_effect=_capture_messages)):
        await nodes.refine_node(state)

    assert "陈默" in captured["system"]
    assert "编辑" in captured["system"]
