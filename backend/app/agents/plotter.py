"""PlotterAgent — handles plotting / worldbuilding / consistency tasks.

Dispatches based on TaskKind:
  - OUTLINE: generates a chapter outline from the premise
  - WORLD_SETTING: builds world-building entries from the premise
  - CONSISTENCY_CHECK: reviews chapter texts for cross-chapter inconsistencies

All three run the three-stage pipeline (draft → refine → evaluate) with
role-specific system prompts. The output is wrapped in the expected_output_keys
defined by the planner templates.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.planner.spec import SubTask, SubTaskDAG, TaskKind


class PlotterAgent(BaseAgent):
    """Role: plotter / worldbuilder / consistency checker.

    Owns tasks that shape the story structure and verify its coherence.
    Does NOT write chapter prose — that's EditorAgent's job.
    """

    name = "plotter"

    async def handle(self, subtask: SubTask, dag: SubTaskDAG) -> dict[str, Any]:
        """Dispatch to kind-specific handler."""
        if subtask.kind == TaskKind.OUTLINE:
            return await self._handle_outline(subtask, dag)
        if subtask.kind == TaskKind.WORLD_SETTING:
            return await self._handle_world_setting(subtask, dag)
        if subtask.kind == TaskKind.CONSISTENCY_CHECK:
            return await self._handle_consistency_check(subtask, dag)
        raise ValueError(
            f"PlotterAgent cannot handle kind={subtask.kind.value} "
            f"(task {subtask.task_id})"
        )

    # --- OUTLINE -----------------------------------------------------------

    async def _handle_outline(
        self, subtask: SubTask, dag: SubTaskDAG
    ) -> dict[str, Any]:
        premise = subtask.spec.inputs.get("premise", "")
        chapter_count = subtask.spec.inputs.get("chapter_count", 1)

        system = (
            "You are a novel plotter. Generate a chapter outline based on "
            "the premise. Output the outline as a numbered list of chapters, "
            "each with a one-sentence summary of what happens. "
            "Output only the outline, no preamble."
        )
        user = (
            f"Premise: {premise}\n\n"
            f"Number of chapters: {chapter_count}\n\n"
            "Generate the chapter outline."
        )
        result = await self._run_three_stage(system, user)
        return {"chapter_outline": result.content}

    # --- WORLD_SETTING ------------------------------------------------------

    async def _handle_world_setting(
        self, subtask: SubTask, dag: SubTaskDAG
    ) -> dict[str, Any]:
        premise = subtask.spec.inputs.get("premise", "")
        deps = self._dep_results(subtask, dag)
        context = self._format_deps(deps)

        system = (
            "You are a worldbuilder. Generate world-setting entries based "
            "on the premise. Cover: geography, culture, magic/technology "
            "system, key factions, and any rules the reader needs to track. "
            "Output as a bulleted list. Output only the entries, no preamble."
        )
        user = f"Premise: {premise}\n\n"
        if context:
            user += f"{context}\n\n"
        user += "Generate the world-setting entries."
        result = await self._run_three_stage(system, user)
        return {"world_entries": result.content}

    # --- CONSISTENCY_CHECK --------------------------------------------------

    async def _handle_consistency_check(
        self, subtask: SubTask, dag: SubTaskDAG
    ) -> dict[str, Any]:
        """Check cross-chapter consistency.

        The evaluator's score doubles as the consistency score — a low
        score means the chapters are inconsistent. The issues are the
        evaluator's feedback combined with the LLM's analysis.
        """
        deps = self._dep_results(subtask, dag)
        context = self._format_deps(deps)

        system = (
            "You are a consistency checker for a novel. Review the chapter "
            "texts for inconsistencies: character names, timelines, world "
            "rules, plot threads. List each issue found. "
            "Output only the issues list, no preamble. If no issues, "
            "output 'No inconsistencies found.'"
        )
        user = ""
        if context:
            user += f"{context}\n\n"
        user += "Check the chapters for consistency issues."
        result = await self._run_three_stage(system, user)
        await self._persist_evaluation(
            stage="consistency_check",
            score=result.score,
            feedback=result.feedback,
            source=subtask.task_id,
        )
        return {
            "issues": result.content,
            "score": result.score,
        }
