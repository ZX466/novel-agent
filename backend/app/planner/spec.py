"""Task specification data structures for the planner.

Three core types:
  - TaskSpec:   immutable description of a single sub-task (kind + inputs)
  - SubTask:     TaskSpec + runtime status (pending / running / done / failed)
  - SubTaskDAG:  collection of SubTasks with topological validation

All dataclasses use `frozen=True` for TaskSpec (immutable spec) and
mutable for SubTask (status transitions during execution). The DAG is
constructed immutable — once built, its topology cannot change, only
the per-task status fields mutate.

TaskKind is an enum to make pattern-matching in the orchestrator safe.
Adding a new kind requires updating both the enum and the PlannerAgent
templates — explicit over implicit so a typo at the call site fails
loudly at import time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskKind(str, Enum):
    """Enumeration of supported sub-task kinds.

    Adding a new kind: add the enum value, then handle it in
    `app.pipeline.orchestrator.execute_subtask()` and any templates
    in `app.planner.templates`.
    """

    OUTLINE = "outline"                      # generate chapter outline
    WORLD_SETTING = "world_setting"          # build a lore entry
    CHARACTER = "character"                  # create/refine a character profile
    CHAPTER_DRAFT = "chapter_draft"           # write a chapter first draft
    CHAPTER_REFINE = "chapter_refine"        # refine based on feedback
    CONSISTENCY_CHECK = "consistency_check"  # cross-chapter consistency
    FINAL_POLISH = "final_polish"            # style/voice pass
    SAFETY_REVIEW = "safety_review"          # content safety check
    REFLECTION = "reflection"                # self-reflection on a refined/polished chapter


class SubTaskStatus(str, Enum):
    """Lifecycle of a sub-task within the DAG."""

    PENDING = "pending"
    READY = "ready"        # all deps satisfied, ready to dispatch
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TaskSpec:
    """Immutable specification of a single sub-task.

    `kind` selects which agent/handler runs the task.
    `inputs` is a free-form dict — the handler is responsible for
    validating its shape.
    `depends_on` lists task_id values that must reach status=DONE
    before this task can be dispatched. The DAG validates that every
    dependency id exists and that no cycle is introduced.
    `expected_output_keys` is a contract: the handler MUST return a
    dict containing at least these keys. Used by the orchestrator
    to short-circuit failed runs whose output is incomplete.
    """

    task_id: str
    kind: TaskKind
    inputs: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    expected_output_keys: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class SubTask:
    """A TaskSpec with mutable runtime status.

    The spec field is immutable; only status / result / error mutate.
    Keeping spec separate prevents accidental mutation of the plan
    during execution.
    """

    spec: TaskSpec
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None

    @property
    def task_id(self) -> str:
        return self.spec.task_id

    @property
    def kind(self) -> TaskKind:
        return self.spec.kind

    @property
    def depends_on(self) -> tuple[str, ...]:
        return self.spec.depends_on


class DAGValidationError(ValueError):
    """Raised when a SubTaskDAG is constructed with an invalid topology."""


@dataclass
class SubTaskDAG:
    """A validated directed acyclic graph of SubTasks.

    Construction validates:
      - all task_ids are unique
      - all depends_on references point to existing task_ids
      - no cycles (Kahn's algorithm)
      - at least one task exists

    Once built, the DAG exposes:
      - task_ids:                list of all task ids
      - ready_tasks():           tasks with all deps DONE, currently PENDING
      - is_complete():           True when all tasks are DONE/SKIPPED/FAILED
      - get(task_id):            SubTask lookup
      - update_status(id, st, result=None, error=None): mutate one task
    """

    tasks: dict[str, SubTask] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validation pass: unique ids + valid dependencies.
        if not self.tasks:
            raise DAGValidationError("DAG must contain at least one task")
        # All depends_on targets must exist.
        for tid, sub in self.tasks.items():
            for dep in sub.depends_on:
                if dep not in self.tasks:
                    raise DAGValidationError(
                        f"Task {tid!r} depends on unknown task {dep!r}"
                    )
        # Cycle detection via Kahn's algorithm.
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        """Raise DAGValidationError if the graph has a cycle."""
        in_degree = {tid: 0 for tid in self.tasks}
        # Build forward edges: dep -> task (task depends on dep).
        edges: dict[str, list[str]] = {tid: [] for tid in self.tasks}
        for tid, sub in self.tasks.items():
            for dep in sub.depends_on:
                edges[dep].append(tid)
                in_degree[tid] += 1
        # Standard Kahn's: drain nodes with in_degree 0.
        queue = [tid for tid, d in in_degree.items() if d == 0]
        visited = 0
        while queue:
            node = queue.pop()
            visited += 1
            for nxt in edges[node]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)
        if visited != len(self.tasks):
            raise DAGValidationError(
                "DAG contains a cycle — cannot topologically sort"
            )

    @property
    def task_ids(self) -> list[str]:
        return list(self.tasks.keys())

    def get(self, task_id: str) -> SubTask:
        if task_id not in self.tasks:
            raise KeyError(f"Task {task_id!r} not in DAG")
        return self.tasks[task_id]

    def ready_tasks(self) -> list[SubTask]:
        """Return PENDING tasks whose dependencies are all DONE.

        Does not return READY/RUNNING/DONE/FAILED tasks — the orchestrator
        only dispatches transitions from PENDING → READY.
        """
        ready: list[SubTask] = []
        for sub in self.tasks.values():
            if sub.status != SubTaskStatus.PENDING:
                continue
            deps_ok = all(
                self.tasks[dep].status == SubTaskStatus.DONE
                for dep in sub.depends_on
            )
            if deps_ok:
                ready.append(sub)
        return ready

    def is_complete(self) -> bool:
        """True when no task is PENDING/READY/RUNNING."""
        terminal = {
            SubTaskStatus.DONE,
            SubTaskStatus.FAILED,
            SubTaskStatus.SKIPPED,
        }
        return all(sub.status in terminal for sub in self.tasks.values())

    def update_status(
        self,
        task_id: str,
        status: SubTaskStatus,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> SubTask:
        """Mutate a single task's status. Returns the updated SubTask."""
        sub = self.get(task_id)
        sub.status = status
        if result is not None:
            sub.result = result
        if error is not None:
            sub.error = error
        return sub

    def summary(self) -> dict[str, Any]:
        """Snapshot for logging / API responses. Does not include results
        (may contain sensitive content)."""
        counts: dict[str, int] = {}
        for sub in self.tasks.values():
            counts[sub.status.value] = counts.get(sub.status.value, 0) + 1
        return {
            "total_tasks": len(self.tasks),
            "status_counts": counts,
            "complete": self.is_complete(),
        }
