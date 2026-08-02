"""Base class for role-specialized agents.

Each agent wraps the three-stage pipeline (draft → refine → evaluate)
with role-specific system prompts and kind-specific prompt builders.
Subclasses implement `handle(subtask, dag)` which dispatches to
kind-specific methods based on `subtask.kind`.

Agents are constructed with an optional BYOK `provider_config` which
flows into all three LLM stages (draft/refine/evaluate) independently
— matching the existing LangGraph pipeline's behavior where each stage
can use a different provider.

The three-stage runner uses `app.llm.clients.draft/refine/evaluate`
directly — same wrappers the LangGraph pipeline uses — so the LLM call
convention is identical between the pipeline and the agents.

Handler protocol matches `app.planner.orchestrator.Handler`:
    async def handle(subtask: SubTask, dag: SubTaskDAG) -> dict[str, Any]

The returned dict MUST include the subtask's `expected_output_keys`.
The orchestrator validates this contract and marks the task FAILED if
keys are missing.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import draft as llm_draft
from app.llm import evaluate as llm_evaluate
from app.llm import refine as llm_refine
from app.planner.spec import SubTask, SubTaskDAG
from app.schemas.chat import ProviderConfig, StageConfig

logger = logging.getLogger(__name__)


# Shared evaluator system prompt — identical to app.pipeline.nodes so
# agent-based and pipeline-based runs produce comparable scores.
EVAL_SYSTEM_PROMPT = (
    "You are a strict writing evaluator. Score the text on a 0.0-1.0 scale "
    "where 1.0 means publish-ready. Respond with ONLY a JSON object: "
    '{"score": <float>, "feedback": "<one short sentence on what to improve>"}. '
    "No prose, no markdown fences, no extra characters. "
    "Respond with ONLY the JSON object."
)


@dataclass
class AgentResult:
    """Outcome of a three-stage agent run.

    `content` is the final refined text after the draft→refine→evaluate loop.
    `score` is the last evaluator score. When a ReviewMatrixRunner is
    attached, `score` is the matrix's aggregate_score and `review_matrix`
    holds the full per-dimension breakdown. `iterations` is the number of
    refine passes completed (0 if draft already met threshold — but
    with the current implementation we always run at least one refine pass).
    """

    content: str
    score: float = 0.0
    feedback: str = ""
    iterations: int = 0
    raw_eval: str = ""
    review_matrix: Any = None  # ReviewMatrix | None (typed as Any to avoid import cycle)


def _parse_eval(raw: str) -> tuple[float, str]:
    """Parse the evaluator's JSON response. Falls back to regex on failure.

    Duplicated from app.pipeline.nodes._parse_eval to keep the agents
    module decoupled from the LangGraph pipeline. If the parsing logic
    needs to change, update both copies (or extract to a shared util).

    The regex fallback anchors to the 'score' keyword before the first
    number: models that echo the prompt's '0.0-1.0 scale' before the real
    score would otherwise report 0.0 and force needless refine loops.
    Score is clamped to [0.0, 1.0] to prevent out-of-range values.
    """
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE
    ).strip()

    # 1. Clean JSON.
    try:
        data = json.loads(cleaned)
        score = max(0.0, min(1.0, float(data["score"])))
        return score, str(data.get("feedback", ""))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        pass

    # 2. JSON object embedded in prose.
    obj_match = re.search(r"\{[^{}]*\}", cleaned)
    if obj_match:
        try:
            data = json.loads(obj_match.group(0))
            if "score" in data:
                score = max(0.0, min(1.0, float(data["score"])))
                return score, str(data.get("feedback", ""))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # 3. Number anchored to the 'score' keyword.
    kw_match = re.search(r"score\b[^\d]*([0-9]*\.?[0-9]+)", cleaned, re.IGNORECASE)
    if kw_match:
        score = max(0.0, min(1.0, float(kw_match.group(1))))
        return score, cleaned[:200]

    # 4. Last-resort: first number anywhere.
    score_match = re.search(r"([0-9]*\.?[0-9]+)", cleaned)
    if score_match:
        score = max(0.0, min(1.0, float(score_match.group(1))))
        return score, cleaned[:200]

    return 0.0, cleaned[:200]


class BaseAgent:
    """Abstract base for role-specialized agents.

    Subclasses MUST set `name` and implement `handle(subtask, dag)`.

    The `provider_config` (BYOK) is optional — when None, agents fall
    back to the .env defaults via app.llm.clients. When provided, each
    stage (draft/refine/evaluate) uses its own StageConfig so users can
    route the three stages to different providers.

    `session` is currently unused (agents don't access the DB directly)
    but is accepted for future tool-enabled agents that need DB access
    via ToolContext. Keeping it in the constructor signature means the
    factory can pass it uniformly.
    """

    name: str = "base"

    def __init__(
        self,
        *,
        session: AsyncSession | None = None,
        provider_config: ProviderConfig | None = None,
        max_iters: int = 3,
        score_threshold: float = 0.8,
        evaluator: Any = None,  # ReviewMatrixRunner | None
        novel_id: int = 0,
    ) -> None:
        """Construct an agent.

        Args:
            session: optional AsyncSession for future tool-enabled agents.
            provider_config: optional BYOK credentials — flows into all
                three LLM stages independently.
            max_iters: max number of refine passes per three-stage run.
            score_threshold: early-exit threshold for the evaluator
                score. With an evaluator attached, this is compared
                against the matrix's aggregate_score.
            evaluator: optional ReviewMatrixRunner. When provided, the
                three-stage loop calls evaluator.evaluate() instead of
                the single llm_evaluate. The aggregate_score drives
                early-exit; aggregate_feedback drives the next refine.
            novel_id: novel scope for persisted evaluations. Defaults to
                0 (the v1 single-novel convention matching the Chapter
                model). Used only when `session` is provided.
        """
        self.session = session
        self.provider_config = provider_config
        self.max_iters = max_iters
        self.score_threshold = score_threshold
        self.evaluator = evaluator
        self.novel_id = novel_id

    async def handle(self, subtask: SubTask, dag: SubTaskDAG) -> dict[str, Any]:
        raise NotImplementedError(
            f"{self.name}.handle() not implemented"
        )

    # --- shared helpers ----------------------------------------------------

    def _pick_stage(self, stage: str) -> StageConfig | None:
        """Read a stage config from provider_config. None when no BYOK."""
        if self.provider_config is None:
            return None
        return getattr(self.provider_config, stage, None)

    def _dep_results(self, subtask: SubTask, dag: SubTaskDAG) -> dict[str, Any]:
        """Collect all dependency results into {task_id: result_dict}.

        Tasks whose dependencies haven't run yet (result is None) are
        omitted — the caller should not assume every dep is present.
        """
        results: dict[str, Any] = {}
        for dep_id in subtask.depends_on:
            dep_sub = dag.tasks.get(dep_id)
            if dep_sub is not None and dep_sub.result is not None:
                results[dep_id] = dep_sub.result
        return results

    def _format_deps(self, deps: dict[str, Any]) -> str:
        """Format dependency results as a human-readable context block.

        Used to inject prior-task outputs into the user prompt so the
        LLM has the full context (outline, world setting, characters, etc.).
        """
        if not deps:
            return ""
        lines: list[str] = ["Context from prior tasks:"]
        for tid, result in deps.items():
            lines.append(f"\n--- {tid} ---")
            if isinstance(result, dict):
                for k, v in result.items():
                    val_str = str(v)
                    if len(val_str) > 500:
                        val_str = val_str[:500] + "..."
                    lines.append(f"{k}: {val_str}")
            else:
                lines.append(str(result))
        return "\n".join(lines)

    async def _run_three_stage(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        refine_system: str = (
            "You are a meticulous editor. Refine the text per the feedback. "
            "Output only the new text, no preamble."
        ),
        eval_system: str | None = None,
        max_iters: int | None = None,
        score_threshold: float | None = None,
    ) -> AgentResult:
        """Run the draft → refine → evaluate loop with role-specific prompts.

        Each phase uses its own BYOK stage config (draft/refine/evaluate)
        from `self.provider_config`. When None, falls back to .env defaults.

        The loop runs at most `max_iters` refine passes. Exits early when
        the evaluator score >= `score_threshold`.
        """
        threshold = (
            score_threshold if score_threshold is not None else self.score_threshold
        )
        iters = max_iters if max_iters is not None else self.max_iters

        draft_cfg = self._pick_stage("draft")
        refine_cfg = self._pick_stage("refine")
        eval_cfg = self._pick_stage("evaluate")

        # Draft phase
        draft_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        draft_resp = await llm_draft(draft_messages, stage_config=draft_cfg)
        current = draft_resp.choices[0].message.content or ""

        # Refine → evaluate loop
        feedback = ""
        score = 0.0
        raw_eval = ""
        review_matrix = None
        for i in range(iters):
            refine_user = f"Current version:\n{current}\n\n"
            if feedback:
                refine_user += f"Evaluator feedback:\n{feedback}\n\n"
            refine_user += "Produce an improved version. Output only the new text."
            refine_messages = [
                {"role": "system", "content": refine_system},
                {"role": "user", "content": refine_user},
            ]
            refine_resp = await llm_refine(refine_messages, stage_config=refine_cfg)
            current = refine_resp.choices[0].message.content or ""

            if self.evaluator is not None:
                # Multi-dimensional evaluation: run all dimensions in
                # parallel, aggregate into a single score. The aggregate
                # feedback (per-dimension notes) is fed to the next refine.
                review_matrix = await self.evaluator.evaluate(
                    current,
                    stage_config=eval_cfg,
                    threshold=threshold,
                )
                score = review_matrix.aggregate_score
                feedback = review_matrix.aggregate_feedback
                raw_eval = ""  # no single raw_eval in matrix mode
                logger.debug(
                    "%s three_stage matrix iter=%d score=%.2f passed=%s",
                    self.name, i + 1, score, review_matrix.passed,
                )
                if score >= threshold:
                    return AgentResult(
                        content=current,
                        score=score,
                        feedback=feedback,
                        iterations=i + 1,
                        raw_eval=raw_eval,
                        review_matrix=review_matrix,
                    )
                continue

            # Single-evaluator path (original)
            eval_messages = [
                {"role": "system", "content": eval_system or EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": current},
            ]
            eval_resp = await llm_evaluate(eval_messages, stage_config=eval_cfg)
            raw_eval = eval_resp.choices[0].message.content or ""
            score, feedback = _parse_eval(raw_eval)
            logger.debug(
                "%s three_stage iter=%d score=%.2f", self.name, i + 1, score
            )
            if score >= threshold:
                return AgentResult(
                    content=current,
                    score=score,
                    feedback=feedback,
                    iterations=i + 1,
                    raw_eval=raw_eval,
                )

        return AgentResult(
            content=current,
            score=score,
            feedback=feedback,
            iterations=iters,
            raw_eval=raw_eval,
            review_matrix=review_matrix,
        )

    async def _persist_evaluation(
        self,
        *,
        stage: str,
        score: float,
        feedback: str,
        chapter_index: int | None = None,
        source: str = "",
    ) -> None:
        """Best-effort persistence of an evaluation record.

        No-op when no DB session is attached (e.g. agents run without a
        session in unit tests). Failures are logged and swallowed so a
        persistence problem never fails a writing task — the evaluation
        still returns to the DAG; only the durable trend record is lost.

        `chapter_index` is resolved to a `chapter_id` via the chapter
        service when both a session and a chapter_index are available;
        otherwise chapter_id is left NULL (cross-chapter evaluations).
        """
        if self.session is None:
            return
        try:
            from app.services.chapter import get_chapter_by_index
            from app.services.evaluation import create_evaluation

            chapter_id: int | None = None
            if chapter_index is not None:
                ch = await get_chapter_by_index(
                    self.session, self.novel_id, chapter_index
                )
                chapter_id = ch.id if ch is not None else None
            await create_evaluation(
                self.session,
                novel_id=self.novel_id,
                chapter_id=chapter_id,
                stage=stage,
                score=score,
                feedback=feedback,
                source=source,
            )
        except Exception:
            # Persistence is best-effort: never fail the writing task.
            logger.exception(
                "%s: failed to persist evaluation stage=%s", self.name, stage
            )
