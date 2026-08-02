"""Task specification data structures for the natural-language parser.

`ParsedTaskSpec` is the structured output of `TaskParser.parse()`. It
captures the information needed to call `PlannerAgent.plan()` plus
optional style/genre hints that downstream agents can read from
`extra_inputs`.

Design:
  - Immutable (frozen=True) — once parsed, the spec doesn't change.
  - All optional fields have sensible defaults so the parser can
    return a partial spec when only some fields are extractable.
  - `extra_inputs` carries free-form metadata (genre, tone, audience,
    style_notes) that templates currently ignore but future agents can
    consume (e.g. PlotterAgent can read genre to steer prompt tone).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParsedTaskSpec:
    """Structured specification parsed from natural-language input.

    Fields:
      premise: the core story premise / theme. Required.
      chapter_count: number of chapters. Defaults to 1.
      target_words_per_chapter: target word count per chapter. Defaults
        to 3000. The parser uses heuristics (regex on numbers + words
        like "字" / "words") to extract this.
      genre: optional genre hint (e.g. "侦探" / "sci-fi" / "fantasy").
        None when not detectable.
      tone: optional tone hint (e.g. "dark" / "light" / "comedic").
        None when not detectable.
      language: detected language of the input ("zh" / "en"). Defaults
        to "zh" since the project's primary audience is Chinese.
      extra_inputs: free-form dict for additional metadata. Merged
        into each TaskSpec.inputs by the planner (future enhancement).
      parser_source: which parser mode produced this spec — "rule" or
        "llm". Useful for debugging and A/B testing.
      parser_confidence: 0.0-1.0 confidence score. Rule-based gives
        1.0 when all fields extracted, lower when defaults used. LLM
        gives a self-reported confidence.
    """

    premise: str
    chapter_count: int = 1
    target_words_per_chapter: int = 3000
    genre: str | None = None
    tone: str | None = None
    language: str = "zh"
    extra_inputs: dict[str, Any] = field(default_factory=dict)
    parser_source: str = "rule"
    parser_confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.premise or not self.premise.strip():
            raise ValueError("ParsedTaskSpec.premise must be non-empty")
        if self.chapter_count < 1:
            raise ValueError(
                f"chapter_count must be >= 1, got {self.chapter_count}"
            )
        if self.target_words_per_chapter < 100:
            raise ValueError(
                f"target_words_per_chapter must be >= 100, got {self.target_words_per_chapter}"
            )
        if not 0.0 <= self.parser_confidence <= 1.0:
            raise ValueError(
                f"parser_confidence must be in [0.0, 1.0], got {self.parser_confidence}"
            )

    def to_planner_kwargs(self) -> dict[str, Any]:
        """Convert to the kwargs expected by PlannerAgent.plan().

        Includes only the fields the planner currently consumes. The
        extra_inputs dict carries the rest for future use.
        """
        return {
            "premise": self.premise,
            "chapter_count": self.chapter_count,
            "target_words_per_chapter": self.target_words_per_chapter,
            "extra_inputs": dict(self.extra_inputs) or None,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for API responses / logging."""
        return {
            "premise": self.premise,
            "chapter_count": self.chapter_count,
            "target_words_per_chapter": self.target_words_per_chapter,
            "genre": self.genre,
            "tone": self.tone,
            "language": self.language,
            "extra_inputs": dict(self.extra_inputs),
            "parser_source": self.parser_source,
            "parser_confidence": self.parser_confidence,
        }
