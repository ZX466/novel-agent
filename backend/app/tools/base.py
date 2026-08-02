"""Tool registry — generic abstraction for agent-callable tools.

A tool is an async function with a typed parameter schema. The registry
wraps each tool with:

  - Parameter validation (pydantic) before dispatch
  - JSON Schema export for LLM function-calling (OpenAI tool format)
  - Exception isolation: tools return ToolResult(ok=False) instead of
    raising — handlers signal failure via the result type, and any
    exception that escapes is caught and converted to a generic error

Three pieces:

  - ToolContext: runtime resources (DB session, BYOK stage config,
    novel_id) passed to every tool invocation. One context type avoids
    N handler signatures.
  - ToolResult: success/failure envelope returned to the caller. `data`
    is always a dict so it serializes cleanly to JSON for LLM tool-call
    responses.
  - Tool: abstract base — subclasses declare `name`, `description`,
    `Params` (pydantic model), and implement `execute(params, ctx)`.

Tool handlers should NOT import resources globally — they receive
everything via ToolContext. This makes tools trivially testable with
MockAsyncSession and lets the orchestrator swap contexts per-task.
"""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import StageConfig


@dataclass(frozen=True)
class ToolContext:
    """Runtime resources passed to every tool invocation.

    `session` is required — every tool needs DB access. The other
    fields are optional because not every tool needs embeddings or
    a novel scope.

    `stage_config` carries the draft BYOK config (used for LLM calls
    within tools that invoke a chat model).

    `embedding_stage_config` carries an optional dedicated embedding
    BYOK config. When None, tools fall back to .env EMBEDD_* credentials.
    This keeps chat and embedding BYOK config separate — they are
    different concerns and may point at different providers.
    """

    session: AsyncSession
    stage_config: StageConfig | None = None
    novel_id: int | None = None
    embedding_stage_config: StageConfig | None = None


@dataclass
class ToolResult:
    """Envelope for tool execution outcome.

    `ok=False` indicates an expected error (validation failure, not
    found, invalid state). `ok=True` indicates success — the data
    dict is the tool's payload.

    Handlers SHOULD return ToolResult directly so they can include
    structured error context. If a handler raises, the registry
    catches the exception and wraps it as ToolResult(ok=False,
    error=...).
    """

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def success(cls, data: dict[str, Any]) -> "ToolResult":
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error: str) -> "ToolResult":
        return cls(ok=False, error=error)


class Tool(ABC):
    """Abstract tool definition.

    Subclasses MUST set the three class attributes and implement
    `execute`. The class itself is the singleton — instances are
    stateless (all state is in ToolContext / Params).
    """

    name: str
    description: str
    Params: type[BaseModel]

    async def execute(
        self, params: BaseModel, ctx: ToolContext
    ) -> ToolResult:
        raise NotImplementedError


class ToolRegistry:
    """Registry of available tools, indexed by name.

    Register via `register(tool)` (raises if a tool with the same name
    is already registered — duplicate registration is a bug). Look up
    via `get(name)` or batch-export schemas via `schemas()`.

    The registry does NOT enforce a global tool list — multiple
    registries can coexist (e.g. a "safe" registry for untrusted
    agents and a full registry for trusted orchestrator agents).
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(
                f"Tool {tool.name!r} already registered"
            )
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Tool {name!r} not registered")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict[str, Any]]:
        """Export OpenAI-style function-calling tool definitions.

        Format: ``[{"type": "function", "function": {"name", "description",
        "parameters": <json-schema>}}]`` — directly usable as the `tools`
        argument to litellm's `acompletion` / OpenAI's chat completions.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.Params.model_json_schema(),
                },
            }
            for tool in self._tools.values()
        ]

    async def invoke(
        self, name: str, params: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        """Validate params, dispatch to handler, return ToolResult.

        Catches:
          - Unknown tool name → ToolResult.failure("Tool not registered")
          - Pydantic ValidationError → ToolResult.failure with errors list
          - Handler exception → ToolResult.failure with exception type + msg

        Tools signal expected errors by returning ToolResult.failure
        directly — that path does not log a traceback. Unexpected
        exceptions are caught here and reported as a generic error.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(f"Tool {name!r} not registered")
        try:
            validated = tool.Params.model_validate(params)
        except ValidationError as e:
            return ToolResult.failure(
                f"Invalid params for {name}: {e.error_count()} error(s): "
                f"{[err['msg'] for err in e.errors()]}"
            )
        try:
            return await tool.execute(validated, ctx)
        except Exception as e:
            return ToolResult.failure(
                f"{type(e).__name__} in tool {name}: {e}"
            )
