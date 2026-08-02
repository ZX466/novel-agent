"""EditorAgent — handles chapter writing / refinement / final polish.

Dispatches based on TaskKind:
  - CHAPTER_DRAFT: writes the first draft of a chapter
  - CHAPTER_REFINE: refines an existing draft based on feedback
  - FINAL_POLISH: applies a final style/voice consistency pass

All three run the three-stage pipeline (draft → refine → evaluate) with
role-specific system prompts. The output is wrapped in the expected_output_keys
defined by the planner templates.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.planner.spec import SubTask, SubTaskDAG, TaskKind


class EditorAgent(BaseAgent):
    """Role: chapter writer / editor.

    Owns the prose-producing tasks. Reads dependency results (outline,
    world setting, characters, prior chapter drafts) and incorporates
    them into the user prompt so the chapter is consistent with the
    established story.
    """

    name = "editor"

    async def handle(self, subtask: SubTask, dag: SubTaskDAG) -> dict[str, Any]:
        if subtask.kind == TaskKind.CHAPTER_DRAFT:
            return await self._handle_chapter_draft(subtask, dag)
        if subtask.kind == TaskKind.CHAPTER_REFINE:
            return await self._handle_chapter_refine(subtask, dag)
        if subtask.kind == TaskKind.FINAL_POLISH:
            return await self._handle_final_polish(subtask, dag)
        if subtask.kind == TaskKind.REFLECTION:
            return await self._handle_reflection(subtask, dag)
        raise ValueError(
            f"EditorAgent cannot handle kind={subtask.kind.value} "
            f"(task {subtask.task_id})"
        )

    # --- CHAPTER_DRAFT ------------------------------------------------------

    async def _handle_chapter_draft(
        self, subtask: SubTask, dag: SubTaskDAG
    ) -> dict[str, Any]:
        chapter_index = subtask.spec.inputs.get("chapter_index", 1)
        target_words = subtask.spec.inputs.get("target_words", 3000)
        deps = self._dep_results(subtask, dag)
        context = self._format_deps(deps)

        system = (
            "You are a novel chapter writer. Write a complete chapter based "
            "on the outline, world setting, and characters provided. "
            "Match the tone and style of a published novel. "
            "Output only the chapter text, no preamble, no chapter heading."
        )
        user = (
            f"Chapter {chapter_index}\n"
            f"Target word count: ~{target_words} words\n\n"
        )
        if context:
            user += f"{context}\n\n"
        user += "Write the chapter."
        result = await self._run_three_stage(system, user)
        await self._persist_evaluation(
            stage="draft",
            score=result.score,
            feedback=result.feedback,
            chapter_index=chapter_index,
            source=subtask.task_id,
        )
        return {
            "content_text": result.content,
            "summary": self._auto_summary(result.content),
        }

    # --- CHAPTER_REFINE -----------------------------------------------------

    async def _handle_chapter_refine(
        self, subtask: SubTask, dag: SubTaskDAG
    ) -> dict[str, Any]:
        """Refine an existing chapter draft.

        Reads the prior chapter_draft_N task's `content_text` from the
        DAG and asks the LLM to refine it. The three-stage pipeline's
        own evaluator provides feedback across iterations.
        """
        deps = self._dep_results(subtask, dag)
        chapter_index = subtask.spec.inputs.get("chapter_index")
        # Find the prior draft text — usually chapter_draft_N.
        draft_text = ""
        for dep_result in deps.values():
            if isinstance(dep_result, dict) and dep_result.get("content_text"):
                draft_text = dep_result["content_text"]
                break

        system = (
            "You are a chapter editor. Refine the chapter draft for better "
            "prose, pacing, and emotional impact. Keep the plot and "
            "characters intact. Output only the refined chapter text, "
            "no preamble."
        )
        user = (
            f"Original chapter draft:\n{draft_text}\n\n"
            "Produce a refined version."
        )
        result = await self._run_three_stage(system, user)
        await self._persist_evaluation(
            stage="refine",
            score=result.score,
            feedback=result.feedback,
            chapter_index=chapter_index if isinstance(chapter_index, int) else None,
            source=subtask.task_id,
        )
        return {"content_text": result.content}

    # --- FINAL_POLISH -------------------------------------------------------

    async def _handle_final_polish(
        self, subtask: SubTask, dag: SubTaskDAG
    ) -> dict[str, Any]:
        """Final style/voice consistency pass across refined chapters."""
        deps = self._dep_results(subtask, dag)
        context = self._format_deps(deps)

        system = (
            "You are a final polisher for a novel. Apply a final pass to "
            "ensure consistent voice, tone, and style across all chapters. "
            "Fix any remaining awkward phrasing. Output only the polished "
            "text, no preamble."
        )
        user = ""
        if context:
            user += f"{context}\n\n"
        user += "Produce the final polished version."
        result = await self._run_three_stage(system, user)
        await self._persist_evaluation(
            stage="final_polish",
            score=result.score,
            feedback=result.feedback,
            source=subtask.task_id,
        )
        return {"content_text": result.content}

    # --- REFLECTION ---------------------------------------------------------

    async def _handle_reflection(
        self, subtask: SubTask, dag: SubTaskDAG
    ) -> dict[str, Any]:
        """Self-reflection over a refined / polished chapter.

        Reads the dependency's chapter text (typically chapter_refine_N or
        final_polish) and asks the editor to critique it: concrete issues
        across pacing, character motivation, consistency, and prose, plus
        an overall quality assessment. The three-stage evaluator's score
        is surfaced as the reflection score (mirrors how
        CONSISTENCY_CHECK reuses the evaluator score).

        Output contract: {issues, score, reflection}.
          - issues:     the critique text (actionable problems found)
          - score:      evaluator score in [0.0, 1.0]
          - reflection: a one-line takeaway for downstream tasks
        """
        chapter_index = subtask.spec.inputs.get("chapter_index")
        deps = self._dep_results(subtask, dag)
        chapter_text = ""
        for dep_result in deps.values():
            if isinstance(dep_result, dict) and dep_result.get("content_text"):
                chapter_text = dep_result["content_text"]
                break

        system = (
            "You are a reflective editor reviewing a finished chapter. "
            "Identify concrete, prioritized issues: pacing, character "
            "motivation, world/plot consistency, and prose quality. Be "
            "specific and honest — do not invent praise. End with a single "
            "line: 'Reflection: <one-sentence takeaway>'. Output only the "
            "critique, no preamble."
        )
        user = (
            f"Chapter {chapter_index if chapter_index is not None else '?'}:\n"
            f"{chapter_text}\n\n"
            "Critique this chapter."
        )
        result = await self._run_three_stage(system, user)
        reflection = self._extract_takeaway(result.content)
        await self._persist_evaluation(
            stage="reflection",
            score=result.score,
            feedback=result.feedback,
            chapter_index=chapter_index if isinstance(chapter_index, int) else None,
            source=subtask.task_id,
        )
        return {
            "issues": result.content,
            "score": result.score,
            "reflection": reflection,
        }

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _extract_takeaway(text: str) -> str:
        """Pull the 'Reflection: ...' line from the critique, if present."""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("reflection:"):
                return stripped[len("reflection:"):].strip()
        return ""

    @staticmethod
    def _auto_summary(text: str, max_chars: int = 200) -> str:
        """Build a short summary from the chapter text.

        Uses the first sentence or first `max_chars` characters,
        whichever is shorter. This is a placeholder — a future
        enhancement can use a dedicated LLM call to summarize.
        """
        if not text:
            return ""
        # Take the first sentence (up to the first period followed by space/newline).
        import re

        first_sentence = re.split(r"[.。!！?？]\s", text, maxsplit=1)[0].strip()
        if first_sentence and len(first_sentence) < max_chars:
            return first_sentence + "."
        return text[:max_chars].strip() + "..."
