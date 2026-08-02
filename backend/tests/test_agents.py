"""Tests for app.agents — PlotterAgent / CharacterAgent / EditorAgent + factory.

Covers P1-agent-1: validates the role-specialized agents that wrap the
three-stage pipeline (draft → refine → evaluate). All tests are pure
Python — the LLM wrappers (app.llm.clients.draft/refine/evaluate) are
mocked via `unittest.mock.patch` so no real LLM calls are made.

Test surface:
  - BaseAgent: _parse_eval, _pick_stage, _dep_results, _format_deps,
    _run_three_stage (early-exit + max_iters + BYOK propagation)
  - PlotterAgent: OUTLINE / WORLD_SETTING / CONSISTENCY_CHECK + rejections
  - CharacterAgent: CHARACTER + rejections
  - EditorAgent: CHAPTER_DRAFT / CHAPTER_REFINE / FINAL_POLISH + rejections
  - make_novel_orchestrator: 7 handlers registered, SAFETY_REVIEW reserved
  - E2E: orchestrator drives a single-chapter DAG with mocked LLM
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import (
    AgentResult,
    BaseAgent,
    CharacterAgent,
    EditorAgent,
    PlotterAgent,
    make_novel_orchestrator,
)
from app.agents.base import _parse_eval
from app.planner.orchestrator import Orchestrator
from app.planner.spec import (
    SubTask,
    SubTaskDAG,
    SubTaskStatus,
    TaskKind,
    TaskSpec,
)
from app.planner.templates import single_chapter_template
from app.schemas.chat import ProviderConfig, StageConfig


# ---------------------------------------------------------------------------
# Helpers — fake litellm response shape
# ---------------------------------------------------------------------------


def _fake_llm_response(content: str):
    """Build an object shaped like a litellm ChatCompletion response.

    Only the attributes the agents read are populated: `.choices[0].message.content`.
    Uses SimpleNamespace so attribute access works without constructing a
    Pydantic model.
    """
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _eval_response(score: float, feedback: str = "ok"):
    """Build a JSON evaluator response."""
    return _fake_llm_response(
        '{"score": ' + str(score) + ', "feedback": "' + feedback + '"}'
    )


def _make_subtask(
    *,
    task_id: str = "t1",
    kind: TaskKind = TaskKind.OUTLINE,
    inputs: dict | None = None,
    depends_on: tuple[str, ...] = (),
    expected_output_keys: tuple[str, ...] = ("chapter_outline",),
) -> tuple[SubTask, SubTaskDAG]:
    """Build a single-task DAG (plus optional dependency tasks).

    Returns (the target SubTask, the DAG containing it). Use this for
    agent.handle() tests where the DAG is mostly a carrier for dep results.
    """
    specs = [
        TaskSpec(
            task_id=task_id,
            kind=kind,
            inputs=inputs or {},
            depends_on=depends_on,
            expected_output_keys=expected_output_keys,
        )
    ]
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
    return dag.get(task_id), dag


def _make_dag_with_dep_results(
    *,
    target_id: str,
    target_kind: TaskKind,
    target_inputs: dict,
    target_keys: tuple[str, ...],
    dep_results: dict[str, dict],
) -> tuple[SubTask, SubTaskDAG]:
    """Build a DAG where deps are already DONE with the given results.

    `dep_results` is {dep_id: result_dict}. Each dep is a minimal task
    with kind=OUTLINE (kind doesn't matter for the test — only its result
    is read) and status=DONE, result set.
    """
    specs = []
    for dep_id in dep_results:
        specs.append(
            TaskSpec(
                task_id=dep_id,
                kind=TaskKind.OUTLINE,
                inputs={},
                expected_output_keys=tuple(dep_results[dep_id].keys()),
            )
        )
    specs.append(
        TaskSpec(
            task_id=target_id,
            kind=target_kind,
            inputs=target_inputs,
            depends_on=tuple(dep_results.keys()),
            expected_output_keys=target_keys,
        )
    )
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
    for dep_id, result in dep_results.items():
        dag.update_status(dep_id, SubTaskStatus.DONE, result=result)
    return dag.get(target_id), dag


def _byok_provider() -> ProviderConfig:
    """A BYOK provider config for tests that exercise stage propagation."""
    return ProviderConfig(
        draft=StageConfig(
            api_base="https://draft.example.com/v1",
            api_key="sk-draft-xxx",
            model="draft-model",
        ),
        refine=StageConfig(
            api_base="https://refine.example.com/v1",
            api_key="sk-refine-xxx",
            model="refine-model",
        ),
        evaluate=StageConfig(
            api_base="https://eval.example.com/v1",
            api_key="sk-eval-xxx",
            model="eval-model",
        ),
    )


# ---------------------------------------------------------------------------
# AgentResult dataclass
# ---------------------------------------------------------------------------


def test_agent_result_defaults():
    r = AgentResult(content="hello")
    assert r.content == "hello"
    assert r.score == 0.0
    assert r.feedback == ""
    assert r.iterations == 0
    assert r.raw_eval == ""


def test_agent_result_explicit_fields():
    r = AgentResult(
        content="text",
        score=0.92,
        feedback="good",
        iterations=2,
        raw_eval='{"score": 0.92}',
    )
    assert r.score == 0.92
    assert r.iterations == 2


# ---------------------------------------------------------------------------
# _parse_eval — JSON, markdown-fenced, fallback
# ---------------------------------------------------------------------------


def test_parse_eval_clean_json():
    score, feedback = _parse_eval('{"score": 0.85, "feedback": "good"}')
    assert score == 0.85
    assert feedback == "good"


def test_parse_eval_markdown_fenced_json():
    raw = '```json\n{"score": 0.9, "feedback": "nice"}\n```'
    score, feedback = _parse_eval(raw)
    assert score == 0.9
    assert feedback == "nice"


def test_parse_eval_bare_fenced_json():
    raw = '```\n{"score": 0.5, "feedback": "meh"}\n```'
    score, feedback = _parse_eval(raw)
    assert score == 0.5
    assert feedback == "meh"


def test_parse_eval_missing_feedback_key_defaults_to_empty():
    score, feedback = _parse_eval('{"score": 0.7}')
    assert score == 0.7
    assert feedback == ""


def test_parse_eval_invalid_json_falls_back_to_regex():
    """Non-JSON text — regex extracts the first number as score."""
    raw = "I would give this a 0.6 out of 1.0 because reasons."
    score, feedback = _parse_eval(raw)
    assert score == 0.6
    assert "0.6" in feedback or "reasons" in feedback


def test_parse_eval_no_numbers_returns_zero_score():
    score, feedback = _parse_eval("no numbers here")
    assert score == 0.0
    assert feedback == "no numbers here"


def test_parse_eval_empty_string():
    score, feedback = _parse_eval("")
    assert score == 0.0
    assert feedback == ""


def test_parse_eval_scale_echo_does_not_steal_leading_zero():
    """Models echoing '0.0-1.0 scale' before the real score must not yield
    0.0 — that would force needless refine iterations."""
    score, _ = _parse_eval("On a 0.0-1.0 scale, score 0.85. Good prose.")
    assert score == 0.85


def test_parse_eval_embedded_json_in_prose():
    score, feedback = _parse_eval(
        'Here is my review: {"score": 0.9, "feedback": "nice"} thanks'
    )
    assert score == 0.9
    assert feedback == "nice"


# ---------------------------------------------------------------------------
# BaseAgent — abstract handle + helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_agent_handle_raises_not_implemented():
    agent = BaseAgent()
    sub, dag = _make_subtask()
    with pytest.raises(NotImplementedError):
        await agent.handle(sub, dag)


def test_pick_stage_returns_none_without_provider_config():
    agent = BaseAgent()
    assert agent._pick_stage("draft") is None
    assert agent._pick_stage("refine") is None
    assert agent._pick_stage("evaluate") is None


def test_pick_stage_returns_correct_stage_with_provider_config():
    cfg = _byok_provider()
    agent = BaseAgent(provider_config=cfg)
    assert agent._pick_stage("draft") is cfg.draft
    assert agent._pick_stage("refine") is cfg.refine
    assert agent._pick_stage("evaluate") is cfg.evaluate


def test_pick_stage_unknown_stage_returns_none():
    """Asking for a stage that doesn't exist on ProviderConfig returns None."""
    cfg = _byok_provider()
    agent = BaseAgent(provider_config=cfg)
    assert agent._pick_stage("nonexistent") is None


def test_dep_results_collects_done_deps():
    """_dep_results pulls result dicts from DONE dependencies."""
    target, _ = _make_dag_with_dep_results(
        target_id="target",
        target_kind=TaskKind.WORLD_SETTING,
        target_inputs={"premise": "x"},
        target_keys=("world_entries",),
        dep_results={
            "outline": {"chapter_outline": "Ch1: intro\nCh2: conflict"},
            "character": {"characters": "Detective Chen"},
        },
    )
    # Rebuild DAG with the target inside (helper includes deps + target).
    # Reuse the dag from helper:
    dag = target.spec  # not used; we want the parent DAG
    # Actually we need the dag. Re-do this with a direct construction:
    specs = [
        TaskSpec(
            task_id="outline",
            kind=TaskKind.OUTLINE,
            inputs={},
            expected_output_keys=("chapter_outline",),
        ),
        TaskSpec(
            task_id="character",
            kind=TaskKind.CHARACTER,
            inputs={},
            expected_output_keys=("characters",),
        ),
        TaskSpec(
            task_id="target",
            kind=TaskKind.WORLD_SETTING,
            inputs={"premise": "x"},
            depends_on=("outline", "character"),
            expected_output_keys=("world_entries",),
        ),
    ]
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
    dag.update_status("outline", SubTaskStatus.DONE, result={"chapter_outline": "Ch1"})
    dag.update_status("character", SubTaskStatus.DONE, result={"characters": "X"})
    target = dag.get("target")

    agent = BaseAgent()
    deps = agent._dep_results(target, dag)
    assert set(deps.keys()) == {"outline", "character"}
    assert deps["outline"] == {"chapter_outline": "Ch1"}
    assert deps["character"] == {"characters": "X"}


def test_dep_results_skips_pending_deps():
    """Deps without results are omitted — caller doesn't get None entries."""
    specs = [
        TaskSpec(
            task_id="dep1",
            kind=TaskKind.OUTLINE,
            inputs={},
            expected_output_keys=("chapter_outline",),
        ),
        TaskSpec(
            task_id="dep2",
            kind=TaskKind.CHARACTER,
            inputs={},
            expected_output_keys=("characters",),
        ),
        TaskSpec(
            task_id="target",
            kind=TaskKind.WORLD_SETTING,
            inputs={"premise": "x"},
            depends_on=("dep1", "dep2"),
            expected_output_keys=("world_entries",),
        ),
    ]
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
    # Only dep1 is DONE; dep2 is still PENDING.
    dag.update_status("dep1", SubTaskStatus.DONE, result={"chapter_outline": "Ch1"})

    agent = BaseAgent()
    deps = agent._dep_results(dag.get("target"), dag)
    assert list(deps.keys()) == ["dep1"]
    assert deps["dep1"] == {"chapter_outline": "Ch1"}


def test_dep_results_empty_when_no_deps():
    """No deps → empty dict."""
    sub, dag = _make_subtask()
    agent = BaseAgent()
    deps = agent._dep_results(sub, dag)
    assert deps == {}


def test_format_deps_empty_returns_empty_string():
    agent = BaseAgent()
    assert agent._format_deps({}) == ""


def test_format_deps_dict_results():
    agent = BaseAgent()
    deps = {
        "outline": {"chapter_outline": "Ch1: intro\nCh2: conflict"},
        "character": {"characters": "Detective Chen"},
    }
    out = agent._format_deps(deps)
    assert "Context from prior tasks:" in out
    assert "--- outline ---" in out
    assert "--- character ---" in out
    assert "chapter_outline: Ch1: intro" in out
    assert "characters: Detective Chen" in out


def test_format_deps_truncates_long_values():
    agent = BaseAgent()
    long_val = "x" * 1000
    deps = {"outline": {"chapter_outline": long_val}}
    out = agent._format_deps(deps)
    # The truncated value should be 500 chars + "..."
    assert "..." in out
    # The full 1000 chars should NOT appear (only the 500-char prefix):
    assert long_val not in out
    assert long_val[:500] in out


def test_format_deps_non_dict_value():
    """Non-dict dep result is formatted as a string."""
    agent = BaseAgent()
    deps = {"outline": "just a string"}
    out = agent._format_deps(deps)
    assert "--- outline ---" in out
    assert "just a string" in out


# ---------------------------------------------------------------------------
# BaseAgent._run_three_stage — draft → refine → evaluate loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_three_stage_high_score_first_eval_exits_early():
    """Draft → 1 refine → eval(score=0.9 ≥ 0.8) → return after 1 iteration."""
    agent = BaseAgent(max_iters=3, score_threshold=0.8)
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("draft v1")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined v1")
        )) as m_refine,
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.9, "great")
        )) as m_eval,
    ):
        result = await agent._run_three_stage("sys", "user")

    assert result.content == "refined v1"
    assert result.score == 0.9
    assert result.feedback == "great"
    assert result.iterations == 1
    assert m_draft.await_count == 1
    assert m_refine.await_count == 1
    assert m_eval.await_count == 1


@pytest.mark.asyncio
async def test_run_three_stage_never_meets_threshold_runs_max_iters():
    """All iterations return score=0.5 < 0.8 → runs max_iters times."""
    agent = BaseAgent(max_iters=3, score_threshold=0.8)
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("draft v1")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            side_effect=[
                _fake_llm_response("refined v1"),
                _fake_llm_response("refined v2"),
                _fake_llm_response("refined v3"),
            ]
        )) as m_refine,
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "needs work")
        )) as m_eval,
    ):
        result = await agent._run_three_stage("sys", "user")

    assert result.score == 0.5
    assert result.iterations == 3
    assert result.content == "refined v3"
    assert m_refine.await_count == 3
    assert m_eval.await_count == 3


@pytest.mark.asyncio
async def test_run_three_stage_per_call_overrides_take_precedence():
    """max_iters / score_threshold overrides win over instance defaults."""
    agent = BaseAgent(max_iters=5, score_threshold=0.95)
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("draft")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.7, "ok")
        )) as m_eval,
    ):
        result = await agent._run_three_stage(
            "sys", "user", max_iters=1, score_threshold=0.99
        )
    # max_iters=1 → only one refine pass.
    assert result.iterations == 1
    assert result.score == 0.7
    # threshold=0.99 not met, so we hit the max_iters cap.
    assert m_eval.await_count == 1


@pytest.mark.asyncio
async def test_run_three_stage_passes_byok_stage_configs():
    """BYOK provider_config — each stage gets its own StageConfig."""
    cfg = _byok_provider()
    agent = BaseAgent(provider_config=cfg, max_iters=1, score_threshold=0.99)
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("draft")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )) as m_refine,
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )) as m_eval,
    ):
        await agent._run_three_stage("sys", "user")

    # Each LLM call should receive stage_config=<corresponding StageConfig>.
    assert m_draft.call_args.kwargs["stage_config"] is cfg.draft
    assert m_refine.call_args.kwargs["stage_config"] is cfg.refine
    assert m_eval.call_args.kwargs["stage_config"] is cfg.evaluate


@pytest.mark.asyncio
async def test_run_three_stage_passes_none_when_no_byok():
    """No provider_config — all stages get stage_config=None (env fallback)."""
    agent = BaseAgent(max_iters=1, score_threshold=0.99)
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("draft")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )) as m_refine,
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )) as m_eval,
    ):
        await agent._run_three_stage("sys", "user")

    assert m_draft.call_args.kwargs["stage_config"] is None
    assert m_refine.call_args.kwargs["stage_config"] is None
    assert m_eval.call_args.kwargs["stage_config"] is None


@pytest.mark.asyncio
async def test_run_three_stage_includes_feedback_in_subsequent_refine():
    """After eval gives feedback, the next refine call should include it."""
    agent = BaseAgent(max_iters=2, score_threshold=0.99)
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("draft")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            side_effect=[
                _fake_llm_response("refined v1"),
                _fake_llm_response("refined v2"),
            ]
        )) as m_refine,
        patch("app.agents.base.llm_evaluate", AsyncMock(
            side_effect=[
                _eval_response(0.4, "fix the pacing"),
                _eval_response(0.6, "better"),
            ]
        )),
    ):
        result = await agent._run_three_stage("sys", "user")

    assert result.iterations == 2
    # Second refine call's user message should mention the prior feedback.
    second_call_user_msg = m_refine.call_args_list[1].args[0][1]["content"]
    assert "fix the pacing" in second_call_user_msg


@pytest.mark.asyncio
async def test_run_three_stage_custom_refine_system():
    """Custom refine_system is used as the system prompt for refine calls."""
    agent = BaseAgent(max_iters=1, score_threshold=0.99)
    custom = "You are a custom editor. Be terse."
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("draft")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )) as m_refine,
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        await agent._run_three_stage("sys", "user", refine_system=custom)

    refine_system = m_refine.call_args.args[0][0]["content"]
    assert refine_system == custom


@pytest.mark.asyncio
async def test_run_three_stage_eval_raw_eval_captured_in_result():
    agent = BaseAgent(max_iters=1, score_threshold=0.99)
    raw = '{"score": 0.55, "feedback": "ok"}'
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("draft")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_fake_llm_response(raw)
        )),
    ):
        result = await agent._run_three_stage("sys", "user")

    assert result.raw_eval == raw


# ---------------------------------------------------------------------------
# PlotterAgent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plotter_handle_outline_returns_chapter_outline():
    agent = PlotterAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="outline",
        kind=TaskKind.OUTLINE,
        inputs={"premise": "A detective solves a locked-room mystery.", "chapter_count": 3},
        expected_output_keys=("chapter_outline",),
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("1. Ch1: Setup\n2. Ch2: Clue\n3. Ch3: Resolution")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined outline")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.6, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert "chapter_outline" in result
    assert result["chapter_outline"] == "refined outline"


@pytest.mark.asyncio
async def test_plotter_handle_outline_passes_premise_and_count_to_draft():
    agent = PlotterAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="outline",
        kind=TaskKind.OUTLINE,
        inputs={"premise": "A detective story.", "chapter_count": 5},
        expected_output_keys=("chapter_outline",),
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("outline")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    # The draft call's user message should mention premise + chapter_count.
    draft_user_msg = m_draft.call_args.args[0][1]["content"]
    assert "A detective story." in draft_user_msg
    assert "5" in draft_user_msg


@pytest.mark.asyncio
async def test_plotter_handle_outline_defaults_missing_inputs():
    """Missing premise/chapter_count default to "" / 1."""
    agent = PlotterAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="outline",
        kind=TaskKind.OUTLINE,
        inputs={},  # no premise, no chapter_count
        expected_output_keys=("chapter_outline",),
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("outline")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    # Defaults don't crash; still produces output.
    assert result["chapter_outline"] == "refined"
    # User prompt still gets formatted (with empty premise / 1 chapter).
    user_msg = m_draft.call_args.args[0][1]["content"]
    assert "Number of chapters: 1" in user_msg


@pytest.mark.asyncio
async def test_plotter_handle_world_setting_returns_world_entries():
    agent = PlotterAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_dag_with_dep_results(
        target_id="world_setting",
        target_kind=TaskKind.WORLD_SETTING,
        target_inputs={"premise": "scifi world"},
        target_keys=("world_entries",),
        dep_results={"outline": {"chapter_outline": "Ch1: intro"}},
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("world entries")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined world entries")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["world_entries"] == "refined world entries"
    # Draft user prompt should contain the dep context.
    draft_user_msg = m_draft.call_args.args[0][1]["content"]
    assert "Context from prior tasks:" in draft_user_msg
    assert "Ch1: intro" in draft_user_msg


@pytest.mark.asyncio
async def test_plotter_handle_consistency_check_returns_issues_and_score():
    agent = PlotterAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_dag_with_dep_results(
        target_id="consistency_check",
        target_kind=TaskKind.CONSISTENCY_CHECK,
        target_inputs={"chapter_indices": [1, 2]},
        target_keys=("issues", "score"),
        dep_results={
            "chapter_refine_1": {"content_text": "Chapter 1 text..."},
            "chapter_refine_2": {"content_text": "Chapter 2 text..."},
        },
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("Inconsistency: name spelling differs")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("Refined issues list")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.72, "two issues")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["issues"] == "Refined issues list"
    assert result["score"] == 0.72


@pytest.mark.asyncio
async def test_plotter_rejects_character_kind():
    agent = PlotterAgent()
    sub, dag = _make_subtask(
        task_id="char",
        kind=TaskKind.CHARACTER,
        inputs={"premise": "x", "count": 2},
        expected_output_keys=("characters",),
    )
    with pytest.raises(ValueError, match="PlotterAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_plotter_rejects_chapter_draft_kind():
    agent = PlotterAgent()
    sub, dag = _make_subtask(
        task_id="draft",
        kind=TaskKind.CHAPTER_DRAFT,
        inputs={"chapter_index": 1, "target_words": 1000},
        expected_output_keys=("content_text", "summary"),
    )
    with pytest.raises(ValueError, match="PlotterAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_plotter_rejects_chapter_refine_kind():
    agent = PlotterAgent()
    sub, dag = _make_subtask(
        task_id="refine",
        kind=TaskKind.CHAPTER_REFINE,
        inputs={"chapter_index": 1},
        expected_output_keys=("content_text",),
    )
    with pytest.raises(ValueError, match="PlotterAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_plotter_rejects_final_polish_kind():
    agent = PlotterAgent()
    sub, dag = _make_subtask(
        task_id="polish",
        kind=TaskKind.FINAL_POLISH,
        inputs={"chapter_indices": [1]},
        expected_output_keys=("content_text",),
    )
    with pytest.raises(ValueError, match="PlotterAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_plotter_rejects_safety_review_kind():
    agent = PlotterAgent()
    sub, dag = _make_subtask(
        task_id="safety",
        kind=TaskKind.SAFETY_REVIEW,
        inputs={"chapter_indices": [1]},
        expected_output_keys=("passed", "issues"),
    )
    with pytest.raises(ValueError, match="PlotterAgent cannot handle"):
        await agent.handle(sub, dag)


# ---------------------------------------------------------------------------
# CharacterAgent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_character_handle_returns_characters():
    agent = CharacterAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="character",
        kind=TaskKind.CHARACTER,
        inputs={"premise": "A mystery novel.", "count": 3},
        expected_output_keys=("characters",),
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("1. Detective Chen\n2. Sister Mai")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined characters")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.7, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["characters"] == "refined characters"


@pytest.mark.asyncio
async def test_character_handle_passes_premise_and_count():
    agent = CharacterAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="character",
        kind=TaskKind.CHARACTER,
        inputs={"premise": "Cyberpunk story.", "count": 4},
        expected_output_keys=("characters",),
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("characters")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    user_msg = m_draft.call_args.args[0][1]["content"]
    assert "Cyberpunk story." in user_msg
    assert "Number of characters: 4" in user_msg


@pytest.mark.asyncio
async def test_character_handle_includes_dep_context():
    agent = CharacterAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_dag_with_dep_results(
        target_id="character",
        target_kind=TaskKind.CHARACTER,
        target_inputs={"premise": "x", "count": 2},
        target_keys=("characters",),
        dep_results={"outline": {"chapter_outline": "Ch1: setup"}},
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("chars")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined chars")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    user_msg = m_draft.call_args.args[0][1]["content"]
    assert "Context from prior tasks:" in user_msg
    assert "Ch1: setup" in user_msg


@pytest.mark.asyncio
async def test_character_handle_defaults_missing_count():
    agent = CharacterAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="character",
        kind=TaskKind.CHARACTER,
        inputs={"premise": "x"},  # no count
        expected_output_keys=("characters",),
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("chars")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["characters"] == "refined"
    # Default count = 2.
    user_msg = m_draft.call_args.args[0][1]["content"]
    assert "Number of characters: 2" in user_msg


@pytest.mark.asyncio
async def test_character_rejects_outline_kind():
    agent = CharacterAgent()
    sub, dag = _make_subtask(
        kind=TaskKind.OUTLINE,
        inputs={"premise": "x", "chapter_count": 1},
        expected_output_keys=("chapter_outline",),
    )
    with pytest.raises(ValueError, match="CharacterAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_character_rejects_chapter_draft_kind():
    agent = CharacterAgent()
    sub, dag = _make_subtask(
        task_id="d",
        kind=TaskKind.CHAPTER_DRAFT,
        inputs={"chapter_index": 1, "target_words": 1000},
        expected_output_keys=("content_text", "summary"),
    )
    with pytest.raises(ValueError, match="CharacterAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_character_rejects_world_setting_kind():
    agent = CharacterAgent()
    sub, dag = _make_subtask(
        task_id="w",
        kind=TaskKind.WORLD_SETTING,
        inputs={"premise": "x"},
        expected_output_keys=("world_entries",),
    )
    with pytest.raises(ValueError, match="CharacterAgent cannot handle"):
        await agent.handle(sub, dag)


# ---------------------------------------------------------------------------
# EditorAgent — CHAPTER_DRAFT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editor_handle_chapter_draft_returns_content_and_summary():
    agent = EditorAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="chapter_draft_1",
        kind=TaskKind.CHAPTER_DRAFT,
        inputs={
            "chapter_index": 1,
            "target_words": 2000,
            "use_outline": True,
        },
        expected_output_keys=("content_text", "summary"),
    )
    chapter_text = "The detective arrived at the manor. Rain lashed the windows."
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response(chapter_text)
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined chapter")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.6, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["content_text"] == "refined chapter"
    assert isinstance(result["summary"], str)
    assert len(result["summary"]) > 0


@pytest.mark.asyncio
async def test_editor_handle_chapter_draft_passes_index_and_target_words():
    agent = EditorAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="chapter_draft_2",
        kind=TaskKind.CHAPTER_DRAFT,
        inputs={"chapter_index": 5, "target_words": 5000},
        expected_output_keys=("content_text", "summary"),
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("text")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    user_msg = m_draft.call_args.args[0][1]["content"]
    assert "Chapter 5" in user_msg
    assert "5000" in user_msg


@pytest.mark.asyncio
async def test_editor_handle_chapter_draft_includes_dep_context():
    """chapter_draft reads outline + world_setting + character from deps."""
    agent = EditorAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_dag_with_dep_results(
        target_id="chapter_draft_1",
        target_kind=TaskKind.CHAPTER_DRAFT,
        target_inputs={"chapter_index": 1, "target_words": 2000},
        target_keys=("content_text", "summary"),
        dep_results={
            "outline": {"chapter_outline": "Ch1: setup"},
            "world_setting": {"world_entries": "rainy city"},
            "character": {"characters": "Detective Chen"},
        },
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("text")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    user_msg = m_draft.call_args.args[0][1]["content"]
    assert "Context from prior tasks:" in user_msg
    assert "Ch1: setup" in user_msg
    assert "rainy city" in user_msg
    assert "Detective Chen" in user_msg


# ---------------------------------------------------------------------------
# EditorAgent — CHAPTER_REFINE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editor_handle_chapter_refine_uses_prior_draft():
    """chapter_refine reads the prior draft_text from dep results."""
    agent = EditorAgent(max_iters=1, score_threshold=0.99)
    prior_draft = "It was a dark and stormy night."
    sub, dag = _make_dag_with_dep_results(
        target_id="chapter_refine_1",
        target_kind=TaskKind.CHAPTER_REFINE,
        target_inputs={"chapter_index": 1},
        target_keys=("content_text",),
        dep_results={"chapter_draft_1": {"content_text": prior_draft, "summary": "s"}},
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("draft")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined chapter")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.7, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["content_text"] == "refined chapter"
    # The draft call's user message should contain the prior draft text.
    draft_user_msg = m_draft.call_args.args[0][1]["content"]
    assert prior_draft in draft_user_msg


@pytest.mark.asyncio
async def test_editor_handle_chapter_refine_no_prior_draft():
    """If no dep result has content_text, the refine handles empty draft."""
    agent = EditorAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_dag_with_dep_results(
        target_id="chapter_refine_1",
        target_kind=TaskKind.CHAPTER_REFINE,
        target_inputs={"chapter_index": 1},
        target_keys=("content_text",),
        dep_results={"chapter_draft_1": {"summary": "s"}, "outline": {"chapter_outline": "x"}},
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("refined chapter")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined chapter")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["content_text"] == "refined chapter"


@pytest.mark.asyncio
async def test_editor_handle_chapter_refine_no_deps_at_all():
    """No deps → empty draft text is used."""
    agent = EditorAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="chapter_refine_1",
        kind=TaskKind.CHAPTER_REFINE,
        inputs={"chapter_index": 1},
        expected_output_keys=("content_text",),
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["content_text"] == "refined"


# ---------------------------------------------------------------------------
# EditorAgent — FINAL_POLISH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editor_handle_final_polish_returns_content_text():
    agent = EditorAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_dag_with_dep_results(
        target_id="final_polish",
        target_kind=TaskKind.FINAL_POLISH,
        target_inputs={"chapter_indices": [1, 2]},
        target_keys=("content_text",),
        dep_results={
            "consistency_check": {"issues": "none", "score": 0.95},
        },
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("polished text")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined polished text")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.85, "good")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["content_text"] == "refined polished text"


@pytest.mark.asyncio
async def test_editor_handle_final_polish_no_deps():
    """final_polish without deps still works (empty context)."""
    agent = EditorAgent(max_iters=1, score_threshold=0.99)
    sub, dag = _make_subtask(
        task_id="final_polish",
        kind=TaskKind.FINAL_POLISH,
        inputs={"chapter_indices": [1]},
        expected_output_keys=("content_text",),
    )
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("polished")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined polished")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.7, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["content_text"] == "refined polished"


# ---------------------------------------------------------------------------
# EditorAgent — rejections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editor_rejects_outline_kind():
    agent = EditorAgent()
    sub, dag = _make_subtask(
        kind=TaskKind.OUTLINE,
        inputs={"premise": "x", "chapter_count": 1},
        expected_output_keys=("chapter_outline",),
    )
    with pytest.raises(ValueError, match="EditorAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_editor_rejects_character_kind():
    agent = EditorAgent()
    sub, dag = _make_subtask(
        task_id="c",
        kind=TaskKind.CHARACTER,
        inputs={"premise": "x", "count": 2},
        expected_output_keys=("characters",),
    )
    with pytest.raises(ValueError, match="EditorAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_editor_rejects_world_setting_kind():
    agent = EditorAgent()
    sub, dag = _make_subtask(
        task_id="w",
        kind=TaskKind.WORLD_SETTING,
        inputs={"premise": "x"},
        expected_output_keys=("world_entries",),
    )
    with pytest.raises(ValueError, match="EditorAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_editor_rejects_consistency_check_kind():
    agent = EditorAgent()
    sub, dag = _make_subtask(
        task_id="cc",
        kind=TaskKind.CONSISTENCY_CHECK,
        inputs={"chapter_indices": [1]},
        expected_output_keys=("issues", "score"),
    )
    with pytest.raises(ValueError, match="EditorAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_editor_rejects_safety_review_kind():
    agent = EditorAgent()
    sub, dag = _make_subtask(
        task_id="s",
        kind=TaskKind.SAFETY_REVIEW,
        inputs={"chapter_indices": [1]},
        expected_output_keys=("passed", "issues"),
    )
    with pytest.raises(ValueError, match="EditorAgent cannot handle"):
        await agent.handle(sub, dag)


# ---------------------------------------------------------------------------
# EditorAgent._auto_summary
# ---------------------------------------------------------------------------


def test_auto_summary_empty_text():
    assert EditorAgent._auto_summary("") == ""


def test_auto_summary_short_first_sentence():
    text = "The detective arrived. Then left."
    summary = EditorAgent._auto_summary(text)
    assert summary == "The detective arrived."


def test_auto_summary_long_first_sentence_truncates():
    long_first = "x" * 600 + ". rest of story."
    summary = EditorAgent._auto_summary(long_first)
    # First sentence is > 200 chars → fall back to 200-char prefix.
    assert len(summary) <= 205  # 200 chars + "..."
    assert summary.endswith("...")


def test_auto_summary_no_sentence_ending():
    """Text without . / ! / ? → returns truncated first 200 chars."""
    text = "no punctuation just continuous text " * 20
    summary = EditorAgent._auto_summary(text)
    # The split returns the whole text (no split), so we fall back to truncation.
    assert summary.endswith("...")
    assert len(summary) <= 205


def test_auto_summary_chinese_sentence_ending():
    """Chinese punctuation 。 followed by whitespace splits the sentence."""
    # The regex requires whitespace after the sentence-ending punctuation,
    # so we test with a space after the first 。.
    text = "侦探到了庄园。 然后离开了。"
    summary = EditorAgent._auto_summary(text)
    assert summary == "侦探到了庄园."


def test_auto_summary_chinese_no_whitespace_returns_truncated():
    """Chinese 。 without trailing whitespace → no split → truncated text."""
    text = "侦探到了庄园。然后离开了。"
    summary = EditorAgent._auto_summary(text)
    # No split happens (regex requires \s after 。), so the whole text
    # becomes the "first sentence". Since it's < max_chars, we get
    # text + "." suffix.
    assert summary == text + "."


# ---------------------------------------------------------------------------
# make_novel_orchestrator
# ---------------------------------------------------------------------------


def test_make_novel_orchestrator_registers_all_eight_handlers():
    """All 9 TaskKinds should have handlers (including SAFETY_REVIEW and REFLECTION)."""
    orch = make_novel_orchestrator(max_iters=1, score_threshold=0.99)
    registered_kinds = set(orch._handlers.keys())
    expected = {
        TaskKind.OUTLINE,
        TaskKind.WORLD_SETTING,
        TaskKind.CONSISTENCY_CHECK,
        TaskKind.CHARACTER,
        TaskKind.CHAPTER_DRAFT,
        TaskKind.CHAPTER_REFINE,
        TaskKind.FINAL_POLISH,
        TaskKind.SAFETY_REVIEW,
        TaskKind.REFLECTION,
    }
    assert registered_kinds == expected


def test_make_novel_orchestrator_does_register_safety_review():
    """SAFETY_REVIEW is now registered by ContentSafetyAgent (P2-safe-1)."""
    from app.safety import ContentSafetyAgent

    orch = make_novel_orchestrator()
    assert TaskKind.SAFETY_REVIEW in orch._handlers
    safety_handler = orch._handlers[TaskKind.SAFETY_REVIEW]
    assert isinstance(safety_handler.__self__, ContentSafetyAgent)


def test_make_novel_orchestrator_handlers_are_agent_methods():
    """Each registered handler is a bound method of an agent instance."""
    orch = make_novel_orchestrator()
    # PlotterAgent handles 3 kinds.
    plotter_handler = orch._handlers[TaskKind.OUTLINE]
    assert hasattr(plotter_handler, "__self__")
    assert isinstance(plotter_handler.__self__, PlotterAgent)
    # CharacterAgent handles 1.
    character_handler = orch._handlers[TaskKind.CHARACTER]
    assert isinstance(character_handler.__self__, CharacterAgent)
    # EditorAgent handles 3.
    editor_handler = orch._handlers[TaskKind.CHAPTER_DRAFT]
    assert isinstance(editor_handler.__self__, EditorAgent)


def test_make_novel_orchestrator_returns_orchestrator_instance():
    orch = make_novel_orchestrator()
    assert isinstance(orch, Orchestrator)


def test_make_novel_orchestrator_passes_kwargs_to_agents():
    """max_iters and score_threshold reach the agent instances."""
    cfg = _byok_provider()
    orch = make_novel_orchestrator(
        provider_config=cfg, max_iters=5, score_threshold=0.92
    )
    plotter = orch._handlers[TaskKind.OUTLINE].__self__
    character = orch._handlers[TaskKind.CHARACTER].__self__
    editor = orch._handlers[TaskKind.CHAPTER_DRAFT].__self__
    for agent in (plotter, character, editor):
        assert agent.provider_config is cfg
        assert agent.max_iters == 5
        assert agent.score_threshold == 0.92


# ---------------------------------------------------------------------------
# E2E: orchestrator drives a single-chapter DAG with mocked LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_runs_single_chapter_template_with_mocked_llm():
    """Full DAG: outline → world_setting → character → chapter_draft_1 →
    chapter_refine_1 → consistency_check → final_polish → safety_review.

    All LLM calls are mocked. The ContentSafetyAgent uses the rule engine
    (deterministic) for the first phase, then the mocked LLM for the
    second phase. No BLOCK rules match the test text → safety task
    proceeds to LLM evaluation.
    """
    dag = single_chapter_template(premise="A locked-room mystery.", target_words=500)
    orch = make_novel_orchestrator(max_iters=1, score_threshold=0.99)

    # Mock all three LLM wrappers — return increasing-quality content so
    # the loop produces distinguishable outputs per stage.
    call_count = {"n": 0}

    async def _fake_draft(messages, *, stage_config=None):
        call_count["n"] += 1
        sys_prompt = messages[0]["content"]
        # Produce stage-specific text so we can verify it propagated.
        if "plotter" in sys_prompt.lower():
            return _fake_llm_response("1. Ch1: Setup\n2. Ch1: Resolution")
        if "worldbuilder" in sys_prompt.lower():
            return _fake_llm_response("City of Shadows, 1920s, noir aesthetic")
        if "character designer" in sys_prompt.lower():
            return _fake_llm_response("1. Detective Chen — protagonist")
        if "chapter writer" in sys_prompt.lower():
            return _fake_llm_response("The detective walked into the manor.")
        if "chapter editor" in sys_prompt.lower():
            return _fake_llm_response("The detective strode into the manor, refined.")
        if "consistency checker" in sys_prompt.lower():
            return _fake_llm_response("No inconsistencies found.")
        if "final polisher" in sys_prompt.lower():
            return _fake_llm_response("The detective strode into the manor — polished.")
        return _fake_llm_response("generic draft")

    async def _fake_refine(messages, *, stage_config=None):
        return _fake_llm_response("refined content")

    async def _fake_eval(messages, *, stage_config=None):
        return _eval_response(0.5, "needs work")

    with (
        patch("app.agents.base.llm_draft", AsyncMock(side_effect=_fake_draft)),
        patch("app.agents.base.llm_refine", AsyncMock(side_effect=_fake_refine)),
        patch("app.agents.base.llm_evaluate", AsyncMock(side_effect=_fake_eval)),
    ):
        result_dag = await orch.run(dag)

    # All tasks should reach terminal status.
    assert result_dag.is_complete()
    summary = result_dag.summary()
    assert summary["complete"] is True
    # No failures expected (handler outputs satisfy expected_output_keys).
    assert summary["status_counts"].get("failed", 0) == 0
    # All 8 tasks DONE including the safety review (real ContentSafetyAgent).
    assert summary["status_counts"].get("done", 0) == 8


@pytest.mark.asyncio
async def test_orchestrator_propagates_dep_results_to_chapter_refine():
    """Verify chapter_refine reads chapter_draft's content_text from the DAG.

    Uses a minimal 2-task DAG: chapter_draft_1 → chapter_refine_1.

    Strategy: make chapter_draft_1's refine pass return a unique marker.
    That marker becomes chapter_draft_1.result["content_text"]. Then
    chapter_refine_1's draft pass should have that marker in its user
    prompt (proving dep propagation through the DAG).
    """
    specs = [
        TaskSpec(
            task_id="chapter_draft_1",
            kind=TaskKind.CHAPTER_DRAFT,
            inputs={"chapter_index": 1, "target_words": 1000},
            expected_output_keys=("content_text", "summary"),
        ),
        TaskSpec(
            task_id="chapter_refine_1",
            kind=TaskKind.CHAPTER_REFINE,
            inputs={"chapter_index": 1},
            depends_on=("chapter_draft_1",),
            expected_output_keys=("content_text",),
        ),
    ]
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})

    orch = make_novel_orchestrator(max_iters=1, score_threshold=0.99)

    # chapter_draft_1's refine pass returns this marker — it becomes
    # chapter_draft_1's content_text after the three-stage run completes.
    draft_marker = "CHAPTER_DRAFT_OUTPUT_MARKER_42"

    # Capture every draft-phase user prompt so we can verify the marker
    # appears in chapter_refine_1's draft call.
    captured_draft_user_msgs: list[str] = []

    async def _draft(messages, *, stage_config=None):
        captured_draft_user_msgs.append(messages[1]["content"])
        return _fake_llm_response("draft placeholder")

    async def _refine(messages, *, stage_config=None):
        # All refine passes return the marker so it propagates through.
        return _fake_llm_response(draft_marker)

    async def _eval(messages, *, stage_config=None):
        return _eval_response(0.6, "ok")

    with (
        patch("app.agents.base.llm_draft", AsyncMock(side_effect=_draft)),
        patch("app.agents.base.llm_refine", AsyncMock(side_effect=_refine)),
        patch("app.agents.base.llm_evaluate", AsyncMock(side_effect=_eval)),
    ):
        await orch.run(dag)

    # chapter_draft_1 should be DONE with content_text = marker (from refine pass).
    draft_sub = dag.get("chapter_draft_1")
    assert draft_sub.status == SubTaskStatus.DONE
    assert draft_sub.result["content_text"] == draft_marker

    # chapter_refine_1 should be DONE too.
    refine_sub = dag.get("chapter_refine_1")
    assert refine_sub.status == SubTaskStatus.DONE

    # Two agents ran their three-stage → at least 2 draft calls.
    # The 2nd draft call is chapter_refine_1's draft phase — its user
    # prompt should contain the marker text from chapter_draft_1.
    assert len(captured_draft_user_msgs) >= 2
    chapter_refine_draft_user_msg = captured_draft_user_msgs[1]
    assert draft_marker in chapter_refine_draft_user_msg


@pytest.mark.asyncio
async def test_orchestrator_handles_agent_failure_gracefully():
    """If an agent raises, the task is FAILED and downstream tasks are stuck PENDING."""
    dag = single_chapter_template(premise="x", target_words=100)
    orch = make_novel_orchestrator(max_iters=1, score_threshold=0.99)

    # Make draft raise for ALL calls — every agent will fail.
    async def _boom(messages, *, stage_config=None):
        raise RuntimeError("LLM is down")

    with (
        patch("app.agents.base.llm_draft", AsyncMock(side_effect=_boom)),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("refined")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        await orch.run(dag)

    # The root task (outline) should be FAILED since draft raised.
    outline_sub = dag.get("outline")
    assert outline_sub.status == SubTaskStatus.FAILED
    assert outline_sub.error is not None
    assert "RuntimeError" in outline_sub.error
    # Downstream tasks depending on outline should remain PENDING
    # (their dep never reached DONE → deadlock → orchestrator exits loop).
    world_sub = dag.get("world_setting")
    assert world_sub.status == SubTaskStatus.PENDING
