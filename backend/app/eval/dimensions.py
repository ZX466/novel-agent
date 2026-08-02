"""Review dimensions for multi-agent evaluation.

Each dimension is an independent evaluator with its own system prompt
and weight. The ReviewMatrixRunner runs all dimensions in parallel
against the same draft text and aggregates the results into a single
ReviewMatrix (composite score + per-dimension feedback).

Default dimensions (Novel-writing context):
  - coherence:        logical flow within and across scenes
  - character_consistency: characters act/speak consistently with their
                              established profiles
  - prose_quality:    prose style, rhythm, sensory detail
  - plot_logic:       causality, foreshadowing, payoff, no plot holes
  - world_consistency: adherence to established worldbuilding rules

Weights are positive floats and need not sum to 1 — the aggregator
normalizes. Higher weight = more influence on the composite score.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewDimension:
    """A single evaluation dimension.

    `name` is a short identifier used as the key in ReviewMatrix.results.
    `system_prompt` instructs the LLM how to score the text on this
        dimension — must follow the same JSON output contract as
        EVAL_SYSTEM_PROMPT in app.agents.base: respond with ONLY a JSON
        object {"score": <float 0.0-1.0>, "feedback": "<short sentence>"}.
    `weight` is a positive float; higher = more influence on the
        composite score. The aggregator normalizes weights to sum to 1.
    `description` is for human-facing docs only (not sent to the LLM).
    """

    name: str
    system_prompt: str
    weight: float = 1.0
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ReviewDimension.name must be non-empty")
        if self.weight <= 0:
            raise ValueError(
                f"ReviewDimension {self.name!r}: weight must be > 0, got {self.weight}"
            )

    def with_overrides(self, **kwargs: Any) -> "ReviewDimension":
        """Return a copy with the given fields replaced.

        Convenient for tests and for production code that wants to tweak
        a single dimension (e.g. raise the weight of `plot_logic`).
        """
        return ReviewDimension(
            name=kwargs.get("name", self.name),
            system_prompt=kwargs.get("system_prompt", self.system_prompt),
            weight=kwargs.get("weight", self.weight),
            description=kwargs.get("description", self.description),
        )


# ---------------------------------------------------------------------------
# Default dimensions
# ---------------------------------------------------------------------------

_COHERENCE_PROMPT = (
    "You are a coherence reviewer for novels. Score the text on a 0.0-1.0 scale "
    "based on logical flow between sentences, paragraphs, and scenes. "
    "Look for: non-sequiturs, abrupt POV shifts, missing transitions, "
    "time/sequence inconsistencies. "
    'Respond with ONLY a JSON object: {"score": <float>, "feedback": "<short sentence>"}. '
    "No prose, no markdown fences."
)

_CHARACTER_CONSISTENCY_PROMPT = (
    "You are a character consistency reviewer for novels. Score the text on a "
    "0.0-1.0 scale based on whether characters act, speak, and think in ways "
    "consistent with their established profiles. Look for: out-of-character "
    "dialogue, motivation drift, inconsistent knowledge/skills, voice mismatch. "
    'Respond with ONLY a JSON object: {"score": <float>, "feedback": "<short sentence>"}. '
    "No prose, no markdown fences."
)

_PROSE_QUALITY_PROMPT = (
    "You are a prose quality reviewer for novels. Score the text on a 0.0-1.0 scale "
    "based on style, rhythm, sensory detail, and word choice. Look for: cliché, "
    "repetitive sentence structure, weak verbs, telling instead of showing, "
    "purple prose. "
    'Respond with ONLY a JSON object: {"score": <float>, "feedback": "<short sentence>"}. '
    "No prose, no markdown fences."
)

_PLOT_LOGIC_PROMPT = (
    "You are a plot logic reviewer for novels. Score the text on a 0.0-1.0 scale "
    "based on causality, foreshadowing, setup/payoff, and absence of plot holes. "
    "Look for: unearned resolutions, contradictions, deus ex machina, broken "
    "promises to the reader. "
    'Respond with ONLY a JSON object: {"score": <float>, "feedback": "<short sentence>"}. '
    "No prose, no markdown fences."
)

_WORLD_CONSISTENCY_PROMPT = (
    "You are a world consistency reviewer for novels. Score the text on a 0.0-1.0 scale "
    "based on adherence to the established worldbuilding rules (geography, magic "
    "system, technology level, social norms, history). Look for: anachronisms, "
    "rule violations, contradictions with prior chapters' world facts. "
    'Respond with ONLY a JSON object: {"score": <float>, "feedback": "<short sentence>"}. '
    "No prose, no markdown fences."
)

_CROSS_CHAPTER_PROMPT = (
    "You are a cross-chapter consistency reviewer for novels. Score the text on a "
    "0.0-1.0 scale based on whether it stays consistent with prior chapters: "
    "character traits and relationships, ongoing plot threads, timeline of events, "
    "established facts and foreshadowing, unresolved mysteries. Look for: "
    "contradictions with earlier chapters, forgotten subplots, timeline errors, "
    "characters acting against their prior development. "
    'Respond with ONLY a JSON object: {"score": <float>, "feedback": "<short sentence>"}. '
    "No prose, no markdown fences."
)


def make_default_dimensions() -> list[ReviewDimension]:
    """Return the default 6-dimension review matrix.

    Returns a fresh list each call — callers may mutate, reorder, or
    remove entries without affecting subsequent calls.
    """
    return [
        ReviewDimension(
            name="coherence",
            system_prompt=_COHERENCE_PROMPT,
            weight=1.0,
            description="Logical flow within and across scenes.",
        ),
        ReviewDimension(
            name="character_consistency",
            system_prompt=_CHARACTER_CONSISTENCY_PROMPT,
            weight=1.2,
            description="Characters act/speak consistently with their profiles.",
        ),
        ReviewDimension(
            name="prose_quality",
            system_prompt=_PROSE_QUALITY_PROMPT,
            weight=1.0,
            description="Style, rhythm, sensory detail, word choice.",
        ),
        ReviewDimension(
            name="plot_logic",
            system_prompt=_PLOT_LOGIC_PROMPT,
            weight=1.3,
            description="Causality, foreshadowing, payoff, no plot holes.",
        ),
        ReviewDimension(
            name="world_consistency",
            system_prompt=_WORLD_CONSISTENCY_PROMPT,
            weight=1.0,
            description="Adherence to established worldbuilding rules.",
        ),
        ReviewDimension(
            name="cross_chapter_consistency",
            system_prompt=_CROSS_CHAPTER_PROMPT,
            weight=1.1,
            description="Consistency with prior chapters (timeline, subplots, character arcs).",
        ),
    ]
