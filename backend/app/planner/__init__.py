"""Planner subpackage — task decomposition for novel writing.

Decomposes a high-level novel premise into a DAG of concrete sub-tasks
that downstream agents (PlotterAgent / CharacterAgent / EditorAgent /
ContentSafetyAgent) can execute. The DAG is the single source of truth
for the orchestrator — agents do not improvise ordering.
"""
from app.planner.spec import (  # noqa: F401
    DAGValidationError,
    SubTask,
    SubTaskDAG,
    SubTaskStatus,
    TaskKind,
    TaskSpec,
)
from app.planner.agent import PlannerAgent, plan_novel  # noqa: F401
