"""PlannerAgent — converts a user premise into a SubTaskDAG.

Two operating modes:
  - rule-based (default): selects a template based on chapter_count
  - LLM-assisted (optional): calls an LLM to refine template inputs
    (premise expansion, character count suggestion). Not yet wired —
    placeholder for P3 task parsing integration. When wired, the LLM
    output feeds `extra_inputs` which is now deep-merged into every
    task's inputs (previously dropped — see plan()).

Why split rule-based from LLM: rule-based is deterministic and fast.
LLM planning adds value only when premise is ambiguous or chapter
count is unknown. For the common case (user says "write a 5-chapter
novel about X"), the template is sufficient and avoids the latency +
cost of an extra LLM call.

`plan_novel(premise, chapter_count, ...)` is the convenience entry
point used by the orchestrator. It constructs a PlannerAgent and
delegates to the appropriate template.
"""
from __future__ import annotations

import logging
from typing import Any

from app.planner.spec import SubTaskDAG
from app.planner.templates import (
    multi_chapter_template,
    reflection_chapter_template,
    single_chapter_template,
)

logger = logging.getLogger(__name__)


class PlannerAgent:
    """Rule-based planner that selects a DAG template for the request.

    The agent is stateless — each `plan()` call returns a fresh DAG.
    Holding no state makes concurrent planning safe.
    """

    def plan(
        self,
        *,
        premise: str,
        chapter_count: int = 1,
        target_words_per_chapter: int = 3000,
        character_count: int | None = None,
        include_reflection: bool = False,
        extra_inputs: dict[str, Any] | None = None,
    ) -> SubTaskDAG:
        """Return a SubTaskDAG for the given premise.

        - chapter_count == 1 → single_chapter_template
        - chapter_count > 1  → multi_chapter_template
        - chapter_count < 1   → ValueError
        - include_reflection → reflection_chapter_template (adds a
          self-reflection pass after chapter_refine)

        When character_count is None the template's default is used
        (2 for single chapter, 4 for multi-chapter).

        `extra_inputs` is deep-merged into every task's `inputs` dict so
        caller-supplied overrides (tone, POV, language, etc.) reach the
        executing agents instead of being silently dropped. Previously
        this was logged-and-ignored; it now takes effect.
        """
        if not premise or not premise.strip():
            raise ValueError("premise must be non-empty")
        if chapter_count < 1:
            raise ValueError("chapter_count must be >= 1")

        premise = premise.strip()
        char_kw: dict[str, int] = (
            {"character_count": character_count} if character_count is not None else {}
        )
        extra = extra_inputs or {}
        if include_reflection:
            dag = reflection_chapter_template(
                premise=premise,
                chapter_count=chapter_count,
                target_words_per_chapter=target_words_per_chapter,
                extra_inputs=extra,
                **char_kw,
            )
        elif chapter_count == 1:
            dag = single_chapter_template(
                premise=premise,
                target_words=target_words_per_chapter,
                extra_inputs=extra,
                **char_kw,
            )
        else:
            dag = multi_chapter_template(
                premise=premise,
                chapter_count=chapter_count,
                target_words_per_chapter=target_words_per_chapter,
                extra_inputs=extra,
                **char_kw,
            )

        if extra_inputs:
            logger.info(
                "PlannerAgent: merged extra_inputs into %d tasks (keys=%s)",
                len(dag.tasks), list(extra_inputs.keys()),
            )
        logger.info(
            "PlannerAgent: planned DAG with %d tasks (chapter_count=%d reflection=%s)",
            len(dag.tasks), chapter_count, include_reflection,
        )
        return dag


# Module-level singleton — PlannerAgent holds no state.
_default_agent = PlannerAgent()


def plan_novel(
    premise: str,
    *,
    chapter_count: int = 1,
    target_words_per_chapter: int = 3000,
    character_count: int | None = None,
    include_reflection: bool = False,
    extra_inputs: dict[str, Any] | None = None,
) -> SubTaskDAG:
    """Convenience entry point used by the orchestrator."""
    return _default_agent.plan(
        premise=premise,
        chapter_count=chapter_count,
        target_words_per_chapter=target_words_per_chapter,
        character_count=character_count,
        include_reflection=include_reflection,
        extra_inputs=extra_inputs,
    )
