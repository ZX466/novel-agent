"""CharacterAgent — handles character profile generation.

Owns the CHARACTER task kind: generates a list of character profiles
based on the premise and the chapter outline (when available as a
dependency). Each profile includes name, role, description, and key
traits — the output is text that the editor agent can incorporate
when writing chapters.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.planner.spec import SubTask, SubTaskDAG, TaskKind


class CharacterAgent(BaseAgent):
    """Role: character designer.

    Generates character profiles that downstream agents (EditorAgent)
    reference when writing chapters. Does NOT write chapter prose.
    """

    name = "character"

    async def handle(self, subtask: SubTask, dag: SubTaskDAG) -> dict[str, Any]:
        if subtask.kind != TaskKind.CHARACTER:
            raise ValueError(
                f"CharacterAgent cannot handle kind={subtask.kind.value} "
                f"(task {subtask.task_id})"
            )
        return await self._handle_character(subtask, dag)

    async def _handle_character(
        self, subtask: SubTask, dag: SubTaskDAG
    ) -> dict[str, Any]:
        premise = subtask.spec.inputs.get("premise", "")
        count = subtask.spec.inputs.get("count", 2)
        deps = self._dep_results(subtask, dag)
        context = self._format_deps(deps)

        system = (
            "You are a character designer for novels. Generate character "
            "profiles based on the premise. For each character output: "
            "name, role (protagonist/antagonist/supporting/NPC), a 2-3 "
            "sentence description, and 3-5 key personality traits. "
            "Output as a numbered list. Output only the profiles, no preamble."
        )
        user = f"Premise: {premise}\nNumber of characters: {count}\n\n"
        if context:
            user += f"{context}\n\n"
        user += "Generate the character profiles."
        result = await self._run_three_stage(system, user)
        return {"characters": result.content}
