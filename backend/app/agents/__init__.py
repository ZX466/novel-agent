"""Agent subpackage — role-specialized executors for the novel-writing DAG.

Public API:
  - BaseAgent: abstract base wrapping the three-stage pipeline
  - AgentResult: outcome of a three-stage run
  - PlotterAgent: handles OUTLINE / WORLD_SETTING / CONSISTENCY_CHECK
  - CharacterAgent: handles CHARACTER
  - EditorAgent: handles CHAPTER_DRAFT / CHAPTER_REFINE / FINAL_POLISH
  - make_novel_orchestrator: factory wiring all three agents into an Orchestrator

Each agent's `handle(subtask, dag)` method matches the orchestrator's
Handler protocol `(SubTask, SubTaskDAG) -> Awaitable[dict]` so they
can be registered directly via `orchestrator.register(TaskKind.X, agent.handle)`.

The agents wrap app.llm.clients.draft/refine/evaluate — the same
wrappers the LangGraph pipeline uses — so BYOK credentials and the
three-stage refinement loop are shared between the pipeline and the agents.
"""
from app.agents.base import (  # noqa: F401
    AgentResult,
    BaseAgent,
)
from app.agents.character import (  # noqa: F401
    CharacterAgent,
)
from app.agents.editor import (  # noqa: F401
    EditorAgent,
)
from app.agents.factory import (  # noqa: F401
    make_novel_orchestrator,
)
from app.agents.plotter import (  # noqa: F401
    PlotterAgent,
)
