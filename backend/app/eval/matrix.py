"""Review matrix + parallel runner for multi-dimensional evaluation.

The ReviewMatrixRunner runs all ReviewDimensions in parallel against the
same draft text via asyncio.gather. Each dimension's LLM call uses the
existing `app.llm.clients.evaluate` wrapper so BYOK credentials flow
through identically to the single-evaluator path.

Aggregation strategies:
  - WEIGHTED_AVERAGE (default): sum(score_i * weight_i) / sum(weight_i).
        Best for general use — high scores on one dimension can partially
        compensate for lower scores on another.
  - MIN_SCORE: min(score_i) across all dimensions.
        Strictest — any single dimension failing drags the composite
        to that score. Use when *every* dimension must pass independently.
  - MEAN: simple arithmetic mean (ignores weights).
        Use for debugging or when weights aren't meaningful.

Each dimension's LLM call is independent — a failure in one dimension
(e.g. JSON parse error, network timeout) does NOT fail the whole matrix.
Instead, the failing dimension is recorded with score=0.0 and
feedback="error: <detail>" so the agent can decide how to react.
"""
from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.eval.dimensions import ReviewDimension, make_default_dimensions
from app.llm import evaluate as llm_evaluate
from app.schemas.chat import StageConfig

# Default max concurrent LLM calls during evaluation. Overridden at runtime
# by settings.pipeline_eval_concurrency. Low-rate-limit providers
# (e.g. mimo-v2.5) need 1 to avoid 429s; the runner reads the setting in
# __init__ so callers can still pass an explicit max_concurrent for tests.
_MAX_CONCURRENT_EVAL_CALLS = 1

_EVAL_DIM_TIMEOUT = 30  # seconds per dimension

logger = logging.getLogger(__name__)


class AggregationStrategy(enum.Enum):
    """How to combine per-dimension scores into a composite score."""

    WEIGHTED_AVERAGE = "weighted_average"
    MIN_SCORE = "min_score"
    MEAN = "mean"


@dataclass(frozen=True)
class ReviewResult:
    """Outcome of a single dimension's evaluation.

    `dimension_name` matches the ReviewDimension.name. `score` is the
    parsed 0.0-1.0 score. `feedback` is the LLM's one-sentence note
    (may be empty if parsing fell back). `raw_eval` is the raw LLM
    response text — useful for debugging parse failures.
    """

    dimension_name: str
    score: float = 0.0
    feedback: str = ""
    raw_eval: str = ""
    error: str = ""

    @property
    def failed(self) -> bool:
        """True if this dimension's evaluation errored out."""
        return bool(self.error)


@dataclass(frozen=True)
class ReviewMatrix:
    """Aggregate result of all dimensions' evaluations.

    `aggregate_score` is computed by the chosen AggregationStrategy.
    `aggregate_feedback` is a multi-line string joining per-dimension
    feedback. `passed` is True when aggregate_score >= threshold.
    """

    results: tuple[ReviewResult, ...] = field(default_factory=tuple)
    aggregate_score: float = 0.0
    aggregate_feedback: str = ""
    threshold: float = 0.8
    strategy: AggregationStrategy = AggregationStrategy.WEIGHTED_AVERAGE

    @property
    def passed(self) -> bool:
        return self.aggregate_score >= self.threshold

    @property
    def failed_dimensions(self) -> list[ReviewResult]:
        """Dimensions whose evaluation errored out (LLM call failed)."""
        return [r for r in self.results if r.failed]

    def get(self, dimension_name: str) -> ReviewResult | None:
        """Look up a result by dimension name. None if not present."""
        for r in self.results:
            if r.dimension_name == dimension_name:
                return r
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (for orchestrator result storage)."""
        return {
            "aggregate_score": self.aggregate_score,
            "aggregate_feedback": self.aggregate_feedback,
            "threshold": self.threshold,
            "strategy": self.strategy.value,
            "passed": self.passed,
            "dimensions": [
                {
                    "name": r.dimension_name,
                    "score": r.score,
                    "feedback": r.feedback,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


class ReviewMatrixRunner:
    """Runs all dimensions' evaluations in parallel and aggregates results.

    The runner holds a list of ReviewDimensions and a chosen
    AggregationStrategy. `evaluate()` runs all dimensions concurrently
    against the same text via asyncio.gather.

    The runner uses `app.llm.clients.evaluate` for each LLM call so BYOK
    credentials flow through identically to the single-evaluator path.
    Each dimension's `evaluate` call uses the same StageConfig (the
    user's BYOK evaluate-stage config) — per-dimension provider routing
    is a future enhancement, not currently needed.
    """

    def __init__(
        self,
        dimensions: list[ReviewDimension] | None = None,
        *,
        strategy: AggregationStrategy = AggregationStrategy.WEIGHTED_AVERAGE,
        threshold: float = 0.8,
        max_concurrent: int | None = None,
    ) -> None:
        self.dimensions: list[ReviewDimension] = (
            dimensions if dimensions is not None else make_default_dimensions()
        )
        if not self.dimensions:
            raise ValueError("ReviewMatrixRunner requires at least one dimension")
        self.strategy = strategy
        self.threshold = threshold
        if max_concurrent is None:
            max_concurrent = getattr(
                settings, "pipeline_eval_concurrency", _MAX_CONCURRENT_EVAL_CALLS
            )
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def add(self, dimension: ReviewDimension) -> None:
        """Append a dimension. Replaces existing by name."""
        self.dimensions = [
            d for d in self.dimensions if d.name != dimension.name
        ] + [dimension]

    def remove(self, name: str) -> bool:
        """Remove a dimension by name. Returns True if removed."""
        before = len(self.dimensions)
        self.dimensions = [d for d in self.dimensions if d.name != name]
        return len(self.dimensions) < before

    async def evaluate(
        self,
        text: str,
        *,
        stage_config: StageConfig | None = None,
        threshold: float | None = None,
    ) -> ReviewMatrix:
        """Run all dimensions against `text` with bounded concurrency.

        Each dimension's LLM call is independent — failures are caught
        and recorded as ReviewResult(score=0.0, error="...") so the
        matrix always returns a result for every dimension.

        `threshold` overrides the runner's threshold for this call only.

        Concurrency is bounded by `self._semaphore` (default 3) to avoid
        thundering-herd rate-limit errors when many dimensions hit the
        same provider endpoint simultaneously.
        """
        eff_threshold = (
            threshold if threshold is not None else self.threshold
        )
        if not text:
            # No text to evaluate — return all-zero matrix without LLM calls.
            results = tuple(
                ReviewResult(
                    dimension_name=d.name,
                    score=0.0,
                    feedback="",
                    error="empty input text",
                )
                for d in self.dimensions
            )
            return self._aggregate(results, eff_threshold)

        # Run all dimensions in parallel. asyncio.gather with
        # return_exceptions=True ensures one failure doesn't cancel others.
        tasks = [
            self._eval_dimension(d, text, stage_config) for d in self.dimensions
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[ReviewResult] = []
        for dim, raw in zip(self.dimensions, raw_results):
            if isinstance(raw, Exception):
                # Unexpected exception in the gather wrapper — record as error.
                logger.warning(
                    "review_matrix dimension=%s raised: %r", dim.name, raw
                )
                results.append(
                    ReviewResult(
                        dimension_name=dim.name,
                        score=0.0,
                        feedback="",
                        error=f"exception: {type(raw).__name__}: {raw}",
                    )
                )
            else:
                results.append(raw)

        return self._aggregate(tuple(results), eff_threshold)

    async def _eval_dimension(
        self,
        dim: ReviewDimension,
        text: str,
        stage_config: StageConfig | None,
    ) -> ReviewResult:
        """Run a single dimension's evaluation. Catches all exceptions.

        Acquires the concurrency semaphore before making the LLM call
        so that at most `max_concurrent` calls hit the provider at once.
        Each call is guarded by a timeout to prevent hanging on slow providers.
        """
        async with self._semaphore:
            try:
                messages = [
                    {"role": "system", "content": dim.system_prompt},
                    {"role": "user", "content": text},
                ]
                resp = await asyncio.wait_for(
                    llm_evaluate(messages, stage_config=stage_config),
                    timeout=_EVAL_DIM_TIMEOUT,
                )
                raw_eval = resp.choices[0].message.content or ""
                score, feedback = _parse_eval(raw_eval)
                return ReviewResult(
                    dimension_name=dim.name,
                    score=score,
                    feedback=feedback,
                    raw_eval=raw_eval,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "review_matrix dimension=%s timed out after %ds",
                    dim.name, _EVAL_DIM_TIMEOUT,
                )
                return ReviewResult(
                    dimension_name=dim.name,
                    score=0.5,
                    feedback=f"evaluation timed out after {_EVAL_DIM_TIMEOUT}s",
                    error=f"timeout after {_EVAL_DIM_TIMEOUT}s",
                )
            except Exception as e:  # noqa: BLE001 — record any failure
                logger.warning(
                    "review_matrix dimension=%s eval failed: %r", dim.name, e
                )
                return ReviewResult(
                    dimension_name=dim.name,
                    score=0.0,
                    feedback="",
                    error=f"{type(e).__name__}: {e}",
                )

    def _aggregate(
        self,
        results: tuple[ReviewResult, ...],
        threshold: float,
    ) -> ReviewMatrix:
        """Combine per-dimension results into a ReviewMatrix."""
        score = self._compute_score(results)
        feedback = self._format_feedback(results)
        return ReviewMatrix(
            results=results,
            aggregate_score=score,
            aggregate_feedback=feedback,
            threshold=threshold,
            strategy=self.strategy,
        )

    def _compute_score(self, results: tuple[ReviewResult, ...]) -> float:
        """Apply the aggregation strategy to compute the composite score.

        Dimensions whose LLM call errored out (e.g. a transient 429) are
        excluded so a rate-limited dimension doesn't drag the composite
        to 0 and force wasteful refine iterations. If every dimension
        failed, returns 0.0.
        """
        if not results:
            return 0.0
        usable = [r for r in results if not r.failed]
        if not usable:
            return 0.0
        scores = [r.score for r in usable]
        if self.strategy == AggregationStrategy.MIN_SCORE:
            return min(scores)
        if self.strategy == AggregationStrategy.MEAN:
            return sum(scores) / len(scores)
        # WEIGHTED_AVERAGE (default)
        weights = [
            self._dim_weight(r.dimension_name) for r in usable
        ]
        total_weight = sum(weights)
        if total_weight <= 0:
            # All weights somehow zero — fall back to mean.
            return sum(scores) / len(scores)
        return sum(s * w for s, w in zip(scores, weights)) / total_weight

    def _dim_weight(self, name: str) -> float:
        """Look up a dimension's weight by name. Defaults to 1.0."""
        for d in self.dimensions:
            if d.name == name:
                return d.weight
        return 1.0

    @staticmethod
    def _format_feedback(results: tuple[ReviewResult, ...]) -> str:
        """Join per-dimension feedback into a single string.

        Each line: "<dimension>: <feedback>" (or "<dimension>: error: ..." on failure).
        Empty feedback lines are skipped.
        """
        lines: list[str] = []
        for r in results:
            if r.failed:
                lines.append(f"{r.dimension_name}: error: {r.error}")
            elif r.feedback:
                lines.append(f"{r.dimension_name}: {r.feedback}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON parsing — duplicated from app.agents.base to keep the eval module
# decoupled. If parsing changes, update both copies.
# ---------------------------------------------------------------------------


def _parse_eval(raw: str) -> tuple[float, str]:
    """Parse the evaluator's response to (score, feedback).

    Tries, in order: clean JSON, a JSON object embedded in prose, a number
    anchored to the 'score' keyword, then the first number anywhere. The
    keyword step is what saves us from models that echo the prompt's
    '0.0-1.0 scale' before stating the actual score — a bare first-number
    regex would grab that leading 0.0 and report score=0.0, which forces
    the pipeline to loop all refine iterations for nothing.

    Score is clamped to [0.0, 1.0].
    """
    import json
    import re

    def _clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    if not raw:
        return 0.0, ""

    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE
    ).strip()

    # 1. Clean JSON.
    try:
        data = json.loads(cleaned)
        return _clamp(float(data["score"])), str(data.get("feedback", ""))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        pass

    # 2. JSON object embedded in prose (e.g. "Here: {\"score\": 0.8 ...}").
    obj_match = re.search(r"\{[^{}]*\}", cleaned)
    if obj_match:
        try:
            data = json.loads(obj_match.group(0))
            if "score" in data:
                return _clamp(float(data["score"])), str(data.get("feedback", ""))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # 3. Number anchored to the 'score' keyword — avoids the leading
    #    0.0 of a "0.0-1.0 scale" echo.
    kw_match = re.search(
        r"score\b[^\d]*([0-9]*\.?[0-9]+)", cleaned, re.IGNORECASE
    )
    if kw_match:
        return _clamp(float(kw_match.group(1))), cleaned[:200]

    # 4. First number anywhere as a last resort.
    score_match = re.search(r"([0-9]*\.?[0-9]+)", cleaned)
    if score_match:
        return _clamp(float(score_match.group(1))), cleaned[:200]

    return 0.0, cleaned[:200]
