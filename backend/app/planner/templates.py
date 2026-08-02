"""Pre-defined DAG templates for common novel-writing flows.

Each template is a pure function that takes a specification (chapter
count, premise, etc.) and returns a SubTaskDAG. Keeping templates
separate from PlannerAgent allows:
  - Unit-testing templates in isolation (no LLM required)
  - Adding new templates without touching the agent class
  - Falling back to a template when the LLM planner is unavailable

All templates use stable task_id prefixes so downstream agents can
recognize their role (e.g. "chapter_draft_3" → third chapter draft).
"""
from __future__ import annotations

from app.planner.spec import (
    SubTask,
    SubTaskDAG,
    TaskKind,
    TaskSpec,
)


def single_chapter_template(
    *,
    premise: str,
    target_words: int = 3000,
    character_count: int = 2,
    extra_inputs: dict | None = None,
) -> SubTaskDAG:
    """Minimal flow: outline → world_setting → character → chapter_draft →
    chapter_refine → consistency_check → final_polish → safety_review.

    Useful for a single-chapter demo or for testing the orchestrator
    end-to-end without a multi-chapter commitment.

    `extra_inputs` (when provided) is deep-merged into every task's
    `inputs` dict so caller-supplied overrides (tone, point of view,
    language, etc.) actually reach the executing agents instead of being
    silently dropped.
    """
    extra_inputs = extra_inputs or {}
    specs: list[TaskSpec] = [
        TaskSpec(
            task_id="outline",
            kind=TaskKind.OUTLINE,
            inputs={**{"premise": premise, "chapter_count": 1}, **extra_inputs},
            expected_output_keys=("chapter_outline",),
        ),
        TaskSpec(
            task_id="world_setting",
            kind=TaskKind.WORLD_SETTING,
            inputs={**{"premise": premise}, **extra_inputs},
            depends_on=("outline",),
            expected_output_keys=("world_entries",),
        ),
        TaskSpec(
            task_id="character",
            kind=TaskKind.CHARACTER,
            inputs={**{"premise": premise, "count": character_count}, **extra_inputs},
            depends_on=("outline",),
            expected_output_keys=("characters",),
        ),
        TaskSpec(
            task_id="chapter_draft_1",
            kind=TaskKind.CHAPTER_DRAFT,
            inputs={
                **{
                    "chapter_index": 1,
                    "target_words": target_words,
                    "use_outline": True,
                },
                **extra_inputs,
            },
            depends_on=("outline", "world_setting", "character"),
            expected_output_keys=("content_text", "summary"),
        ),
        TaskSpec(
            task_id="chapter_refine_1",
            kind=TaskKind.CHAPTER_REFINE,
            inputs={**{"chapter_index": 1}, **extra_inputs},
            depends_on=("chapter_draft_1",),
            expected_output_keys=("content_text",),
        ),
        TaskSpec(
            task_id="consistency_check",
            kind=TaskKind.CONSISTENCY_CHECK,
            inputs={**{"chapter_indices": [1]}, **extra_inputs},
            depends_on=("chapter_refine_1",),
            expected_output_keys=("issues", "score"),
        ),
        TaskSpec(
            task_id="final_polish",
            kind=TaskKind.FINAL_POLISH,
            inputs={**{"chapter_indices": [1]}, **extra_inputs},
            depends_on=("consistency_check",),
            expected_output_keys=("content_text",),
        ),
        TaskSpec(
            task_id="safety_review",
            kind=TaskKind.SAFETY_REVIEW,
            inputs={**{"chapter_indices": [1]}, **extra_inputs},
            depends_on=("final_polish",),
            expected_output_keys=("passed", "issues"),
        ),
    ]
    return SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})


def _merge_inputs(base: dict, extra: dict) -> dict:
    """Deep-merge `extra` into `base` (extra wins on key collision).

    Nested dicts are merged recursively so callers can override a single
    nested key without clobbering the whole sub-dict.
    """
    out = dict(base)
    for k, v in extra.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge_inputs(out[k], v)
        else:
            out[k] = v
    return out


def multi_chapter_template(
    *,
    premise: str,
    chapter_count: int,
    target_words_per_chapter: int = 3000,
    character_count: int = 4,
    extra_inputs: dict | None = None,
) -> SubTaskDAG:
    """Multi-chapter flow: outline + setup once, then per-chapter
    draft→refine, then a single cross-chapter consistency check, polish,
    and safety review.

    Per-chapter tasks are independent of each other (each depends only
    on the shared outline+setup, not on prior chapters) so they can be
    parallelized by the orchestrator. A serial mode can be added by
    chaining chapter_draft_{i} → chapter_draft_{i+1} in a variant
    template if needed.

    `extra_inputs` is deep-merged into every task's inputs.
    """
    if chapter_count < 1:
        raise ValueError("chapter_count must be >= 1")

    extra_inputs = extra_inputs or {}
    specs: list[TaskSpec] = [
        TaskSpec(
            task_id="outline",
            kind=TaskKind.OUTLINE,
            inputs=_merge_inputs(
                {"premise": premise, "chapter_count": chapter_count}, extra_inputs
            ),
            expected_output_keys=("chapter_outline",),
        ),
        TaskSpec(
            task_id="world_setting",
            kind=TaskKind.WORLD_SETTING,
            inputs=_merge_inputs({"premise": premise}, extra_inputs),
            depends_on=("outline",),
            expected_output_keys=("world_entries",),
        ),
        TaskSpec(
            task_id="character",
            kind=TaskKind.CHARACTER,
            inputs=_merge_inputs(
                {"premise": premise, "count": character_count}, extra_inputs
            ),
            depends_on=("outline",),
            expected_output_keys=("characters",),
        ),
    ]
    # Per-chapter draft + refine. Each chapter depends on shared setup.
    chapter_draft_ids: list[str] = []
    chapter_refine_ids: list[str] = []
    for i in range(1, chapter_count + 1):
        draft_id = f"chapter_draft_{i}"
        refine_id = f"chapter_refine_{i}"
        chapter_draft_ids.append(draft_id)
        chapter_refine_ids.append(refine_id)
        specs.append(TaskSpec(
            task_id=draft_id,
            kind=TaskKind.CHAPTER_DRAFT,
            inputs=_merge_inputs(
                {
                    "chapter_index": i,
                    "target_words": target_words_per_chapter,
                    "use_outline": True,
                },
                extra_inputs,
            ),
            depends_on=("outline", "world_setting", "character"),
            expected_output_keys=("content_text", "summary"),
        ))
        specs.append(TaskSpec(
            task_id=refine_id,
            kind=TaskKind.CHAPTER_REFINE,
            inputs=_merge_inputs({"chapter_index": i}, extra_inputs),
            depends_on=(draft_id,),
            expected_output_keys=("content_text",),
        ))

    # Cross-chapter consistency + polish + safety.
    specs.append(TaskSpec(
        task_id="consistency_check",
        kind=TaskKind.CONSISTENCY_CHECK,
        inputs=_merge_inputs(
            {"chapter_indices": list(range(1, chapter_count + 1))}, extra_inputs
        ),
        depends_on=tuple(chapter_refine_ids),
        expected_output_keys=("issues", "score"),
    ))
    specs.append(TaskSpec(
        task_id="final_polish",
        kind=TaskKind.FINAL_POLISH,
        inputs=_merge_inputs(
            {"chapter_indices": list(range(1, chapter_count + 1))}, extra_inputs
        ),
        depends_on=("consistency_check",),
        expected_output_keys=("content_text",),
    ))
    specs.append(TaskSpec(
        task_id="safety_review",
        kind=TaskKind.SAFETY_REVIEW,
        inputs=_merge_inputs(
            {"chapter_indices": list(range(1, chapter_count + 1))}, extra_inputs
        ),
        depends_on=("final_polish",),
        expected_output_keys=("passed", "issues"),
    ))

    return SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})


def reflection_chapter_template(
    *,
    premise: str,
    chapter_count: int = 1,
    target_words_per_chapter: int = 3000,
    character_count: int = 2,
    extra_inputs: dict | None = None,
) -> SubTaskDAG:
    """Extended flow with a self-reflection pass after refinement.

    Adds a REFLECTION node for each chapter so the editor critiques
    the refined text (pacing, character motivation, consistency, prose)
    before the cross-chapter consistency check runs. Reflection scores
    are persisted when the orchestrator has a DB session attached,
    enabling quality trend tracking.

    Flow: outline → world_setting → character →
          [per chapter: chapter_draft → chapter_refine → reflection] →
          consistency_check → final_polish → safety_review.

    `extra_inputs` is deep-merged into every task's inputs.
    """
    if chapter_count < 1:
        raise ValueError("chapter_count must be >= 1")

    extra_inputs = extra_inputs or {}
    specs: list[TaskSpec] = [
        TaskSpec(
            task_id="outline",
            kind=TaskKind.OUTLINE,
            inputs=_merge_inputs(
                {"premise": premise, "chapter_count": chapter_count}, extra_inputs
            ),
            expected_output_keys=("chapter_outline",),
        ),
        TaskSpec(
            task_id="world_setting",
            kind=TaskKind.WORLD_SETTING,
            inputs=_merge_inputs({"premise": premise}, extra_inputs),
            depends_on=("outline",),
            expected_output_keys=("world_entries",),
        ),
        TaskSpec(
            task_id="character",
            kind=TaskKind.CHARACTER,
            inputs=_merge_inputs(
                {"premise": premise, "count": character_count}, extra_inputs
            ),
            depends_on=("outline",),
            expected_output_keys=("characters",),
        ),
    ]

    chapter_refine_ids: list[str] = []
    for i in range(1, chapter_count + 1):
        draft_id = f"chapter_draft_{i}"
        refine_id = f"chapter_refine_{i}"
        reflection_id = f"reflection_{i}"
        chapter_refine_ids.append(refine_id)
        specs.append(TaskSpec(
            task_id=draft_id,
            kind=TaskKind.CHAPTER_DRAFT,
            inputs=_merge_inputs(
                {
                    "chapter_index": i,
                    "target_words": target_words_per_chapter,
                    "use_outline": True,
                },
                extra_inputs,
            ),
            depends_on=("outline", "world_setting", "character"),
            expected_output_keys=("content_text", "summary"),
        ))
        specs.append(TaskSpec(
            task_id=refine_id,
            kind=TaskKind.CHAPTER_REFINE,
            inputs=_merge_inputs({"chapter_index": i}, extra_inputs),
            depends_on=(draft_id,),
            expected_output_keys=("content_text",),
        ))
        specs.append(TaskSpec(
            task_id=reflection_id,
            kind=TaskKind.REFLECTION,
            inputs=_merge_inputs({"chapter_index": i}, extra_inputs),
            depends_on=(refine_id,),
            expected_output_keys=("issues", "score", "reflection"),
        ))

    specs.append(TaskSpec(
        task_id="consistency_check",
        kind=TaskKind.CONSISTENCY_CHECK,
        inputs=_merge_inputs(
            {"chapter_indices": list(range(1, chapter_count + 1))}, extra_inputs
        ),
        depends_on=tuple(chapter_refine_ids),
        expected_output_keys=("issues", "score"),
    ))
    specs.append(TaskSpec(
        task_id="final_polish",
        kind=TaskKind.FINAL_POLISH,
        inputs=_merge_inputs(
            {"chapter_indices": list(range(1, chapter_count + 1))}, extra_inputs
        ),
        depends_on=("consistency_check",),
        expected_output_keys=("content_text",),
    ))
    specs.append(TaskSpec(
        task_id="safety_review",
        kind=TaskKind.SAFETY_REVIEW,
        inputs=_merge_inputs(
            {"chapter_indices": list(range(1, chapter_count + 1))}, extra_inputs
        ),
        depends_on=("final_polish",),
        expected_output_keys=("passed", "issues"),
    ))

    return SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
