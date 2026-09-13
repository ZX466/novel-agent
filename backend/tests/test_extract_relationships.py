"""Task 3: outline entity extraction must ask for character relationships.

The Creative Kit generates relationship lines, but the outline "AI 提取"
flow only returned characters/world_settings/plot_events. draft_node's
extract branch must request a fourth `relationships` array so the frontend
can feed it to the name-based import endpoint (outline -> graph).
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
    async def _gen():
        for item in items:
            yield item

    return _gen()


@pytest.mark.asyncio
async def test_extract_system_prompt_asks_for_relationships() -> None:
    """task_type=extract → system prompt declares the relationships array."""
    from unittest.mock import AsyncMock, patch

    state: dict = {"topic": "大纲文本", "task_type": "extract"}
    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return _as_async_iter(
            [_chunk('{"characters":[],"world_settings":[],"plot_events":[],"relationships":[]}')]
        )

    with patch.object(nodes, "llm_draft", AsyncMock(side_effect=_capture_messages)):
        await nodes.draft_node(state)

    system = captured["system"]
    assert "relationships" in system
    assert "relation_type" in system
    assert "subject_name" in system


@pytest.mark.asyncio
async def test_extract_prompt_declares_strength_range() -> None:
    """strength 取值范围必须显式声明（1-10 整数），否则模型乱给数值，
    导入端点 (ge=0, le=10) 直接 422 拒收整条关系线。"""
    from unittest.mock import AsyncMock, patch

    state: dict = {"topic": "大纲文本", "task_type": "extract"}
    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return _as_async_iter([_chunk("{}")])

    with patch.object(nodes, "llm_draft", AsyncMock(side_effect=_capture_messages)):
        await nodes.draft_node(state)

    assert "strength 为 1-10 的整数" in captured["system"]


@pytest.mark.asyncio
async def test_extract_prompt_keeps_core_entity_schema() -> None:
    """Guard: adding relationships must not drop the original three arrays."""
    from unittest.mock import AsyncMock, patch

    state: dict = {"topic": "大纲文本", "task_type": "extract"}
    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return _as_async_iter([_chunk("{}")])

    with patch.object(nodes, "llm_draft", AsyncMock(side_effect=_capture_messages)):
        await nodes.draft_node(state)

    system = captured["system"]
    for key in ("characters", "world_settings", "plot_events", "strength", "object_name"):
        assert key in system


@pytest.mark.asyncio
async def test_extract_relationship_instruction_conditional_on_outline() -> None:
    """大纲未体现人物关系 → 提示词要求 relationships 留空 []。"""
    from unittest.mock import AsyncMock, patch

    state: dict = {"topic": "大纲文本", "task_type": "extract"}
    captured: dict = {}

    def _capture_messages(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return _as_async_iter([_chunk("{}")])

    with patch.object(nodes, "llm_draft", AsyncMock(side_effect=_capture_messages)):
        await nodes.draft_node(state)

    assert "留空 []" in captured["system"]
