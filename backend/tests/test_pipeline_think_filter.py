"""Tests for _ThinkStreamFilter — inline <think> block stripping.

Some reasoning models (step-3.7-flash etc.) emit chain-of-thought inline
in `content` between <think>…</think> tags instead of the separate
reasoning_content field. The filter must drop those blocks from both the
streamed tokens and the assembled text, while never eating novel content.
"""
import pytest

from app.pipeline.nodes import _ThinkStreamFilter


def feed_all(filter_: _ThinkStreamFilter, tokens: list[str]) -> str:
    out = "".join(filter_.feed(t) for t in tokens)
    out += filter_.finish()
    return filter_.strip(out)


def test_no_think_passthrough() -> None:
    """Plain content passes through unchanged."""
    f = _ThinkStreamFilter()
    assert feed_all(f, ["你好", "世界"]) == "你好世界"


def test_single_block_whole_stream() -> None:
    """Entire output is one think block → nothing leaks."""
    f = _ThinkStreamFilter()
    assert feed_all(f, ["<think>", "let me ponder.", "</think>"]) == ""


def test_think_then_content() -> None:
    """Thinking first, then real content — only content survives."""
    f = _ThinkStreamFilter()
    out = feed_all(f, ["<think>推理中…</think>\n\n", "第一章\n张三出门。"])
    assert out == "第一章\n张三出门。"


def test_tag_spanning_token_boundary() -> None:
    """<think> split across tokens must still be caught (buffer holdback)."""
    f = _ThinkStreamFilter()
    out = feed_all(f, ["正文A<thi", "nk>secret</th", "ink>正文B"])
    assert out == "正文A正文B"


def test_unclosed_think_dropped_at_end() -> None:
    """Unclosed <think> (truncated mid-thought): tail is dropped, head kept."""
    f = _ThinkStreamFilter()
    out = feed_all(f, ["开头", "<think>", "没写完的思考…"])
    assert out == "开头"


def test_multiline_and_multiple_blocks() -> None:
    """Multiple think blocks, multi-line, with surrounding whitespace cleanup."""
    f = _ThinkStreamFilter()
    out = feed_all(f, [
        "<think>a\nb\nc</think>\n", "第一段。",
        "<think>d</think>", "第二段。",
    ])
    assert out == "第一段。第二段。"


def test_angle_bracket_content_not_eaten() -> None:
    """Regular angle brackets that aren't think tags pass through intact."""
    f = _ThinkStreamFilter()
    out = feed_all(f, ["用 <b> 和 </div> 无关。", "别误伤 <thinking-adjacent 文本"])
    # "<thinking…" is 9 chars short of a full tag; holdback re-emits on strip/final
    assert "<b>" in out and "</div>" in out


@pytest.mark.asyncio
async def test_draft_node_filters_inline_think() -> None:
    """draft_node: inline <think> in streamed chunks never reaches on_token/draft."""
    from unittest.mock import AsyncMock, patch

    from app.pipeline import nodes

    state: dict = {"topic": "test", "task_type": "outline"}
    seen: list[str] = []

    async def cb(text: str) -> None:
        seen.append(text)

    state["on_token"] = cb
    chunks = [
        type("Chunk", (), {"choices": [type("C", (), {"delta": type("D", (), {"content": c})()})()]})()
        for c in ("<think>", "规划大纲中…", "</think># 大纲\n第一章")
    ]
    with patch.object(nodes, "llm_draft", AsyncMock(return_value=_as_async_iter(chunks))):
        out = await nodes.draft_node(state)

    assert out["draft"] == "# 大纲\n第一章"
    assert "".join(seen) == "# 大纲\n第一章"
    assert "规划" not in out["draft"]


@pytest.mark.asyncio
async def test_refine_node_filters_inline_think() -> None:
    """refine_node: same guarantee on the refine stage."""
    from unittest.mock import AsyncMock, patch

    from app.pipeline import nodes

    state: dict = {"draft": "原稿", "iterations": 0}
    chunks = [
        type("Chunk", (), {"choices": [type("C", (), {"delta": type("D", (), {"content": c})()})()]})()
        for c in ("润色后", "<think>改哪呢", "</think>定稿")
    ]
    with patch.object(nodes, "llm_refine", AsyncMock(return_value=_as_async_iter(chunks))):
        out = await nodes.refine_node(state)

    assert out["refined"] == "润色后定稿"


def _as_async_iter(items):
    async def gen():
        for i in items:
            yield i
    return gen()
