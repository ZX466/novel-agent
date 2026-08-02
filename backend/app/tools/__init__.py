"""Tool subpackage — agent-callable tools with parameter validation.

Public API:
  - ToolContext: runtime resources (session, stage_config, novel_id)
  - ToolResult: success/failure envelope
  - Tool: abstract base class for tools
  - ToolRegistry: lookup + invoke + JSON Schema export
  - SearchLoreTool / GetCharacterTool / SaveChapterTool: built-ins
  - make_default_registry(): factory with all built-ins registered
  - run_tool_loop(): LLM ↔ tool execution loop (LangGraph-compatible)
  - ToolLoopResult / ToolCallRecord: loop outcome types
  - build_llm_kwargs(): helper to build llm_kwargs from StageConfig
"""
from app.tools.base import (  # noqa: F401
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
)
from app.tools.builtins import (  # noqa: F401
    GetCharacterTool,
    SaveChapterTool,
    SearchLoreTool,
    make_default_registry,
)
from app.tools.loop import (  # noqa: F401
    LLMCallable,
    ToolCallRecord,
    ToolLoopResult,
    build_llm_kwargs,
    run_tool_loop,
)
