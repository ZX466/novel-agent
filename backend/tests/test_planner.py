"""Tests for app.planner — DAG spec, templates, PlannerAgent, Orchestrator.

Covers P0-plan-2: validates that the planner correctly decomposes a novel
premise into a sub-task DAG and that the orchestrator can drive that DAG
to completion. All tests are pure-Python (no LLM, no DB) — they exercise
the planner's data structures and dispatch logic.
"""
from __future__ import annotations

import pytest

from app.planner import (
    DAGValidationError,
    PlannerAgent,
    SubTask,
    SubTaskDAG,
    SubTaskStatus,
    TaskKind,
    TaskSpec,
    plan_novel,
)
from app.planner.orchestrator import (
    Orchestrator,
    _noop_handler,
    make_noop_orchestrator,
)
from app.planner.templates import (
    multi_chapter_template,
    single_chapter_template,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(
    tid: str,
    kind: TaskKind = TaskKind.OUTLINE,
    *,
    depends_on: tuple[str, ...] = (),
    expected_output_keys: tuple[str, ...] = (),
    inputs: dict | None = None,
) -> TaskSpec:
    return TaskSpec(
        task_id=tid,
        kind=kind,
        inputs=inputs or {},
        depends_on=depends_on,
        expected_output_keys=expected_output_keys,
    )


def _dag(*specs: TaskSpec) -> SubTaskDAG:
    return SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})


# ---------------------------------------------------------------------------
# TaskSpec — immutability
# ---------------------------------------------------------------------------


def test_task_spec_is_frozen():
    spec = _spec("a", inputs={"x": 1})
    with pytest.raises(Exception):
        spec.task_id = "b"  # type: ignore[misc]


def test_task_spec_defaults_are_empty():
    spec = _spec("a")
    assert spec.inputs == {}
    assert spec.depends_on == ()
    assert spec.expected_output_keys == ()


# ---------------------------------------------------------------------------
# SubTask — mutable wrapper
# ---------------------------------------------------------------------------


def test_subtask_initial_status_is_pending():
    sub = SubTask(spec=_spec("a"))
    assert sub.status is SubTaskStatus.PENDING
    assert sub.result is None
    assert sub.error is None


def test_subtask_proxies_spec_fields():
    sub = SubTask(spec=_spec("a", TaskKind.CHAPTER_DRAFT, depends_on=("x",)))
    assert sub.task_id == "a"
    assert sub.kind is TaskKind.CHAPTER_DRAFT
    assert sub.depends_on == ("x",)


# ---------------------------------------------------------------------------
# SubTaskDAG — validation
# ---------------------------------------------------------------------------


def test_dag_rejects_empty():
    with pytest.raises(DAGValidationError, match="at least one task"):
        SubTaskDAG(tasks={})


def test_dag_rejects_missing_dependency():
    with pytest.raises(DAGValidationError, match="depends on unknown task"):
        _dag(_spec("a", depends_on=("nonexistent",)))


def test_dag_rejects_self_cycle():
    with pytest.raises(DAGValidationError, match="cycle"):
        _dag(_spec("a", depends_on=("a",)))


def test_dag_rejects_two_node_cycle():
    with pytest.raises(DAGValidationError, match="cycle"):
        _dag(
            _spec("a", depends_on=("b",)),
            _spec("b", depends_on=("a",)),
        )


def test_dag_rejects_three_node_cycle():
    with pytest.raises(DAGValidationError, match="cycle"):
        _dag(
            _spec("a", depends_on=("c",)),
            _spec("b", depends_on=("a",)),
            _spec("c", depends_on=("b",)),
        )


def test_dag_accepts_acyclic_chain():
    dag = _dag(
        _spec("a"),
        _spec("b", depends_on=("a",)),
        _spec("c", depends_on=("b",)),
    )
    assert sorted(dag.task_ids) == ["a", "b", "c"]


def test_dag_accepts_diamond_dependency():
    """a → b, a → c, b → d, c → d (diamond) is acyclic."""
    dag = _dag(
        _spec("a"),
        _spec("b", depends_on=("a",)),
        _spec("c", depends_on=("a",)),
        _spec("d", depends_on=("b", "c")),
    )
    assert dag.is_complete() is False


# ---------------------------------------------------------------------------
# SubTaskDAG — ready_tasks()
# ---------------------------------------------------------------------------


def test_ready_tasks_returns_no_deps_first():
    dag = _dag(
        _spec("a"),
        _spec("b", depends_on=("a",)),
    )
    ready = dag.ready_tasks()
    assert [s.task_id for s in ready] == ["a"]


def test_ready_tasks_excludes_non_pending():
    dag = _dag(_spec("a"), _spec("b", depends_on=("a",)))
    dag.update_status("a", SubTaskStatus.RUNNING)
    # b is PENDING but dep a is not DONE; a is RUNNING (not PENDING).
    assert dag.ready_tasks() == []


def test_ready_tasks_after_dep_done():
    dag = _dag(_spec("a"), _spec("b", depends_on=("a",)))
    dag.update_status("a", SubTaskStatus.DONE)
    ready = dag.ready_tasks()
    assert [s.task_id for s in ready] == ["b"]


def test_ready_tasks_blocked_when_dep_failed():
    """A FAILED dep should NOT make the dependent ready (dep never reached DONE)."""
    dag = _dag(_spec("a"), _spec("b", depends_on=("a",)))
    dag.update_status("a", SubTaskStatus.FAILED, error="boom")
    assert dag.ready_tasks() == []


def test_ready_tasks_skipped_dep_does_not_unblock():
    """A SKIPPED dep is not DONE — dependent stays blocked."""
    dag = _dag(_spec("a"), _spec("b", depends_on=("a",)))
    dag.update_status("a", SubTaskStatus.SKIPPED)
    assert dag.ready_tasks() == []


def test_ready_tasks_returns_multiple_independent():
    dag = _dag(_spec("a"), _spec("b"), _spec("c"))
    ready_ids = sorted(s.task_id for s in dag.ready_tasks())
    assert ready_ids == ["a", "b", "c"]


def test_ready_tasks_empty_when_all_done():
    dag = _dag(_spec("a"))
    dag.update_status("a", SubTaskStatus.DONE)
    assert dag.ready_tasks() == []


# ---------------------------------------------------------------------------
# SubTaskDAG — is_complete()
# ---------------------------------------------------------------------------


def test_is_complete_false_when_any_pending():
    dag = _dag(_spec("a"), _spec("b"))
    assert dag.is_complete() is False


def test_is_complete_true_when_all_done():
    dag = _dag(_spec("a"), _spec("b"))
    dag.update_status("a", SubTaskStatus.DONE)
    dag.update_status("b", SubTaskStatus.DONE)
    assert dag.is_complete() is True


def test_is_complete_true_with_mixed_terminal_states():
    """DONE + FAILED + SKIPPED are all terminal."""
    dag = _dag(_spec("a"), _spec("b"), _spec("c"))
    dag.update_status("a", SubTaskStatus.DONE)
    dag.update_status("b", SubTaskStatus.FAILED, error="x")
    dag.update_status("c", SubTaskStatus.SKIPPED)
    assert dag.is_complete() is True


def test_is_complete_false_when_running():
    dag = _dag(_spec("a"))
    dag.update_status("a", SubTaskStatus.RUNNING)
    assert dag.is_complete() is False


# ---------------------------------------------------------------------------
# SubTaskDAG — get / update_status / summary
# ---------------------------------------------------------------------------


def test_get_returns_subtask():
    dag = _dag(_spec("a"))
    sub = dag.get("a")
    assert sub.task_id == "a"


def test_get_unknown_raises_keyerror():
    dag = _dag(_spec("a"))
    with pytest.raises(KeyError):
        dag.get("nope")


def test_update_status_records_result():
    dag = _dag(_spec("a"))
    sub = dag.update_status("a", SubTaskStatus.DONE, result={"k": "v"})
    assert sub.status is SubTaskStatus.DONE
    assert sub.result == {"k": "v"}


def test_update_status_records_error():
    dag = _dag(_spec("a"))
    sub = dag.update_status("a", SubTaskStatus.FAILED, error="boom")
    assert sub.status is SubTaskStatus.FAILED
    assert sub.error == "boom"


def test_summary_reports_counts():
    dag = _dag(_spec("a"), _spec("b"), _spec("c"))
    dag.update_status("a", SubTaskStatus.DONE)
    dag.update_status("b", SubTaskStatus.FAILED, error="x")
    # c stays PENDING
    summary = dag.summary()
    assert summary["total_tasks"] == 3
    assert summary["status_counts"]["done"] == 1
    assert summary["status_counts"]["failed"] == 1
    assert summary["status_counts"]["pending"] == 1
    assert summary["complete"] is False


# ---------------------------------------------------------------------------
# Templates — single_chapter_template
# ---------------------------------------------------------------------------


def test_single_chapter_template_has_eight_tasks():
    dag = single_chapter_template(premise="A detective solves a locked-room mystery.")
    assert len(dag.tasks) == 8


def test_single_chapter_template_task_ids():
    dag = single_chapter_template(premise="x")
    expected = {
        "outline",
        "world_setting",
        "character",
        "chapter_draft_1",
        "chapter_refine_1",
        "consistency_check",
        "final_polish",
        "safety_review",
    }
    assert set(dag.task_ids) == expected


def test_single_chapter_template_dependency_chain():
    dag = single_chapter_template(premise="x")
    # outline has no deps.
    assert dag.get("outline").depends_on == ()
    # world_setting & character depend on outline.
    assert dag.get("world_setting").depends_on == ("outline",)
    assert dag.get("character").depends_on == ("outline",)
    # chapter_draft_1 depends on all three setup tasks.
    assert set(dag.get("chapter_draft_1").depends_on) == {
        "outline", "world_setting", "character",
    }
    # chapter_refine_1 depends on its own draft.
    assert dag.get("chapter_refine_1").depends_on == ("chapter_draft_1",)
    # consistency → final_polish → safety_review chain.
    assert dag.get("consistency_check").depends_on == ("chapter_refine_1",)
    assert dag.get("final_polish").depends_on == ("consistency_check",)
    assert dag.get("safety_review").depends_on == ("final_polish",)


def test_single_chapter_template_premise_propagated():
    dag = single_chapter_template(premise="A summer on Mars.")
    assert dag.get("outline").spec.inputs["premise"] == "A summer on Mars."
    assert dag.get("world_setting").spec.inputs["premise"] == "A summer on Mars."


def test_single_chapter_template_target_words_in_draft():
    dag = single_chapter_template(premise="x", target_words=5000)
    assert dag.get("chapter_draft_1").spec.inputs["target_words"] == 5000


def test_single_chapter_template_all_tasks_have_output_keys():
    """Every task in the single-chapter template declares output contract."""
    dag = single_chapter_template(premise="x")
    for sub in dag.tasks.values():
        assert sub.spec.expected_output_keys, (
            f"Task {sub.task_id} missing expected_output_keys"
        )


def test_single_chapter_template_kinds():
    dag = single_chapter_template(premise="x")
    assert dag.get("outline").kind is TaskKind.OUTLINE
    assert dag.get("world_setting").kind is TaskKind.WORLD_SETTING
    assert dag.get("character").kind is TaskKind.CHARACTER
    assert dag.get("chapter_draft_1").kind is TaskKind.CHAPTER_DRAFT
    assert dag.get("chapter_refine_1").kind is TaskKind.CHAPTER_REFINE
    assert dag.get("consistency_check").kind is TaskKind.CONSISTENCY_CHECK
    assert dag.get("final_polish").kind is TaskKind.FINAL_POLISH
    assert dag.get("safety_review").kind is TaskKind.SAFETY_REVIEW


# ---------------------------------------------------------------------------
# Templates — multi_chapter_template
# ---------------------------------------------------------------------------


def test_multi_chapter_template_task_count():
    """3 setup + 2*N per-chapter + 3 final = 2*N + 6."""
    n = 3
    dag = multi_chapter_template(premise="x", chapter_count=n)
    assert len(dag.tasks) == 2 * n + 6  # 12


def test_multi_chapter_template_task_ids_for_n3():
    dag = multi_chapter_template(premise="x", chapter_count=3)
    expected = {
        "outline", "world_setting", "character",
        "chapter_draft_1", "chapter_refine_1",
        "chapter_draft_2", "chapter_refine_2",
        "chapter_draft_3", "chapter_refine_3",
        "consistency_check", "final_polish", "safety_review",
    }
    assert set(dag.task_ids) == expected


def test_multi_chapter_template_per_chapter_independence():
    """chapter_draft_2 must NOT depend on chapter_draft_1 — they're parallel."""
    dag = multi_chapter_template(premise="x", chapter_count=3)
    assert "chapter_draft_1" not in dag.get("chapter_draft_2").depends_on
    assert "chapter_refine_1" not in dag.get("chapter_draft_2").depends_on


def test_multi_chapter_template_each_draft_depends_on_setup():
    dag = multi_chapter_template(premise="x", chapter_count=3)
    for i in range(1, 4):
        deps = dag.get(f"chapter_draft_{i}").depends_on
        assert set(deps) == {"outline", "world_setting", "character"}


def test_multi_chapter_template_each_refine_depends_on_own_draft():
    dag = multi_chapter_template(premise="x", chapter_count=3)
    for i in range(1, 4):
        assert dag.get(f"chapter_refine_{i}").depends_on == (f"chapter_draft_{i}",)


def test_multi_chapter_template_consistency_depends_on_all_refines():
    dag = multi_chapter_template(premise="x", chapter_count=3)
    deps = dag.get("consistency_check").depends_on
    assert set(deps) == {"chapter_refine_1", "chapter_refine_2", "chapter_refine_3"}


def test_multi_chapter_template_chapter_count_in_outline_inputs():
    dag = multi_chapter_template(premise="x", chapter_count=5)
    assert dag.get("outline").spec.inputs["chapter_count"] == 5


def test_multi_chapter_template_chapter_indices_in_consistency():
    dag = multi_chapter_template(premise="x", chapter_count=3)
    assert dag.get("consistency_check").spec.inputs["chapter_indices"] == [1, 2, 3]


def test_multi_chapter_template_rejects_zero_chapters():
    with pytest.raises(ValueError, match="chapter_count"):
        multi_chapter_template(premise="x", chapter_count=0)


def test_multi_chapter_template_rejects_negative_chapters():
    with pytest.raises(ValueError, match="chapter_count"):
        multi_chapter_template(premise="x", chapter_count=-1)


def test_multi_chapter_template_n1_produces_setup_plus_two_plus_three():
    """N=1 should produce 3 + 2 + 3 = 8 tasks (same count as single-chapter
    template, though different IDs may differ)."""
    dag = multi_chapter_template(premise="x", chapter_count=1)
    assert len(dag.tasks) == 8


# ---------------------------------------------------------------------------
# PlannerAgent — plan()
# ---------------------------------------------------------------------------


def test_planner_agent_single_chapter():
    agent = PlannerAgent()
    dag = agent.plan(premise="A heist in Venice.", chapter_count=1)
    assert len(dag.tasks) == 8
    assert "chapter_draft_1" in dag.tasks


def test_planner_agent_multi_chapter():
    agent = PlannerAgent()
    dag = agent.plan(premise="A heist in Venice.", chapter_count=4)
    # 3 + 2*4 + 3 = 14
    assert len(dag.tasks) == 14


def test_planner_agent_strips_premise_whitespace():
    agent = PlannerAgent()
    dag = agent.plan(premise="  Spaced premise.  ", chapter_count=1)
    assert dag.get("outline").spec.inputs["premise"] == "Spaced premise."


def test_planner_agent_rejects_empty_premise():
    agent = PlannerAgent()
    with pytest.raises(ValueError, match="premise"):
        agent.plan(premise="", chapter_count=1)


def test_planner_agent_rejects_whitespace_only_premise():
    agent = PlannerAgent()
    with pytest.raises(ValueError, match="premise"):
        agent.plan(premise="   ", chapter_count=1)


def test_planner_agent_rejects_zero_chapters():
    agent = PlannerAgent()
    with pytest.raises(ValueError, match="chapter_count"):
        agent.plan(premise="x", chapter_count=0)


def test_planner_agent_rejects_negative_chapters():
    agent = PlannerAgent()
    with pytest.raises(ValueError, match="chapter_count"):
        agent.plan(premise="x", chapter_count=-3)


def test_planner_agent_target_words_propagated_to_draft():
    agent = PlannerAgent()
    dag = agent.plan(
        premise="x", chapter_count=1, target_words_per_chapter=7777,
    )
    assert dag.get("chapter_draft_1").spec.inputs["target_words"] == 7777


def test_plan_novel_module_convenience_matches_agent():
    """plan_novel() should produce the same DAG as a fresh PlannerAgent()."""
    agent = PlannerAgent()
    a = agent.plan(premise="x", chapter_count=2)
    b = plan_novel("x", chapter_count=2)
    # Same task set & topology.
    assert set(a.task_ids) == set(b.task_ids)


# ---------------------------------------------------------------------------
# Orchestrator — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_runs_simple_dag_to_completion():
    """Single-task DAG with a registered handler completes to DONE."""
    dag = _dag(
        TaskSpec(
            task_id="t1",
            kind=TaskKind.OUTLINE,
            expected_output_keys=("chapter_outline",),
        )
    )

    async def handler(sub, dag):
        return {"chapter_outline": "outline-text"}

    orch = Orchestrator(handlers={TaskKind.OUTLINE: handler})
    await orch.run(dag)
    assert dag.get("t1").status is SubTaskStatus.DONE
    assert dag.get("t1").result == {"chapter_outline": "outline-text"}


@pytest.mark.asyncio
async def test_orchestrator_runs_chain_in_order():
    """a → b → c chain: handlers must run in dependency order."""
    dag = _dag(
        TaskSpec(task_id="a", kind=TaskKind.OUTLINE, expected_output_keys=("o",)),
        TaskSpec(
            task_id="b",
            kind=TaskKind.CHARACTER,
            depends_on=("a",),
            expected_output_keys=("c",),
        ),
        TaskSpec(
            task_id="c",
            kind=TaskKind.CHAPTER_DRAFT,
            depends_on=("b",),
            expected_output_keys=("d",),
        ),
    )

    order: list[str] = []

    async def h_a(sub, dag):
        order.append("a")
        return {"o": "outline"}

    async def h_b(sub, dag):
        order.append("b")
        return {"c": "character"}

    async def h_c(sub, dag):
        order.append("c")
        return {"d": "draft"}

    orch = Orchestrator(handlers={
        TaskKind.OUTLINE: h_a,
        TaskKind.CHARACTER: h_b,
        TaskKind.CHAPTER_DRAFT: h_c,
    })
    await orch.run(dag)
    assert order == ["a", "b", "c"]
    assert dag.is_complete() is True


@pytest.mark.asyncio
async def test_orchestrator_handler_can_read_dep_result():
    """A handler can inspect the result of a completed dependency."""
    dag = _dag(
        TaskSpec(
            task_id="a",
            kind=TaskKind.OUTLINE,
            expected_output_keys=("chapter_outline",),
        ),
        TaskSpec(
            task_id="b",
            kind=TaskKind.CHARACTER,
            depends_on=("a",),
            expected_output_keys=("echo",),
        ),
    )

    async def h_a(sub, dag):
        return {"chapter_outline": "outline-text"}

    async def h_b(sub, dag):
        upstream = dag.get("a").result
        return {"echo": upstream["chapter_outline"]}

    orch = Orchestrator(handlers={
        TaskKind.OUTLINE: h_a,
        TaskKind.CHARACTER: h_b,
    })
    await orch.run(dag)
    assert dag.get("b").result == {"echo": "outline-text"}


# ---------------------------------------------------------------------------
# Orchestrator — failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_handler_exception_marks_failed():
    dag = _dag(
        TaskSpec(
            task_id="t1",
            kind=TaskKind.OUTLINE,
            expected_output_keys=("o",),
        )
    )

    async def bad(sub, dag):
        raise RuntimeError("handler exploded")

    orch = Orchestrator(handlers={TaskKind.OUTLINE: bad})
    await orch.run(dag)
    sub = dag.get("t1")
    assert sub.status is SubTaskStatus.FAILED
    assert sub.error is not None
    assert "RuntimeError" in sub.error
    assert "handler exploded" in sub.error


@pytest.mark.asyncio
async def test_orchestrator_missing_output_keys_marks_failed():
    dag = _dag(
        TaskSpec(
            task_id="t1",
            kind=TaskKind.OUTLINE,
            expected_output_keys=("chapter_outline", "extras"),
        )
    )

    async def partial(sub, dag):
        return {"chapter_outline": "x"}  # missing "extras"

    orch = Orchestrator(handlers={TaskKind.OUTLINE: partial})
    await orch.run(dag)
    sub = dag.get("t1")
    assert sub.status is SubTaskStatus.FAILED
    assert "extras" in (sub.error or "")


@pytest.mark.asyncio
async def test_orchestrator_no_handler_marks_failed():
    dag = _dag(
        TaskSpec(task_id="t1", kind=TaskKind.SAFETY_REVIEW),
    )
    orch = Orchestrator(handlers={})  # no handlers at all
    await orch.run(dag)
    sub = dag.get("t1")
    assert sub.status is SubTaskStatus.FAILED
    assert "No handler" in (sub.error or "")


@pytest.mark.asyncio
async def test_orchestrator_failed_dependency_blocks_dependents():
    """When a dep fails, dependents stay PENDING and the orchestrator
    loop exits (deadlock detected: no ready tasks, DAG not complete)."""
    dag = _dag(
        TaskSpec(
            task_id="a",
            kind=TaskKind.OUTLINE,
            expected_output_keys=("o",),
        ),
        TaskSpec(
            task_id="b",
            kind=TaskKind.CHARACTER,
            depends_on=("a",),
            expected_output_keys=("c",),
        ),
    )

    async def failing(sub, dag):
        raise RuntimeError("a fails")

    orch = Orchestrator(handlers={TaskKind.OUTLINE: failing})
    await orch.run(dag)
    # a FAILED (terminal), b PENDING (blocked) → DAG not complete.
    assert dag.get("a").status is SubTaskStatus.FAILED
    assert dag.get("b").status is SubTaskStatus.PENDING
    assert dag.is_complete() is False


@pytest.mark.asyncio
async def test_orchestrator_parallel_branches_continue_after_failure():
    """A failure in one branch does not block an independent branch."""
    dag = _dag(
        TaskSpec(
            task_id="a",
            kind=TaskKind.OUTLINE,
            expected_output_keys=("o",),
        ),
        TaskSpec(
            task_id="b",
            kind=TaskKind.CHARACTER,
            expected_output_keys=("c",),
        ),
    )

    async def fail(sub, dag):
        raise RuntimeError("a fails")

    async def ok(sub, dag):
        return {"c": "char"}

    orch = Orchestrator(handlers={
        TaskKind.OUTLINE: fail,
        TaskKind.CHARACTER: ok,
    })
    await orch.run(dag)
    assert dag.get("a").status is SubTaskStatus.FAILED
    assert dag.get("b").status is SubTaskStatus.DONE


# ---------------------------------------------------------------------------
# Orchestrator — noop helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_noop_handler_returns_empty_dict():
    sub = SubTask(spec=_spec("a"))
    result = await _noop_handler(sub, _dag(_spec("a")))
    assert result == {}


@pytest.mark.asyncio
async def test_noop_handler_rejects_tasks_with_output_keys():
    sub = SubTask(spec=_spec("a", expected_output_keys=("foo",)))
    dag = _dag(_spec("a", expected_output_keys=("foo",)))
    with pytest.raises(RuntimeError, match="expected_output_keys"):
        await _noop_handler(sub, dag)


def test_make_noop_orchestrator_has_all_kinds():
    orch = make_noop_orchestrator()
    # Internal: handlers dict covers every TaskKind.
    for kind in TaskKind:
        assert kind in orch._handlers


@pytest.mark.asyncio
async def test_make_noop_orchestrator_runs_dependency_free_dag():
    """DAG with no expected_output_keys and no deps runs to completion via noop."""
    dag = _dag(
        TaskSpec(task_id="a", kind=TaskKind.OUTLINE),
        TaskSpec(task_id="b", kind=TaskKind.CHARACTER),
    )
    orch = make_noop_orchestrator()
    await orch.run(dag)
    assert dag.get("a").status is SubTaskStatus.DONE
    assert dag.get("b").status is SubTaskStatus.DONE


@pytest.mark.asyncio
async def test_make_noop_orchestrator_fails_dag_with_output_contracts():
    """Noop handler rejects tasks that declare expected_output_keys —
    the orchestrator must mark them FAILED (not silently complete)."""
    dag = _dag(
        TaskSpec(
            task_id="a",
            kind=TaskKind.OUTLINE,
            expected_output_keys=("chapter_outline",),
        )
    )
    orch = make_noop_orchestrator()
    await orch.run(dag)
    assert dag.get("a").status is SubTaskStatus.FAILED


# ---------------------------------------------------------------------------
# Orchestrator — full template end-to-end (with stub handlers)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_runs_single_chapter_template_end_to_end():
    """End-to-end: single_chapter_template + stub handlers for every kind
    completes the whole DAG in topological order."""
    dag = single_chapter_template(premise="A noir detective story.")

    async def universal_handler(sub, dag):
        # Return a dict satisfying every template's expected_output_keys.
        return {key: f"stub-{sub.task_id}-{key}" for key in sub.spec.expected_output_keys}

    handlers = {kind: universal_handler for kind in TaskKind}
    orch = Orchestrator(handlers=handlers)
    await orch.run(dag)
    assert dag.is_complete() is True
    # No task should be PENDING/FAILED — all DONE.
    for sub in dag.tasks.values():
        assert sub.status is SubTaskStatus.DONE, (
            f"Task {sub.task_id} ended as {sub.status}: {sub.error}"
        )


@pytest.mark.asyncio
async def test_orchestrator_runs_multi_chapter_template_end_to_end():
    dag = multi_chapter_template(premise="x", chapter_count=3)

    async def universal_handler(sub, dag):
        return {key: f"stub-{sub.task_id}-{key}" for key in sub.spec.expected_output_keys}

    handlers = {kind: universal_handler for kind in TaskKind}
    orch = Orchestrator(handlers=handlers)
    await orch.run(dag)
    assert dag.is_complete() is True
    # All tasks reached DONE.
    statuses = {sub.status for sub in dag.tasks.values()}
    assert statuses == {SubTaskStatus.DONE}


@pytest.mark.asyncio
async def test_orchestrator_executes_in_topological_order():
    """Sanity: within a single-chapter DAG, ensure each task's deps are DONE
    before the task itself transitions to RUNNING. (Serial dispatch should
    guarantee this naturally.)"""
    dag = single_chapter_template(premise="x")

    async def universal_handler(sub, dag):
        # Verify invariant: every declared dep is already DONE.
        for dep_id in sub.depends_on:
            assert dag.get(dep_id).status is SubTaskStatus.DONE, (
                f"Task {sub.task_id} dispatched before dep {dep_id} was DONE"
            )
        return {key: f"v-{key}" for key in sub.spec.expected_output_keys}

    handlers = {kind: universal_handler for kind in TaskKind}
    orch = Orchestrator(handlers=handlers)
    await orch.run(dag)
    assert dag.is_complete() is True
