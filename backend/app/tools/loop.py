"""Tool-calling loop — LLM ↔ tool execution until a final answer.

Composable with LangGraph nodes: an agent calls ``run_tool_loop()`` inside
its node function and returns the result merged into state.

This is the project's equivalent of ``langgraph.prebuilt.ToolNode`` +
the tool-calling agent loop, but using our own Tool abstraction (not
LangChain BaseTool). Keeps the dependency surface minimal — no
langchain-core, no langgraph.prebuilt, just litellm + our registry.

Loop invariant: ``messages`` always ends with either
  - the last assistant message (with tool_calls), followed by one
    role:tool message per tool_call, OR
  - the final assistant message (no tool_calls) — loop exits.

Cap iterations to prevent infinite loops. A misbehaving LLM that keeps
calling tools will hit the cap and return with ``final_content=None``
and ``max_iterations_reached=True`` — the caller decides whether to
retry with a "produce your final answer now" prompt.

The loop is framework-agnostic: ``llm`` is any async callable matching
``litellm.acompletion``'s signature (``messages`` + kwargs → response
with ``.choices[0].message``). Defaults to ``litellm.acompletion`` so
production code can omit it; tests pass an ``AsyncMock``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List

import litellm

from app.tools.base import ToolContext, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

# Async callable matching litellm.acompletion's signature.
LLMCallable = Callable[..., Awaitable[Any]]


@dataclass
class ToolCallRecord:
    """One tool invocation in the loop's trace."""

    name: str
    arguments: dict[str, Any]
    result: ToolResult


@dataclass
class ToolLoopResult:
    """Outcome of a tool-calling loop run.

    ``final_content`` is None when the LLM never produced a non-tool-call
    message before ``max_iterations`` was hit. Callers should handle
    that case (e.g. retry with a "produce your final answer now" prompt,
    or surface "agent exceeded tool budget" to the user).
    """

    final_content: str | None
    tool_calls_trace: list[ToolCallRecord] = field(default_factory=list)
    iterations: int = 0
    max_iterations_reached: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_message(response: Any) -> Any:
    """Pull choices[0].message from a litellm/OpenAI-shaped response."""
    return response.choices[0].message


def _has_tool_calls(message: Any) -> bool:
    """True if the message has a non-empty tool_calls list."""
    tool_calls = getattr(message, "tool_calls", None)
    return bool(tool_calls)


def _assistant_message_to_dict(message: Any) -> dict[str, Any]:
    """Convert the litellm Message object to a dict for re-injection.

    LiteLLM/OpenAI returns message objects with .content (str | None) and
    .tool_calls (list of ToolCall | None). When we re-inject the assistant
    message into the next call's messages list, we need the dict form so
    litellm accepts it on the next iteration.
    """
    out: dict[str, Any] = {
        "role": "assistant",
        "content": message.content or "",
    }
    if getattr(message, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
    return out


def _tool_result_message(tool_call_id: str, result: ToolResult) -> dict:
    """Build the role:tool message to append after a tool_call.

    On success, the payload is the tool's ``data`` dict. On failure,
    the payload is ``{"error": ...}`` so the LLM sees the error reason
    and can react (retry, ask for clarification, or give up).
    """
    payload = result.data if result.ok else {"error": result.error or "unknown"}
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(payload, ensure_ascii=False, default=str),
    }


def _parse_tool_arguments(raw_args: str) -> tuple[dict[str, Any], str | None]:
    """Parse the LLM's tool_call arguments JSON.

    Returns ``(args, error)``. When parsing fails, ``args`` is {} and
    ``error`` is a human-readable message. The error is surfaced to
    the LLM via the role:tool message so it can correct itself.
    """
    if not raw_args:
        return {}, None
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError as e:
        return {}, f"Invalid JSON arguments: {e}"
    if not isinstance(parsed, dict):
        return {}, f"Arguments must be a JSON object, got {type(parsed).__name__}"
    return parsed, None


async def _execute_tool_call(
    tool_call: Any,
    registry: ToolRegistry,
    ctx: ToolContext,
) -> ToolCallRecord:
    """Execute one tool_call from the LLM response.

    The LLM-shaped tool_call has:
        id: str
        type: "function"
        function: {name: str, arguments: str (JSON)}
    """
    name = tool_call.function.name
    args, parse_err = _parse_tool_arguments(tool_call.function.arguments)
    if parse_err is not None:
        result = ToolResult.failure(parse_err)
    else:
        result = await registry.invoke(name, args, ctx)
    return ToolCallRecord(name=name, arguments=args, result=result)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_tool_loop(
    messages: List[dict[str, Any]],
    *,
    llm: LLMCallable | None = None,
    llm_kwargs: dict[str, Any] | None = None,
    registry: ToolRegistry,
    ctx: ToolContext,
    max_iterations: int = 5,
    tool_choice: str = "auto",
) -> ToolLoopResult:
    """Run an LLM ↔ tool execution loop until a final answer is produced.

    The loop:
      1. Call LLM with ``messages`` + ``tools=registry.schemas()``
      2. If response has ``tool_calls``:
         - Append the assistant message (with tool_calls) to ``messages``
         - For each tool_call: execute via ``registry.invoke()``, append
           a role:tool message with the result
         - Increment iteration counter, repeat
      3. If response has no tool_calls: return ``final_content``
      4. If ``iterations >= max_iterations``: return with
         ``final_content=None`` and ``max_iterations_reached=True``

    ``llm_kwargs`` carries static config (model, api_key, api_base,
    temperature, max_tokens). The loop adds ``messages``, ``tools``,
    ``tool_choice`` per call — keys in ``llm_kwargs`` that collide
    with these are overridden.

    ``messages`` is mutated in place — the caller should pass a copy
    if it needs the original list preserved.

    Raises ``ValueError`` if ``max_iterations < 1``.
    """
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    if llm is None:
        llm = litellm.acompletion
    if llm_kwargs is None:
        llm_kwargs = {}

    tools_schema = registry.schemas()
    trace: list[ToolCallRecord] = []

    # Fast path: no tools registered → single LLM call, no loop.
    if not tools_schema:
        logger.debug("tool_loop: no tools registered, single LLM call")
        response = await llm(messages=messages, **llm_kwargs)
        msg = _extract_message(response)
        return ToolLoopResult(
            final_content=msg.content or "",
            tool_calls_trace=[],
            iterations=1,
            max_iterations_reached=False,
        )

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        response = await llm(
            messages=messages,
            tools=tools_schema,
            tool_choice=tool_choice,
            **llm_kwargs,
        )
        msg = _extract_message(response)

        if not _has_tool_calls(msg):
            # Final answer — exit loop.
            logger.debug(
                "tool_loop: final answer at iter=%d after %d tool calls",
                iteration,
                len(trace),
            )
            return ToolLoopResult(
                final_content=msg.content or "",
                tool_calls_trace=trace,
                iterations=iteration,
                max_iterations_reached=False,
            )

        # Append the assistant message (with tool_calls) to messages.
        messages.append(_assistant_message_to_dict(msg))

        # Execute each tool_call and append the result.
        for tc in msg.tool_calls:
            record = await _execute_tool_call(tc, registry, ctx)
            trace.append(record)
            tool_call_id = getattr(tc, "id", f"call_{len(trace)}")
            messages.append(_tool_result_message(tool_call_id, record.result))
            logger.debug(
                "tool_loop iter=%d call=%s ok=%s",
                iteration,
                record.name,
                record.result.ok,
            )

    # Hit max_iterations without a final answer.
    logger.warning(
        "tool_loop hit max_iterations=%d without final answer",
        max_iterations,
    )
    return ToolLoopResult(
        final_content=None,
        tool_calls_trace=trace,
        iterations=iteration,
        max_iterations_reached=True,
    )


# ---------------------------------------------------------------------------
# Convenience: build llm_kwargs from a BYOK StageConfig
# ---------------------------------------------------------------------------


def build_llm_kwargs(
    stage_config: Any | None = None,
    *,
    default_model: str | None = None,
    default_api_key: str | None = None,
    default_api_base: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """Build the ``llm_kwargs`` dict for ``run_tool_loop``.

    When ``stage_config`` is provided (BYOK), uses the user's api_base /
    api_key / model with the ``openai/`` prefix (so any OpenAI-compatible
    endpoint works). When None, uses the passed defaults from .env —
    ``default_model`` is required in this case.

    Reuses ``app.llm.clients._byok_kwargs`` for SSRF validation and the
    BYOK kwarg convention — single source of truth for the wire format.
    """
    if stage_config is not None:
        # Late import to avoid circular dependency at module load time.
        from app.llm.clients import _byok_kwargs

        kwargs = _byok_kwargs(stage_config)
        kwargs["temperature"] = temperature
        kwargs["max_tokens"] = max_tokens
        return kwargs

    if default_model is None:
        raise ValueError(
            "default_model is required when stage_config is None "
            "(no BYOK credentials supplied)"
        )

    kwargs: dict[str, Any] = {
        "model": default_model,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if default_api_key is not None:
        kwargs["api_key"] = default_api_key
    if default_api_base is not None:
        kwargs["api_base"] = default_api_base
    return kwargs


__all__ = [
    "LLMCallable",
    "ToolCallRecord",
    "ToolLoopResult",
    "build_llm_kwargs",
    "run_tool_loop",
]
