"""DAG orchestrator — executes a SubTaskDAG by dispatching ready tasks to
registered handlers.

Handler protocol:
    async def handler(subtask: SubTask, dag: SubTaskDAG) -> dict[str, Any]

Each handler returns a dict whose keys MUST include the
`expected_output_keys` of the task spec. The orchestrator does not
validate the dict contents (only the keys) — handlers own their
data contract.

Failure modes:
    - Handler raises       → SubTask.status=FAILED, error recorded, loop
                              continues with remaining ready tasks.
    - Handler returns
      missing output keys   → SubTask.status=FAILED, error message lists
                              the missing keys.
    - All remaining tasks
      become unreachable    → loop exits; their status stays PENDING
                              and is reported in `summary()`.

Concurrency:
    v1 dispatches tasks one at a time (serial). Per-layer parallelism
    can be added by replacing the `for ready in dag.ready_tasks()`
    loop with asyncio.gather once we have real handlers that benefit
    from concurrency. Serial-first keeps the order deterministic and
    makes failures easier to reproduce.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from app.planner.spec import (
    SubTask,
    SubTaskDAG,
    SubTaskStatus,
    TaskKind,
)

logger = logging.getLogger(__name__)

Handler = Callable[[SubTask, SubTaskDAG], Awaitable[dict]]


class Orchestrator:
    """Executes a SubTaskDAG via registered TaskKind handlers.

    Register handlers via `register(kind, fn)` or by passing a dict
    to the constructor. Unhandled kinds raise at dispatch time, not at
    registration — this lets templates reference kinds before their
    handlers are wired (useful for staging development).
    """

    def __init__(self, handlers: dict[TaskKind, Handler] | None = None) -> None:
        self._handlers: dict[TaskKind, Handler] = dict(handlers or {})

    def register(self, kind: TaskKind, handler: Handler) -> None:
        self._handlers[kind] = handler

    async def run(self, dag: SubTaskDAG) -> SubTaskDAG:
        """Drive the DAG to completion. Mutates task statuses in place.

        Returns the same DAG instance (for chaining / inspection).
        Continues after handler failures so unrelated branches can still
        complete. Tasks depending on a FAILED task remain PENDING
        (their deps never reach DONE) — they appear in the final
        summary as PENDING, signaling "blocked by failure".
        """
        while not dag.is_complete():
            ready = dag.ready_tasks()
            if not ready:
                # No runnable tasks and not complete → deadlock (a
                # failed dep is blocking the rest). Stop the loop.
                logger.warning(
                    "Orchestrator: no ready tasks but DAG not complete — stopping. "
                    "Summary: %s", dag.summary()
                )
                break
            # Serial dispatch (see module docstring for concurrency note).
            for sub in ready:
                await self._dispatch(dag, sub)
        return dag

    async def _dispatch(self, dag: SubTaskDAG, sub: SubTask) -> None:
        handler = self._handlers.get(sub.kind)
        if handler is None:
            dag.update_status(
                sub.task_id,
                SubTaskStatus.FAILED,
                error=f"No handler registered for kind={sub.kind.value}",
            )
            logger.error("No handler for task %s kind=%s", sub.task_id, sub.kind)
            return

        dag.update_status(sub.task_id, SubTaskStatus.RUNNING)
        logger.info("Dispatching task %s kind=%s", sub.task_id, sub.kind)
        try:
            result = await handler(sub, dag)
        except Exception as e:
            dag.update_status(
                sub.task_id, SubTaskStatus.FAILED, error=f"{type(e).__name__}: {e}"
            )
            logger.exception("Task %s failed", sub.task_id)
            return

        # Validate output contract.
        missing = [
            k for k in sub.spec.expected_output_keys
            if not (isinstance(result, dict) and k in result)
        ]
        if missing:
            dag.update_status(
                sub.task_id,
                SubTaskStatus.FAILED,
                error=f"Handler output missing keys: {missing}",
            )
            logger.error(
                "Task %s output missing keys %s — got keys %s",
                sub.task_id, missing, list(result.keys()) if isinstance(result, dict) else None,
            )
            return

        dag.update_status(
            sub.task_id, SubTaskStatus.DONE, result=result
        )
        logger.info("Task %s done — output keys: %s", sub.task_id, list(result.keys()))


# --- Default no-op handlers (for testing / bootstrapping) ------------------


async def _noop_handler(sub: SubTask, dag: SubTaskDAG) -> dict:
    """Returns an empty dict. Only valid for tasks with no expected_output_keys.

    Used by tests that want to drive the DAG topology without running
    real agent logic. Production code registers real handlers.
    """
    if sub.spec.expected_output_keys:
        raise RuntimeError(
            f"_noop_handler cannot satisfy expected_output_keys={sub.spec.expected_output_keys}"
        )
    return {}


def make_noop_orchestrator() -> Orchestrator:
    """Build an Orchestrator with _noop_handler for every TaskKind.

    Only useful for tests that exercise the DAG topology (dependency
    resolution, cycle detection, deadlock detection) without spinning
    up real agents.
    """
    return Orchestrator(
        handlers={kind: _noop_handler for kind in TaskKind}
    )
