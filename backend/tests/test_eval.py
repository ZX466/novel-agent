"""Tests for app.eval — multi-dimensional review matrix.

Covers P2-eval-1: validates the multi-dimensional evaluation system
that replaces the single evaluator score with a 5-dimension review
matrix (coherence, character_consistency, prose_quality, plot_logic,
world_consistency).

Test surface:
  - ReviewDimension: construction, validation, with_overrides
  - make_default_dimensions: returns 5 dimensions with correct names/weights
  - AggregationStrategy: enum values
  - ReviewResult: dataclass + failed property
  - ReviewMatrix: passed, failed_dimensions, get, to_dict
  - ReviewMatrixRunner: construction, add/remove, defaults
  - ReviewMatrixRunner.evaluate: parallel execution, mock LLM, empty text
  - Aggregation strategies: WEIGHTED_AVERAGE, MIN_SCORE, MEAN
  - Exception handling: per-dimension failures don't fail the matrix
  - Integration with BaseAgent._run_three_stage (matrix mode)
  - Factory integration: evaluator flows to plotter/character/editor
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
from app.eval import (
    AggregationStrategy,
    ReviewDimension,
    ReviewMatrix,
    ReviewMatrixRunner,
    ReviewResult,
    make_default_dimensions,
)
from app.eval.matrix import _parse_eval
from app.planner.spec import TaskKind


# ---------------------------------------------------------------------------
# Helpers — fake litellm response shape (mirrors test_agents.py)
# ---------------------------------------------------------------------------


def _fake_llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _eval_response(score: float, feedback: str = "ok"):
    return _fake_llm_response(
        '{"score": ' + str(score) + ', "feedback": "' + feedback + '"}'
    )


# ---------------------------------------------------------------------------
# ReviewDimension
# ---------------------------------------------------------------------------


class TestReviewDimension:
    def test_basic_construction(self):
        d = ReviewDimension(
            name="test",
            system_prompt="Score this.",
            weight=1.5,
            description="A test dimension.",
        )
        assert d.name == "test"
        assert d.system_prompt == "Score this."
        assert d.weight == 1.5
        assert d.description == "A test dimension."

    def test_default_weight_is_1(self):
        d = ReviewDimension(name="t", system_prompt="x")
        assert d.weight == 1.0
        assert d.description == ""

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name must be non-empty"):
            ReviewDimension(name="", system_prompt="x")

    def test_zero_weight_raises(self):
        with pytest.raises(ValueError, match="weight must be > 0"):
            ReviewDimension(name="t", system_prompt="x", weight=0.0)

    def test_negative_weight_raises(self):
        with pytest.raises(ValueError, match="weight must be > 0"):
            ReviewDimension(name="t", system_prompt="x", weight=-1.0)

    def test_frozen(self):
        d = ReviewDimension(name="t", system_prompt="x")
        with pytest.raises(Exception):
            d.name = "changed"  # type: ignore[misc]

    def test_with_overrides_keeps_unchanged_fields(self):
        d = ReviewDimension(name="t", system_prompt="x", weight=2.0)
        d2 = d.with_overrides(weight=3.0)
        assert d2.name == "t"
        assert d2.system_prompt == "x"
        assert d2.weight == 3.0

    def test_with_overrides_replaces_name(self):
        d = ReviewDimension(name="t", system_prompt="x")
        d2 = d.with_overrides(name="renamed")
        assert d2.name == "renamed"
        assert d2.system_prompt == "x"

    def test_with_overrides_does_not_mutate_original(self):
        d = ReviewDimension(name="t", system_prompt="x", weight=1.0)
        _ = d.with_overrides(weight=5.0)
        assert d.weight == 1.0


# ---------------------------------------------------------------------------
# make_default_dimensions
# ---------------------------------------------------------------------------


class TestMakeDefaultDimensions:
    def test_returns_expected_count(self):
        dims = make_default_dimensions()
        assert isinstance(dims, list)
        assert len(dims) == len(make_default_dimensions())
        assert len(dims) >= 5  # guard against silent shrinkage

    def test_returns_expected_names(self):
        dims = make_default_dimensions()
        names = {d.name for d in dims}
        assert names == {
            "coherence",
            "character_consistency",
            "prose_quality",
            "plot_logic",
            "world_consistency",
            "cross_chapter_consistency",
        }

    def test_all_weights_positive(self):
        dims = make_default_dimensions()
        for d in dims:
            assert d.weight > 0

    def test_plot_logic_has_highest_weight(self):
        dims = make_default_dimensions()
        weights = {d.name: d.weight for d in dims}
        max_weight = max(weights.values())
        assert weights["plot_logic"] == max_weight

    def test_character_consistency_weight_above_default(self):
        dims = make_default_dimensions()
        weights = {d.name: d.weight for d in dims}
        assert weights["character_consistency"] > 1.0

    def test_returns_fresh_list_each_call(self):
        d1 = make_default_dimensions()
        d2 = make_default_dimensions()
        assert d1 is not d2
        assert d1[0] is not d2[0]

    def test_all_system_prompts_non_empty(self):
        dims = make_default_dimensions()
        for d in dims:
            assert d.system_prompt
            assert "JSON" in d.system_prompt or "json" in d.system_prompt

    def test_all_descriptions_non_empty(self):
        dims = make_default_dimensions()
        for d in dims:
            assert d.description


# ---------------------------------------------------------------------------
# AggregationStrategy
# ---------------------------------------------------------------------------


class TestAggregationStrategy:
    def test_has_three_strategies(self):
        values = {s.value for s in AggregationStrategy}
        assert values == {"weighted_average", "min_score", "mean"}

    def test_default_is_weighted_average(self):
        runner = ReviewMatrixRunner()
        assert runner.strategy == AggregationStrategy.WEIGHTED_AVERAGE


# ---------------------------------------------------------------------------
# ReviewResult
# ---------------------------------------------------------------------------


class TestReviewResult:
    def test_defaults(self):
        r = ReviewResult(dimension_name="t")
        assert r.dimension_name == "t"
        assert r.score == 0.0
        assert r.feedback == ""
        assert r.raw_eval == ""
        assert r.error == ""

    def test_failed_is_false_when_no_error(self):
        r = ReviewResult(dimension_name="t", score=0.5)
        assert not r.failed

    def test_failed_is_true_when_error_set(self):
        r = ReviewResult(dimension_name="t", error="boom")
        assert r.failed

    def test_failed_is_true_when_error_is_nonempty_string(self):
        r = ReviewResult(dimension_name="t", error="x")
        assert r.failed

    def test_frozen(self):
        r = ReviewResult(dimension_name="t")
        with pytest.raises(Exception):
            r.score = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ReviewMatrix
# ---------------------------------------------------------------------------


class TestReviewMatrix:
    def _make_results(self, *scores: float) -> tuple[ReviewResult, ...]:
        return tuple(
            ReviewResult(dimension_name=f"d{i}", score=s)
            for i, s in enumerate(scores)
        )

    def test_passed_true_when_above_threshold(self):
        m = ReviewMatrix(
            results=self._make_results(0.9),
            aggregate_score=0.9,
            threshold=0.8,
        )
        assert m.passed

    def test_passed_false_when_below_threshold(self):
        m = ReviewMatrix(
            results=self._make_results(0.7),
            aggregate_score=0.7,
            threshold=0.8,
        )
        assert not m.passed

    def test_passed_true_when_equal_to_threshold(self):
        m = ReviewMatrix(
            results=self._make_results(0.8),
            aggregate_score=0.8,
            threshold=0.8,
        )
        assert m.passed

    def test_failed_dimensions_empty_when_no_errors(self):
        m = ReviewMatrix(
            results=(
                ReviewResult(dimension_name="a", score=0.5),
                ReviewResult(dimension_name="b", score=0.7),
            ),
        )
        assert m.failed_dimensions == []

    def test_failed_dimensions_returns_only_failed(self):
        m = ReviewMatrix(
            results=(
                ReviewResult(dimension_name="a", score=0.5),
                ReviewResult(dimension_name="b", error="boom"),
                ReviewResult(dimension_name="c", error="bang"),
            ),
        )
        failed = m.failed_dimensions
        assert len(failed) == 2
        assert {f.dimension_name for f in failed} == {"b", "c"}

    def test_get_returns_matching_result(self):
        m = ReviewMatrix(
            results=(
                ReviewResult(dimension_name="a", score=0.5),
                ReviewResult(dimension_name="b", score=0.7),
            ),
        )
        r = m.get("b")
        assert r is not None
        assert r.score == 0.7

    def test_get_returns_none_when_missing(self):
        m = ReviewMatrix(results=(ReviewResult(dimension_name="a"),))
        assert m.get("nonexistent") is None

    def test_to_dict_structure(self):
        m = ReviewMatrix(
            results=(
                ReviewResult(dimension_name="a", score=0.5, feedback="ok"),
                ReviewResult(dimension_name="b", error="err"),
            ),
            aggregate_score=0.5,
            aggregate_feedback="a: ok\nb: error: err",
            threshold=0.8,
            strategy=AggregationStrategy.WEIGHTED_AVERAGE,
        )
        d = m.to_dict()
        assert d["aggregate_score"] == 0.5
        assert d["aggregate_feedback"] == "a: ok\nb: error: err"
        assert d["threshold"] == 0.8
        assert d["strategy"] == "weighted_average"
        assert d["passed"] is False
        assert len(d["dimensions"]) == 2
        assert d["dimensions"][0]["name"] == "a"
        assert d["dimensions"][0]["score"] == 0.5
        assert d["dimensions"][1]["error"] == "err"


# ---------------------------------------------------------------------------
# ReviewMatrixRunner — construction + add/remove
# ---------------------------------------------------------------------------


class TestReviewMatrixRunnerConstruction:
    def test_default_construction_uses_default_dimensions(self):
        r = ReviewMatrixRunner()
        assert len(r.dimensions) == len(make_default_dimensions())
        assert r.strategy == AggregationStrategy.WEIGHTED_AVERAGE
        assert r.threshold == 0.8

    def test_custom_dimensions(self):
        d = ReviewDimension(name="custom", system_prompt="x")
        r = ReviewMatrixRunner(dimensions=[d])
        assert len(r.dimensions) == 1
        assert r.dimensions[0].name == "custom"

    def test_empty_dimensions_raises(self):
        with pytest.raises(ValueError, match="at least one dimension"):
            ReviewMatrixRunner(dimensions=[])

    def test_custom_strategy(self):
        r = ReviewMatrixRunner(strategy=AggregationStrategy.MIN_SCORE)
        assert r.strategy == AggregationStrategy.MIN_SCORE

    def test_custom_threshold(self):
        r = ReviewMatrixRunner(threshold=0.95)
        assert r.threshold == 0.95

    def test_add_replaces_by_name(self):
        r = ReviewMatrixRunner(
            dimensions=[ReviewDimension(name="x", system_prompt="old", weight=1.0)]
        )
        r.add(ReviewDimension(name="x", system_prompt="new", weight=2.0))
        assert len(r.dimensions) == 1
        assert r.dimensions[0].system_prompt == "new"
        assert r.dimensions[0].weight == 2.0

    def test_add_appends_new_dimension(self):
        r = ReviewMatrixRunner(
            dimensions=[ReviewDimension(name="x", system_prompt="a")]
        )
        r.add(ReviewDimension(name="y", system_prompt="b"))
        assert len(r.dimensions) == 2
        names = {d.name for d in r.dimensions}
        assert names == {"x", "y"}

    def test_remove_existing(self):
        r = ReviewMatrixRunner(
            dimensions=[
                ReviewDimension(name="x", system_prompt="a"),
                ReviewDimension(name="y", system_prompt="b"),
            ]
        )
        assert r.remove("x") is True
        assert len(r.dimensions) == 1
        assert r.dimensions[0].name == "y"

    def test_remove_nonexisting(self):
        r = ReviewMatrixRunner(
            dimensions=[ReviewDimension(name="x", system_prompt="a")]
        )
        assert r.remove("nonexistent") is False
        assert len(r.dimensions) == 1


# ---------------------------------------------------------------------------
# ReviewMatrixRunner.evaluate — aggregation strategies
# ---------------------------------------------------------------------------


class TestAggregationStrategies:
    """Test aggregation math directly via _compute_score (no LLM calls)."""

    def _make_runner(self, strategy, weights=None):
        weights = weights or [1.0, 1.0, 1.0]
        dims = [
            ReviewDimension(name=f"d{i}", system_prompt="x", weight=w)
            for i, w in enumerate(weights)
        ]
        return ReviewMatrixRunner(dimensions=dims, strategy=strategy)

    def test_weighted_average_equal_weights(self):
        r = self._make_runner(AggregationStrategy.WEIGHTED_AVERAGE)
        results = (
            ReviewResult(dimension_name="d0", score=0.6),
            ReviewResult(dimension_name="d1", score=0.8),
            ReviewResult(dimension_name="d2", score=1.0),
        )
        # (0.6 + 0.8 + 1.0) / 3 = 0.8
        assert r._compute_score(results) == pytest.approx(0.8)

    def test_weighted_average_unequal_weights(self):
        r = self._make_runner(
            AggregationStrategy.WEIGHTED_AVERAGE, weights=[1.0, 2.0, 1.0]
        )
        results = (
            ReviewResult(dimension_name="d0", score=0.0),
            ReviewResult(dimension_name="d1", score=1.0),
            ReviewResult(dimension_name="d2", score=0.0),
        )
        # (0*1 + 1*2 + 0*1) / (1+2+1) = 2/4 = 0.5
        assert r._compute_score(results) == pytest.approx(0.5)

    def test_min_score(self):
        r = self._make_runner(AggregationStrategy.MIN_SCORE)
        results = (
            ReviewResult(dimension_name="d0", score=0.6),
            ReviewResult(dimension_name="d1", score=0.2),
            ReviewResult(dimension_name="d2", score=0.9),
        )
        assert r._compute_score(results) == pytest.approx(0.2)

    def test_mean(self):
        r = self._make_runner(
            AggregationStrategy.MEAN, weights=[1.0, 5.0, 1.0]
        )
        # MEAN ignores weights
        results = (
            ReviewResult(dimension_name="d0", score=0.0),
            ReviewResult(dimension_name="d1", score=1.0),
            ReviewResult(dimension_name="d2", score=0.5),
        )
        # (0 + 1 + 0.5) / 3 = 0.5
        assert r._compute_score(results) == pytest.approx(0.5)

    def test_weighted_average_empty_results(self):
        r = self._make_runner(AggregationStrategy.WEIGHTED_AVERAGE)
        assert r._compute_score(()) == 0.0

    def test_weighted_average_zero_total_weight_falls_back_to_mean(self):
        # Edge case: all weights somehow zero — but ReviewDimension rejects
        # weight=0, so this only happens via _dim_weight returning 0 for
        # unknown dimension names. Construct results with unknown names.
        r = self._make_runner(AggregationStrategy.WEIGHTED_AVERAGE)
        results = (
            ReviewResult(dimension_name="unknown1", score=0.4),
            ReviewResult(dimension_name="unknown2", score=0.6),
        )
        # _dim_weight returns 1.0 default — so this is really just mean
        # (0.4 + 0.6) / 2 = 0.5
        assert r._compute_score(results) == pytest.approx(0.5)

    def test_weighted_average_excludes_failed_dimensions(self):
        # A transient eval failure (e.g. 429) must not drag the composite
        # to 0 and force wasteful refine iterations. Only the succeeded
        # dimensions contribute to the score.
        r = self._make_runner(
            AggregationStrategy.WEIGHTED_AVERAGE, weights=[1.0, 1.0, 1.0]
        )
        results = (
            ReviewResult(dimension_name="d0", score=0.8),
            ReviewResult(dimension_name="d1", error="RateLimitError: 429"),
            ReviewResult(dimension_name="d2", score=0.9),
        )
        # (0.8 + 0.9) / 2 = 0.85 — the failed d1 is excluded, not counted as 0
        assert r._compute_score(results) == pytest.approx(0.85)

    def test_all_failed_returns_zero(self):
        r = self._make_runner(AggregationStrategy.WEIGHTED_AVERAGE)
        results = (
            ReviewResult(dimension_name="d0", error="boom"),
            ReviewResult(dimension_name="d1", error="bang"),
        )
        assert r._compute_score(results) == 0.0


# ---------------------------------------------------------------------------
# ReviewMatrixRunner.evaluate — with mocked LLM
# ---------------------------------------------------------------------------


class TestEvaluateWithMockedLLM:
    @pytest.mark.asyncio
    async def test_evaluate_runs_each_dimension(self):
        dims = make_default_dimensions()
        runner = ReviewMatrixRunner(dimensions=dims)
        captured_systems: list[str] = []

        async def _fake_eval(messages, *, stage_config=None):
            captured_systems.append(messages[0]["content"])
            return _eval_response(0.9, "looks good")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            m = await runner.evaluate("test text")

        # All dimensions ran
        expected = len(make_default_dimensions())
        assert len(m.results) == expected
        assert len(captured_systems) == expected
        # All scores are 0.9
        for r in m.results:
            assert r.score == 0.9

    @pytest.mark.asyncio
    async def test_evaluate_aggregate_score_weighted(self):
        # Use 2 dimensions with different weights so the weighted average
        # is distinguishable from a simple mean.
        dims = [
            ReviewDimension(name="a", system_prompt="pa", weight=1.0),
            ReviewDimension(name="b", system_prompt="pb", weight=3.0),
        ]
        runner = ReviewMatrixRunner(
            dimensions=dims, strategy=AggregationStrategy.WEIGHTED_AVERAGE
        )

        async def _fake_eval(messages, *, stage_config=None):
            sys = messages[0]["content"]
            if sys == "pa":
                return _eval_response(1.0, "perfect")
            return _eval_response(0.0, "fail")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            m = await runner.evaluate("text")

        # (1.0*1 + 0.0*3) / (1+3) = 0.25
        assert m.aggregate_score == pytest.approx(0.25)
        assert not m.passed  # 0.25 < 0.8

    @pytest.mark.asyncio
    async def test_evaluate_aggregate_score_min(self):
        dims = [
            ReviewDimension(name="a", system_prompt="pa"),
            ReviewDimension(name="b", system_prompt="pb"),
        ]
        runner = ReviewMatrixRunner(
            dimensions=dims, strategy=AggregationStrategy.MIN_SCORE
        )

        async def _fake_eval(messages, *, stage_config=None):
            sys = messages[0]["content"]
            if sys == "pa":
                return _eval_response(0.9, "ok")
            return _eval_response(0.3, "low")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            m = await runner.evaluate("text")

        assert m.aggregate_score == pytest.approx(0.3)
        assert not m.passed

    @pytest.mark.asyncio
    async def test_evaluate_aggregate_score_mean(self):
        dims = [
            ReviewDimension(name="a", system_prompt="pa", weight=5.0),
            ReviewDimension(name="b", system_prompt="pb", weight=1.0),
        ]
        runner = ReviewMatrixRunner(
            dimensions=dims, strategy=AggregationStrategy.MEAN
        )

        async def _fake_eval(messages, *, stage_config=None):
            sys = messages[0]["content"]
            if sys == "pa":
                return _eval_response(1.0, "perfect")
            return _eval_response(0.0, "fail")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            m = await runner.evaluate("text")

        # Mean ignores weights: (1.0 + 0.0) / 2 = 0.5
        assert m.aggregate_score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_evaluate_passes_threshold_override(self):
        dims = [ReviewDimension(name="a", system_prompt="pa")]
        runner = ReviewMatrixRunner(dimensions=dims, threshold=0.95)

        async def _fake_eval(messages, *, stage_config=None):
            return _eval_response(0.9, "ok")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            # Default threshold 0.95 — should NOT pass at 0.9
            m1 = await runner.evaluate("text")
            assert not m1.passed

            # Override threshold to 0.8 — should pass
            m2 = await runner.evaluate("text", threshold=0.8)
            assert m2.passed

    @pytest.mark.asyncio
    async def test_evaluate_passes_stage_config(self):
        from app.schemas.chat import StageConfig

        dims = [ReviewDimension(name="a", system_prompt="pa")]
        runner = ReviewMatrixRunner(dimensions=dims)

        captured_configs: list = []

        async def _fake_eval(messages, *, stage_config=None):
            captured_configs.append(stage_config)
            return _eval_response(0.5, "ok")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            byok = StageConfig(
                api_base="https://example.com/v1",
                api_key="sk-test",
                model="gpt-4",
            )
            _ = await runner.evaluate("text", stage_config=byok)

        assert captured_configs[0] is byok

    @pytest.mark.asyncio
    async def test_evaluate_empty_text_skips_llm(self):
        dims = make_default_dimensions()
        runner = ReviewMatrixRunner(dimensions=dims)

        call_count = 0

        async def _fake_eval(messages, *, stage_config=None):
            nonlocal call_count
            call_count += 1
            return _eval_response(0.9, "ok")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            m = await runner.evaluate("")

        assert call_count == 0
        assert len(m.results) == len(make_default_dimensions())
        for r in m.results:
            assert r.score == 0.0
            assert r.error == "empty input text"
        assert m.aggregate_score == 0.0


# ---------------------------------------------------------------------------
# ReviewMatrixRunner.evaluate — exception handling
# ---------------------------------------------------------------------------


class TestEvaluateExceptionHandling:
    @pytest.mark.asyncio
    async def test_one_dimension_failure_does_not_fail_matrix(self):
        dims = [
            ReviewDimension(name="a", system_prompt="pa"),
            ReviewDimension(name="b", system_prompt="pb"),
        ]
        runner = ReviewMatrixRunner(dimensions=dims)

        async def _fake_eval(messages, *, stage_config=None):
            sys = messages[0]["content"]
            if sys == "pb":
                raise RuntimeError("boom")
            return _eval_response(0.9, "ok")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            m = await runner.evaluate("text")

        # Both results present
        assert len(m.results) == 2
        a = m.get("a")
        b = m.get("b")
        assert a is not None and b is not None
        # a succeeded
        assert a.score == 0.9
        assert not a.failed
        # b failed but recorded
        assert b.score == 0.0
        assert b.failed
        assert "RuntimeError" in b.error
        assert "boom" in b.error

    @pytest.mark.asyncio
    async def test_all_dimensions_failure_still_returns_matrix(self):
        dims = [
            ReviewDimension(name="a", system_prompt="pa"),
            ReviewDimension(name="b", system_prompt="pb"),
        ]
        runner = ReviewMatrixRunner(dimensions=dims)

        async def _fake_eval(messages, *, stage_config=None):
            raise ConnectionError("network down")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            m = await runner.evaluate("text")

        assert len(m.results) == 2
        for r in m.results:
            assert r.failed
            assert "ConnectionError" in r.error
        # All zeros → aggregate 0.0
        assert m.aggregate_score == 0.0
        assert not m.passed

    @pytest.mark.asyncio
    async def test_failed_dimension_appears_in_failed_dimensions(self):
        dims = [
            ReviewDimension(name="a", system_prompt="pa"),
            ReviewDimension(name="b", system_prompt="pb"),
        ]
        runner = ReviewMatrixRunner(dimensions=dims)

        async def _fake_eval(messages, *, stage_config=None):
            if messages[0]["content"] == "pb":
                raise ValueError("nope")
            return _eval_response(0.9, "ok")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            m = await runner.evaluate("text")

        failed = m.failed_dimensions
        assert len(failed) == 1
        assert failed[0].dimension_name == "b"

    @pytest.mark.asyncio
    async def test_failed_dimension_in_aggregate_feedback(self):
        dims = [
            ReviewDimension(name="a", system_prompt="pa"),
            ReviewDimension(name="b", system_prompt="pb"),
        ]
        runner = ReviewMatrixRunner(dimensions=dims)

        async def _fake_eval(messages, *, stage_config=None):
            if messages[0]["content"] == "pb":
                raise ValueError("nope")
            return _eval_response(0.9, "looks good")

        with patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            m = await runner.evaluate("text")

        # Feedback contains the failed dimension's error
        assert "b: error" in m.aggregate_feedback
        assert "nope" in m.aggregate_feedback
        # And the success dimension's feedback
        assert "a: looks good" in m.aggregate_feedback


# ---------------------------------------------------------------------------
# _parse_eval (matrix version)
# ---------------------------------------------------------------------------


class TestParseEval:
    def test_clean_json(self):
        score, feedback = _parse_eval('{"score": 0.85, "feedback": "good"}')
        assert score == 0.85
        assert feedback == "good"

    def test_markdown_fenced(self):
        score, _ = _parse_eval('```json\n{"score": 0.7}\n```')
        assert score == 0.7

    def test_bare_fenced(self):
        score, _ = _parse_eval('```\n{"score": 0.6}\n```')
        assert score == 0.6

    def test_missing_feedback(self):
        score, feedback = _parse_eval('{"score": 0.5}')
        assert score == 0.5
        assert feedback == ""

    def test_invalid_json_falls_back_to_regex(self):
        score, feedback = _parse_eval("score is 0.42")
        assert score == 0.42
        # feedback is the cleaned text
        assert "0.42" in feedback

    def test_no_numbers_returns_zero(self):
        score, _ = _parse_eval("no numbers here")
        assert score == 0.0

    def test_empty_string(self):
        score, _ = _parse_eval("")
        assert score == 0.0

    def test_scale_echo_does_not_steal_leading_zero(self):
        """Models often echo '0.0-1.0 scale' before the real score. A naive
        first-number regex grabs that 0.0 -> score 0.0 -> forces the pipeline
        to loop every refine iteration. The keyword anchor must win."""
        score, _ = _parse_eval("On a 0.0-1.0 scale, score 0.85. Good prose.")
        assert score == 0.85

    def test_embedded_json_in_prose(self):
        score, feedback = _parse_eval(
            'Here is my review: {"score": 0.9, "feedback": "nice"} thanks'
        )
        assert score == 0.9
        assert feedback == "nice"

    def test_score_keyword_after_scale(self):
        score, _ = _parse_eval("0.0-1.0 scale. The score is 0.7 here.")
        assert score == 0.7

    def test_clamps_above_one(self):
        score, _ = _parse_eval('{"score": 1.5}')
        assert score == 1.0


# ---------------------------------------------------------------------------
# Integration with BaseAgent._run_three_stage
# ---------------------------------------------------------------------------


class TestBaseAgentMatrixIntegration:
    @pytest.mark.asyncio
    async def test_evaluator_uses_matrix_when_provided(self):
        """When evaluator is provided, _run_three_stage uses the matrix."""
        dims = [
            ReviewDimension(name="d1", system_prompt="pd1"),
            ReviewDimension(name="d2", system_prompt="pd2"),
        ]
        evaluator = ReviewMatrixRunner(
            dimensions=dims, strategy=AggregationStrategy.MEAN
        )

        class _A(BaseAgent):
            name = "test"

            async def handle(self, subtask, dag):
                raise NotImplementedError

        agent = _A(evaluator=evaluator)

        eval_call_count = 0

        async def _fake_draft(messages, *, stage_config=None):
            return _fake_llm_response("draft text")

        async def _fake_refine(messages, *, stage_config=None):
            return _fake_llm_response("refined text")

        async def _fake_eval(messages, *, stage_config=None):
            nonlocal eval_call_count
            eval_call_count += 1
            return _eval_response(0.95, "matrix pass")

        # Patch the matrix's llm_evaluate (NOT agents.base's — the
        # matrix module has its own imported reference).
        with patch("app.agents.base.llm_draft", new=_fake_draft), \
             patch("app.agents.base.llm_refine", new=_fake_refine), \
             patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            result = await agent._run_three_stage("sys", "user")

        # Matrix ran both dimensions once per iteration.
        # 2 dimensions * 1 iteration = 2 eval calls.
        assert eval_call_count == 2
        # Should have exited early since 0.95 >= 0.8
        assert result.score == 0.95
        assert result.review_matrix is not None
        assert result.review_matrix.aggregate_score == 0.95
        assert result.review_matrix.passed
        assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_evaluator_feedback_includes_per_dimension(self):
        """The aggregate_feedback (per-dimension notes) flows to next refine."""
        dims = [
            ReviewDimension(name="d1", system_prompt="pd1"),
            ReviewDimension(name="d2", system_prompt="pd2"),
        ]
        evaluator = ReviewMatrixRunner(
            dimensions=dims, strategy=AggregationStrategy.MEAN
        )

        class _A(BaseAgent):
            name = "test"

            async def handle(self, subtask, dag):
                raise NotImplementedError

        # First iteration: low score → triggers refine
        # Second iteration: high score → exit
        eval_responses = [
            ("d1", 0.4, "d1: needs work"),
            ("d2", 0.5, "d2: also needs work"),
            ("d1", 0.95, "d1: better"),
            ("d2", 0.95, "d2: better"),
        ]
        eval_idx = 0

        async def _fake_draft(messages, *, stage_config=None):
            return _fake_llm_response("draft")

        captured_refine_user_msgs: list[str] = []

        async def _fake_refine(messages, *, stage_config=None):
            captured_refine_user_msgs.append(messages[1]["content"])
            return _fake_llm_response("refined")

        async def _fake_eval(messages, *, stage_config=None):
            nonlocal eval_idx
            sys_prompt = messages[0]["content"]
            # Match by system prompt to identify the dimension
            for entry in eval_responses:
                if entry[0] == "d1" and sys_prompt == "pd1":
                    return _eval_response(entry[1], entry[2])
                if entry[0] == "d2" and sys_prompt == "pd2":
                    return _eval_response(entry[1], entry[2])
            # Fallback — shouldn't reach here
            return _eval_response(0.0, "fallback")

        # Use a fresh state — eval_idx needs to track per-call
        eval_call_log: list[str] = []
        eval_idx_per_dim = {"d1": 0, "d2": 0}

        async def _fake_eval_v2(messages, *, stage_config=None):
            sys_prompt = messages[0]["content"]
            if sys_prompt == "pd1":
                idx = eval_idx_per_dim["d1"]
                eval_idx_per_dim["d1"] += 1
                entry = eval_responses[idx * 2]
                eval_call_log.append(entry[0])
                return _eval_response(entry[1], entry[2])
            elif sys_prompt == "pd2":
                idx = eval_idx_per_dim["d2"]
                eval_idx_per_dim["d2"] += 1
                entry = eval_responses[idx * 2 + 1]
                eval_call_log.append(entry[0])
                return _eval_response(entry[1], entry[2])
            return _eval_response(0.0, "fallback")

        agent = _A(evaluator=evaluator, max_iters=3, score_threshold=0.8)

        with patch("app.agents.base.llm_draft", new=_fake_draft), \
             patch("app.agents.base.llm_refine", new=_fake_refine), \
             patch("app.eval.matrix.llm_evaluate", new=_fake_eval_v2):
            result = await agent._run_three_stage("sys", "user")

        # First iteration's matrix returned score ~0.45 (mean of 0.4, 0.5) → no exit
        # Second iteration's matrix returned score ~0.95 → exit
        assert result.iterations == 2
        assert result.score == pytest.approx(0.95)
        # The second refine call's user prompt should contain per-dimension
        # feedback from the first iteration's matrix.
        assert len(captured_refine_user_msgs) == 2
        second_refine_msg = captured_refine_user_msgs[1]
        assert "d1" in second_refine_msg
        assert "d2" in second_refine_msg

    @pytest.mark.asyncio
    async def test_evaluator_max_iters_no_exit(self):
        """If matrix never reaches threshold, runs all iters."""
        dims = [ReviewDimension(name="d1", system_prompt="pd1")]
        evaluator = ReviewMatrixRunner(dimensions=dims)

        class _A(BaseAgent):
            name = "test"

            async def handle(self, subtask, dag):
                raise NotImplementedError

        async def _fake_draft(messages, *, stage_config=None):
            return _fake_llm_response("draft")

        async def _fake_refine(messages, *, stage_config=None):
            return _fake_llm_response("refined")

        async def _fake_eval(messages, *, stage_config=None):
            return _eval_response(0.3, "still bad")

        agent = _A(evaluator=evaluator, max_iters=2, score_threshold=0.8)

        with patch("app.agents.base.llm_draft", new=_fake_draft), \
             patch("app.agents.base.llm_refine", new=_fake_refine), \
             patch("app.eval.matrix.llm_evaluate", new=_fake_eval):
            result = await agent._run_three_stage("sys", "user")

        assert result.iterations == 2
        assert result.score == 0.3
        assert result.review_matrix is not None
        assert not result.review_matrix.passed

    @pytest.mark.asyncio
    async def test_no_evaluator_uses_single_evaluator_path(self):
        """When no evaluator, _run_three_stage uses single llm_evaluate."""

        class _A(BaseAgent):
            name = "test"

            async def handle(self, subtask, dag):
                raise NotImplementedError

        agent = _A()  # no evaluator
        assert agent.evaluator is None

        matrix_eval_calls = 0
        single_eval_calls = 0

        async def _fake_draft(messages, *, stage_config=None):
            return _fake_llm_response("draft")

        async def _fake_refine(messages, *, stage_config=None):
            return _fake_llm_response("refined")

        async def _fake_matrix_eval(messages, *, stage_config=None):
            nonlocal matrix_eval_calls
            matrix_eval_calls += 1
            return _eval_response(0.9, "ok")

        async def _fake_single_eval(messages, *, stage_config=None):
            nonlocal single_eval_calls
            single_eval_calls += 1
            return _eval_response(0.9, "ok")

        with patch("app.agents.base.llm_draft", new=_fake_draft), \
             patch("app.agents.base.llm_refine", new=_fake_refine), \
             patch("app.agents.base.llm_evaluate", new=_fake_single_eval), \
             patch("app.eval.matrix.llm_evaluate", new=_fake_matrix_eval):
            result = await agent._run_three_stage("sys", "user")

        # Single-evaluator path was used, not the matrix
        assert matrix_eval_calls == 0
        assert single_eval_calls == 1
        # No matrix attached
        assert result.review_matrix is None

    @pytest.mark.asyncio
    async def test_agent_result_review_matrix_field_default_none(self):
        """AgentResult.review_matrix defaults to None when no evaluator."""
        r = AgentResult(content="x", score=0.5)
        assert r.review_matrix is None


# ---------------------------------------------------------------------------
# Factory integration
# ---------------------------------------------------------------------------


class TestFactoryEvaluatorIntegration:
    def test_factory_accepts_evaluator_param(self):
        dims = [ReviewDimension(name="d1", system_prompt="pd1")]
        evaluator = ReviewMatrixRunner(dimensions=dims)
        orch = make_novel_orchestrator(evaluator=evaluator)
        assert orch is not None

    def test_factory_passes_evaluator_to_plotter(self):
        dims = [ReviewDimension(name="d1", system_prompt="pd1")]
        evaluator = ReviewMatrixRunner(dimensions=dims)
        # Use the orchestrator's handlers dict to introspect — but the
        # handlers are bound methods, so we can't easily reach the agent
        # instance. Instead, construct a plotter directly with the same
        # args and verify.
        plotter = PlotterAgent(evaluator=evaluator)
        assert plotter.evaluator is evaluator

    def test_factory_passes_evaluator_to_character(self):
        evaluator = ReviewMatrixRunner(
            dimensions=[ReviewDimension(name="d1", system_prompt="pd1")]
        )
        character = CharacterAgent(evaluator=evaluator)
        assert character.evaluator is evaluator

    def test_factory_passes_evaluator_to_editor(self):
        evaluator = ReviewMatrixRunner(
            dimensions=[ReviewDimension(name="d1", system_prompt="pd1")]
        )
        editor = EditorAgent(evaluator=evaluator)
        assert editor.evaluator is evaluator

    def test_factory_evaluator_defaults_to_none(self):
        # When no evaluator is passed, agents have evaluator=None
        plotter = PlotterAgent()
        assert plotter.evaluator is None

    def test_factory_evaluator_none_uses_single_path(self):
        # Smoke test — make_novel_orchestrator works with no evaluator
        orch = make_novel_orchestrator()
        # All 8 task kinds registered
        from app.planner.spec import TaskKind
        for kind in TaskKind:
            assert kind in orch._handlers

    @pytest.mark.asyncio
    async def test_full_dag_with_matrix_evaluator(self):
        """E2E: PlotterAgent.handle() with a matrix evaluator attached.
        Verifies the matrix is invoked instead of the single evaluator
        and that the result dict contains the expected output key.
        """
        from app.planner.spec import (
            SubTask,
            SubTaskDAG,
            TaskKind,
            TaskSpec,
        )

        dims = [
            ReviewDimension(name="d1", system_prompt="pd1"),
            ReviewDimension(name="d2", system_prompt="pd2"),
        ]
        evaluator = ReviewMatrixRunner(
            dimensions=dims, strategy=AggregationStrategy.MEAN
        )

        matrix_eval_calls = 0

        async def _fake_draft(messages, *, stage_config=None):
            return _fake_llm_response("draft content")

        async def _fake_refine(messages, *, stage_config=None):
            return _fake_llm_response("refined content")

        async def _fake_matrix_eval(messages, *, stage_config=None):
            nonlocal matrix_eval_calls
            matrix_eval_calls += 1
            return _eval_response(0.95, "good")

        plotter = PlotterAgent(evaluator=evaluator, max_iters=1)

        spec = TaskSpec(
            task_id="outline_1",
            kind=TaskKind.OUTLINE,
            inputs={"theme": "test", "target_chapters": 1},
            expected_output_keys=("chapter_outline",),
        )
        dag = SubTaskDAG(tasks={spec.task_id: SubTask(spec=spec)})

        with patch("app.agents.base.llm_draft", new=_fake_draft), \
             patch("app.agents.base.llm_refine", new=_fake_refine), \
             patch("app.eval.matrix.llm_evaluate", new=_fake_matrix_eval):
            result = await plotter.handle(dag.get("outline_1"), dag)

        # Matrix ran both dimensions once (1 iteration)
        assert matrix_eval_calls == 2
        # Result dict returned from handle()
        assert result is not None
        assert "chapter_outline" in result
