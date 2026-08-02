"""Pipeline state schema."""
from __future__ import annotations

from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import ProviderConfig


class PipelineState(TypedDict, total=False):
    """State passed between draft -> refine -> evaluate -> safety_check nodes.

    `total=False` so the initial invoke dict only needs to carry `topic`.
    Nodes add their outputs as the graph progresses.

    `provider_config` is optional BYOK credentials that flow through to all
    LLM calls. When None, nodes fall back to .env settings.

    `session` is an optional SQLAlchemy async session. When present,
    the evaluate node persists a quality score to the `evaluations`
    table for trend analysis, and the draft node retrieves relevant
    memories to ground the draft in established lore.

    `evaluator` is an optional ReviewMatrixRunner. When present, the
    evaluate node uses multi-dimensional parallel evaluation instead of
    the single llm_evaluate call. The aggregate score and per-dimension
    feedback drive the refine loop identically to the agent path.

    `novel_id` scopes memory retrieval and evaluation persistence to a
    specific novel. When None, the draft node skips retrieval (no
    cross-novel leakage).
    """
    topic: str                          # user's input prompt
    draft: str                          # DeepSeek / BYOK draft output
    refined: str                        # Qwen / BYOK refine output (current iteration)
    score: float                        # Claude / BYOK evaluation score [0.0, 1.0]
    feedback: str                       # evaluator feedback for next refine iteration
    iterations: int                     # number of refine passes completed
    provider_config: ProviderConfig | None  # BYOK credentials (None = use .env)
    session: AsyncSession | None        # optional DB session for eval persistence + retrieval
    evaluator: Any | None               # optional ReviewMatrixRunner for multi-dim eval
    novel_id: int | None                # novel scope for retrieval + eval persistence
    retrieved_context: str              # lore injected by retrieval_node (empty = no context)
    task_type: str                      # "generate" | "continue" | "rewrite" | "polish" | "outline"
    safety_passed: bool                 # whether safety check passed
    safety_report: dict                 # safety check details
    review_details: dict                # per-dimension evaluation details
    fallback_mode: bool                 # True when a stage was skipped due to failure
    fallback_reason: str                # which stage failed and was skipped
    on_token: Any                       # async callback for real-time streaming: await on_token(text)
