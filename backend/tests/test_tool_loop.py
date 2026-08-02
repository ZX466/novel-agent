"""Tests for app.tools.loop — the LLM ↔ tool execution loop.

Covers P1-tool-2: validates the tool-calling loop's iteration logic,
tool execution dispatch, error handling, max-iteration cap, and
message-mutation contract. The LLM callable is mocked via AsyncMock
so no real LLM call is made; tools use a fake Tool subclass for
end-to-end registry wiring without DB / LLM dependencies.

Test groups:
  - ToolLoopResult / ToolCallRecord dataclass shape
  - run_tool_loop fast paths (no tools, immediate final answer)
  - run_tool_loop tool dispatch (1 call, 2 calls, args parsing)
  - run_tool_loop error paths (unknown tool, bad JSON, tool exception)
  - run_tool_loop max_iterations cap
  - run_tool_loop message mutation (assistant + tool messages appended)
  - run_tool_loop LLM call kwargs (tool_choice, llm_kwargs passed through)
  - run_tool_loop default llm = litellm.acompletion
  - build_llm_kwargs (BYOK vs env defaults)
  - run_tool_loop validation (max_iterations >= 1)
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.tools import (
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    build_llm_kwargs,
    run_tool_loop,
)
from app.tools.loop import ToolCallRecord, ToolLoopResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _fake_response(content=None, tool_calls=None):
    """Build a litellm-shaped response with a single choice."""
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _fake_tool_call(id, name, arguments):
    """Build a single tool_call object matching OpenAI's shape."""
    return SimpleNamespace(
        id=id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class _CountingTool(Tool):
    """Fake tool that echoes its arg and counts invocations."""

    name = "count"
    description = "Echoes the input n."

    class Params(BaseModel):
        n: int = 0

    def __init__(self):
        self.call_count = 0

    async def execute(self, params, ctx):
        self.call_count += 1
        return ToolResult.success({"echoed": params.n, "call_index": self.call_count})


class _ExplodingTool(Tool):
    """Tool that always raises — tests exception isolation in the registry."""

    name = "explode"
    description = "Always raises."

    class Params(BaseModel):
        pass

    async def execute(self, params, ctx):
        raise RuntimeError("kaboom")


def _registry_with(*tools):
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def _ctx(session="fake-session"):
    return ToolContext(session=session)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ToolLoopResult / ToolCallRecord dataclass
# ---------------------------------------------------------------------------


def test_tool_loop_result_defaults():
    r = ToolLoopResult(final_content=None)
    assert r.final_content is None
    assert r.tool_calls_trace == []
    assert r.iterations == 0
    assert r.max_iterations_reached is False


def test_tool_loop_result_with_content():
    r = ToolLoopResult(final_content="hello", iterations=1)
    assert r.final_content == "hello"
    assert r.iterations == 1


def test_tool_call_record_shape():
    result = ToolResult.success({"x": 1})
    rec = ToolCallRecord(name="foo", arguments={"a": 1}, result=result)
    assert rec.name == "foo"
    assert rec.arguments == {"a": 1}
    assert rec.result.ok is True
    assert rec.result.data == {"x": 1}


# ---------------------------------------------------------------------------
# Fast paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_tools_calls_llm_once():
    """Empty registry → single LLM call, returns content, no loop."""
    llm = AsyncMock(return_value=_fake_response(content="final answer"))
    reg = ToolRegistry()  # no tools

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "hi"}],
        llm=llm,
        llm_kwargs={"model": "test-model"},
        registry=reg,
        ctx=_ctx(),
    )

    assert llm.await_count == 1
    assert result.final_content == "final answer"
    assert result.iterations == 1
    assert result.tool_calls_trace == []
    assert result.max_iterations_reached is False


@pytest.mark.asyncio
async def test_immediate_final_answer():
    """LLM returns no tool_calls on first response → exits immediately."""
    llm = AsyncMock(return_value=_fake_response(content="done"))
    reg = _registry_with(_CountingTool())

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "hi"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    assert llm.await_count == 1
    assert result.final_content == "done"
    assert result.iterations == 1
    assert result.tool_calls_trace == []
    assert result.max_iterations_reached is False


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_tool_call_then_final():
    """LLM returns 1 tool_call, then final content → 2 iterations, 1 trace."""
    tool = _CountingTool()
    responses = [
        _fake_response(tool_calls=[_fake_tool_call("c1", "count", '{"n": 5}')]),
        _fake_response(content="after tool"),
    ]
    llm = AsyncMock(side_effect=responses)
    reg = _registry_with(tool)

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "go"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    assert llm.await_count == 2
    assert result.final_content == "after tool"
    assert result.iterations == 2
    assert len(result.tool_calls_trace) == 1
    assert result.tool_calls_trace[0].name == "count"
    assert result.tool_calls_trace[0].arguments == {"n": 5}
    assert result.tool_calls_trace[0].result.ok is True
    assert result.tool_calls_trace[0].result.data == {"echoed": 5, "call_index": 1}
    assert tool.call_count == 1
    assert result.max_iterations_reached is False


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_response():
    """LLM returns 2 tool_calls in one response → 2 trace entries, 1 iteration."""
    tool = _CountingTool()
    responses = [
        _fake_response(tool_calls=[
            _fake_tool_call("c1", "count", '{"n": 1}'),
            _fake_tool_call("c2", "count", '{"n": 2}'),
        ]),
        _fake_response(content="merged result"),
    ]
    llm = AsyncMock(side_effect=responses)
    reg = _registry_with(tool)

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "go"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    assert result.final_content == "merged result"
    assert result.iterations == 2
    assert len(result.tool_calls_trace) == 2
    assert result.tool_calls_trace[0].arguments == {"n": 1}
    assert result.tool_calls_trace[1].arguments == {"n": 2}
    assert tool.call_count == 2


@pytest.mark.asyncio
async def test_tool_executed_with_correct_ctx():
    """Tool.execute receives the ToolContext passed to run_tool_loop."""
    captured = {}

    class _CapturingTool(Tool):
        name = "capture"
        description = "Captures ctx"
        class Params(BaseModel):
            pass

        async def execute(self, params, ctx):
            captured["session"] = ctx.session
            captured["novel_id"] = ctx.novel_id
            return ToolResult.success({})

    reg = _registry_with(_CapturingTool())
    llm = AsyncMock(side_effect=[
        _fake_response(tool_calls=[_fake_tool_call("c1", "capture", "{}")]),
        _fake_response(content="ok"),
    ])
    ctx = ToolContext(session="my-session", novel_id=42)  # type: ignore[arg-type]

    await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=ctx,
    )

    assert captured["session"] == "my-session"
    assert captured["novel_id"] == 42


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_name_continues_loop():
    """LLM calls a tool not in registry → registry.invoke returns failure,
    failure message is appended, loop continues."""
    llm = AsyncMock(side_effect=[
        _fake_response(tool_calls=[_fake_tool_call("c1", "nonexistent", "{}")]),
        _fake_response(content="recovered"),
    ])
    reg = _registry_with(_CountingTool())  # only 'count', not 'nonexistent'

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    assert result.final_content == "recovered"
    assert len(result.tool_calls_trace) == 1
    assert result.tool_calls_trace[0].name == "nonexistent"
    assert result.tool_calls_trace[0].result.ok is False
    assert "not registered" in result.tool_calls_trace[0].result.error


@pytest.mark.asyncio
async def test_invalid_json_arguments_continues_loop():
    """LLM returns invalid JSON as arguments → loop catches, continues."""
    llm = AsyncMock(side_effect=[
        _fake_response(tool_calls=[
            _fake_tool_call("c1", "count", "not-valid-json{"),
        ]),
        _fake_response(content="recovered"),
    ])
    reg = _registry_with(_CountingTool())

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    assert result.final_content == "recovered"
    assert len(result.tool_calls_trace) == 1
    rec = result.tool_calls_trace[0]
    assert rec.name == "count"
    assert rec.result.ok is False
    assert "Invalid JSON" in rec.result.error
    assert rec.arguments == {}  # parsed-args default on failure


@pytest.mark.asyncio
async def test_tool_exception_isolated():
    """Tool.execute raises → registry.invoke catches, returns failure."""
    llm = AsyncMock(side_effect=[
        _fake_response(tool_calls=[_fake_tool_call("c1", "explode", "{}")]),
        _fake_response(content="recovered"),
    ])
    reg = _registry_with(_ExplodingTool())

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    assert result.final_content == "recovered"
    assert len(result.tool_calls_trace) == 1
    rec = result.tool_calls_trace[0]
    assert rec.result.ok is False
    assert "RuntimeError" in rec.result.error
    assert "kaboom" in rec.result.error


@pytest.mark.asyncio
async def test_failed_tool_message_format():
    """Verify the role:tool message after a failed tool has the error payload."""
    captured_messages = []

    class _CapturingLLM:
        async def __call__(self, messages, **kwargs):
            captured_messages.append(list(messages))  # snapshot
            if len(captured_messages) == 1:
                return _fake_response(tool_calls=[
                    _fake_tool_call("c1", "explode", "{}"),
                ])
            return _fake_response(content="done")

    reg = _registry_with(_ExplodingTool())
    llm = _CapturingLLM()

    await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    # Second LLM call should have:
    #   [0] original user message
    #   [1] assistant message with tool_calls
    #   [2] role:tool message with error payload
    second_call_messages = captured_messages[1]
    assert len(second_call_messages) == 3
    assert second_call_messages[0]["role"] == "user"
    assert second_call_messages[1]["role"] == "assistant"
    assert second_call_messages[1]["tool_calls"][0]["function"]["name"] == "explode"
    assert second_call_messages[2]["role"] == "tool"
    assert second_call_messages[2]["tool_call_id"] == "c1"
    payload = json.loads(second_call_messages[2]["content"])
    assert "error" in payload
    assert "kaboom" in payload["error"]


# ---------------------------------------------------------------------------
# max_iterations cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_iterations_reached():
    """LLM keeps calling tools → loop hits cap, returns None content."""
    # Every response has a tool_call → never terminates naturally.
    llm = AsyncMock(return_value=_fake_response(
        tool_calls=[_fake_tool_call("c1", "count", '{"n": 0}')],
    ))
    reg = _registry_with(_CountingTool())

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "go"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
        max_iterations=3,
    )

    assert result.final_content is None
    assert result.max_iterations_reached is True
    assert result.iterations == 3
    assert llm.await_count == 3
    assert len(result.tool_calls_trace) == 3


@pytest.mark.asyncio
async def test_max_iterations_one():
    """max_iterations=1 → only one LLM call allowed. If it has tool_calls,
    loop exits immediately with None content."""
    llm = AsyncMock(return_value=_fake_response(
        tool_calls=[_fake_tool_call("c1", "count", '{"n": 1}')],
    ))
    reg = _registry_with(_CountingTool())

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "go"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
        max_iterations=1,
    )

    assert result.final_content is None
    assert result.max_iterations_reached is True
    assert result.iterations == 1
    assert llm.await_count == 1


@pytest.mark.asyncio
async def test_max_iterations_exactly_enough():
    """max_iterations=2 → exactly enough for 1 tool call + 1 final."""
    llm = AsyncMock(side_effect=[
        _fake_response(tool_calls=[_fake_tool_call("c1", "count", '{"n": 1}')]),
        _fake_response(content="final"),
    ])
    reg = _registry_with(_CountingTool())

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "go"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
        max_iterations=2,
    )

    assert result.final_content == "final"
    assert result.max_iterations_reached is False
    assert result.iterations == 2


# ---------------------------------------------------------------------------
# Message mutation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_messages_mutated_in_place():
    """The messages list passed in is mutated — assistant + tool messages
    are appended so the caller can inspect the full conversation after."""
    messages = [{"role": "user", "content": "go"}]
    llm = AsyncMock(side_effect=[
        _fake_response(tool_calls=[_fake_tool_call("c1", "count", '{"n": 1}')]),
        _fake_response(content="final"),
    ])
    reg = _registry_with(_CountingTool())

    await run_tool_loop(
        messages=messages,
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    # Original list now has: user, assistant(with tool_calls), tool, (no final
    # assistant because the final response had no tool_calls — we don't append
    # the final assistant message since the loop exits immediately).
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "count"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "c1"
    payload = json.loads(messages[2]["content"])
    assert payload["echoed"] == 1


@pytest.mark.asyncio
async def test_tool_result_message_payload_is_json():
    """The role:tool message content is a JSON string of the tool's data."""
    captured_messages = []

    class _CapturingLLM:
        async def __call__(self, messages, **kwargs):
            captured_messages.append(list(messages))
            if len(captured_messages) == 1:
                return _fake_response(tool_calls=[
                    _fake_tool_call("c1", "count", '{"n": 42}'),
                ])
            return _fake_response(content="done")

    reg = _registry_with(_CountingTool())
    llm = _CapturingLLM()

    await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    # Second LLM call's messages should include the role:tool message.
    second_call_messages = captured_messages[1]
    tool_msg = second_call_messages[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c1"
    payload = json.loads(tool_msg["content"])
    assert payload["echoed"] == 42
    assert payload["call_index"] == 1


@pytest.mark.asyncio
async def test_assistant_message_with_tool_calls_appended_as_dict():
    """The assistant message is converted to dict form (with tool_calls)
    before being appended, so litellm accepts it on the next call."""
    captured_messages = []

    class _CapturingLLM:
        async def __call__(self, messages, **kwargs):
            captured_messages.append(list(messages))
            if len(captured_messages) == 1:
                return _fake_response(tool_calls=[
                    _fake_tool_call("abc-123", "count", '{"n": 7}'),
                ])
            return _fake_response(content="ok")

    reg = _registry_with(_CountingTool())
    llm = _CapturingLLM()

    await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    # Second call's messages should include the dict-form assistant message.
    second_call = captured_messages[1]
    assistant_msg = second_call[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["id"] == "abc-123"
    assert assistant_msg["tool_calls"][0]["type"] == "function"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "count"
    assert assistant_msg["tool_calls"][0]["function"]["arguments"] == '{"n": 7}'


# ---------------------------------------------------------------------------
# LLM call kwargs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_choice_passed_through():
    """tool_choice is forwarded to the LLM call."""
    llm = AsyncMock(return_value=_fake_response(content="x"))
    reg = _registry_with(_CountingTool())

    await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
        tool_choice="required",
    )

    assert llm.await_count == 1
    assert llm.await_args.kwargs["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_llm_kwargs_passed_through():
    """Static llm_kwargs (model, api_key, etc.) are forwarded to each call."""
    llm = AsyncMock(return_value=_fake_response(content="x"))
    reg = _registry_with(_CountingTool())
    kwargs = {"model": "my-model", "api_key": "sk-x", "api_base": "http://x/v1"}

    await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs=kwargs,
        registry=reg,
        ctx=_ctx(),
    )

    call_kwargs = llm.await_args.kwargs
    assert call_kwargs["model"] == "my-model"
    assert call_kwargs["api_key"] == "sk-x"
    assert call_kwargs["api_base"] == "http://x/v1"
    # tools and tool_choice are added by the loop.
    assert "tools" in call_kwargs
    assert call_kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_no_tools_skips_tools_kwarg():
    """Empty registry → no 'tools' or 'tool_choice' in LLM call kwargs."""
    llm = AsyncMock(return_value=_fake_response(content="x"))
    reg = ToolRegistry()

    await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    call_kwargs = llm.await_args.kwargs
    assert "tools" not in call_kwargs
    assert "tool_choice" not in call_kwargs


# ---------------------------------------------------------------------------
# Default LLM = litellm.acompletion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_llm_is_litellm_acompletion():
    """When llm=None, the loop uses litellm.acompletion at call time.
    Patching litellm.acompletion at test time is picked up."""
    fake_response = _fake_response(content="from-litellm")
    with patch("litellm.acompletion", AsyncMock(return_value=fake_response)):
        result = await run_tool_loop(
            messages=[{"role": "user", "content": "x"}],
            llm=None,
            llm_kwargs={"model": "m"},
            registry=ToolRegistry(),
            ctx=_ctx(),
        )
    assert result.final_content == "from-litellm"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_iterations_must_be_positive():
    """max_iterations < 1 → ValueError."""
    with pytest.raises(ValueError, match="max_iterations"):
        await run_tool_loop(
            messages=[],
            llm=AsyncMock(),
            llm_kwargs={},
            registry=ToolRegistry(),
            ctx=_ctx(),
            max_iterations=0,
        )


@pytest.mark.asyncio
async def test_max_iterations_must_be_positive_negative():
    with pytest.raises(ValueError, match="max_iterations"):
        await run_tool_loop(
            messages=[],
            llm=AsyncMock(),
            llm_kwargs={},
            registry=ToolRegistry(),
            ctx=_ctx(),
            max_iterations=-1,
        )


# ---------------------------------------------------------------------------
# build_llm_kwargs
# ---------------------------------------------------------------------------


def test_build_llm_kwargs_with_env_defaults():
    kwargs = build_llm_kwargs(
        None,
        default_model="deepseek/my-model",
        default_api_key="env-key",
        default_api_base="http://env/v1",
    )
    assert kwargs["model"] == "deepseek/my-model"
    assert kwargs["api_key"] == "env-key"
    assert kwargs["api_base"] == "http://env/v1"
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_tokens"] == 2048


def test_build_llm_kwargs_with_env_defaults_no_api_base():
    kwargs = build_llm_kwargs(
        None,
        default_model="my-model",
    )
    assert kwargs["model"] == "my-model"
    assert "api_key" not in kwargs
    assert "api_base" not in kwargs
    assert kwargs["temperature"] == 0.7


def test_build_llm_kwargs_with_byok_stage_config():
    """BYOK StageConfig → uses openai/ prefix + user's api_base/api_key."""
    from app.schemas.chat import StageConfig

    stage = StageConfig(
        api_base="https://api.openai.com/v1",
        api_key="sk-test-123",
        model="gpt-4o-mini",
    )
    kwargs = build_llm_kwargs(stage, temperature=0.4, max_tokens=512)
    assert kwargs["model"] == "openai/gpt-4o-mini"
    assert kwargs["api_key"] == "sk-test-123"
    assert kwargs["api_base"] == "https://api.openai.com/v1"
    assert kwargs["temperature"] == 0.4
    assert kwargs["max_tokens"] == 512


def test_build_llm_kwargs_byok_validates_ssrf():
    """BYOK api_base pointing at internal IP → ValueError from SSRF check."""
    from app.schemas.chat import StageConfig

    stage = StageConfig(
        api_base="http://169.254.169.254/v1",  # cloud metadata
        api_key="sk-x",
        model="m",
    )
    with pytest.raises(ValueError, match="Blocked internal address"):
        build_llm_kwargs(stage)


def test_build_llm_kwargs_requires_default_model_when_no_stage():
    """No stage_config and no default_model → ValueError."""
    with pytest.raises(ValueError, match="default_model is required"):
        build_llm_kwargs(None)


# ---------------------------------------------------------------------------
# End-to-end with real ToolRegistry + schemas export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_registry_schemas_passed_to_llm():
    """The LLM call's 'tools' kwarg matches the registry's schemas()."""
    reg = _registry_with(_CountingTool())
    expected_schemas = reg.schemas()
    llm = AsyncMock(return_value=_fake_response(content="x"))

    await run_tool_loop(
        messages=[{"role": "user", "content": "x"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
    )

    call_kwargs = llm.await_args.kwargs
    assert call_kwargs["tools"] == expected_schemas
    # Verify schema shape.
    assert call_kwargs["tools"][0]["type"] == "function"
    assert call_kwargs["tools"][0]["function"]["name"] == "count"
    assert "parameters" in call_kwargs["tools"][0]["function"]


@pytest.mark.asyncio
async def test_e2e_full_loop_with_real_tool():
    """Full loop: LLM calls count(5), then count(10), then final answer."""
    tool = _CountingTool()
    reg = _registry_with(tool)
    llm = AsyncMock(side_effect=[
        _fake_response(tool_calls=[_fake_tool_call("c1", "count", '{"n": 5}')]),
        _fake_response(tool_calls=[_fake_tool_call("c2", "count", '{"n": 10}')]),
        _fake_response(content="final answer"),
    ])

    result = await run_tool_loop(
        messages=[{"role": "user", "content": "go"}],
        llm=llm,
        llm_kwargs={"model": "m"},
        registry=reg,
        ctx=_ctx(),
        max_iterations=5,
    )

    assert result.final_content == "final answer"
    assert result.iterations == 3
    assert len(result.tool_calls_trace) == 2
    assert result.tool_calls_trace[0].arguments == {"n": 5}
    assert result.tool_calls_trace[1].arguments == {"n": 10}
    assert tool.call_count == 2
    assert result.max_iterations_reached is False
