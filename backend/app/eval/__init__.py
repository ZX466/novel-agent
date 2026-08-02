"""Eval subpackage — multi-dimensional review matrix.

Public API:
  - ReviewDimension: a single evaluation dimension (name, prompt, weight)
  - make_default_dimensions(): built-in 5-dimension set for novels
  - ReviewResult: outcome of one dimension's evaluation
  - ReviewMatrix: aggregate of all dimensions + composite score
  - ReviewMatrixRunner: parallel runner + aggregator
  - AggregationStrategy: WEIGHTED_AVERAGE / MIN_SCORE / MEAN

Design:
  - Each dimension is an independent LLM evaluator with its own system
    prompt (e.g. coherence, character_consistency, prose_quality,
    plot_logic, world_consistency).
  - ReviewMatrixRunner.evaluate() runs all dimensions in parallel via
    asyncio.gather — failures in one dimension don't fail the whole
    matrix (recorded as ReviewResult(score=0.0, error="...")).
  - Three aggregation strategies: WEIGHTED_AVERAGE (default, uses
    dimension weights), MIN_SCORE (strictest), MEAN (ignores weights).
  - The runner uses app.llm.clients.evaluate so BYOK credentials flow
    through identically to the single-evaluator path.

Integration with BaseAgent:
  - BaseAgent accepts an optional `evaluator: ReviewMatrixRunner`.
  - When provided, _run_three_stage uses evaluator.evaluate() instead
    of the single llm_evaluate call. The composite score drives the
    early-exit threshold; aggregate_feedback is fed back to the refine
    stage just like the single-evaluator feedback.
  - AgentResult gains a `review_matrix` field (None when no evaluator).
"""
from app.eval.dimensions import (  # noqa: F401
    ReviewDimension,
    make_default_dimensions,
)
from app.eval.matrix import (  # noqa: F401
    AggregationStrategy,
    ReviewMatrix,
    ReviewMatrixRunner,
    ReviewResult,
)
