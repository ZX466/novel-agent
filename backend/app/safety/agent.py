"""ContentSafetyAgent — handles TaskKind.SAFETY_REVIEW.

Two-phase safety check:
  1. Rule engine (deterministic, fast) — runs first.
     - If any BLOCK-severity rule matches → short-circuit: return
       passed=False with the issues listed. LLM is NOT invoked.
     - If only INFO/WARNING rules match → continue to LLM evaluation
       for nuanced judgment.
  2. Three-stage LLM evaluator (draft → refine → evaluate).
     - System prompt asks the LLM to judge safety considering context
       (e.g. "violence" in a thriller novel is acceptable, hate speech
       is not). The evaluator's score doubles as the safety score:
       high score = safe, low score = unsafe.
     - Threshold: score >= 0.8 → passed=True. Otherwise → passed=False.

Output (matching SAFETY_REVIEW's expected_output_keys):
  - passed: bool — whether the text passed safety review
  - issues: str — human-readable summary of issues found

The agent's `rule_engine` is injectable — tests pass a custom engine
to make rule matching deterministic.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.planner.spec import SubTask, SubTaskDAG, TaskKind
from app.safety.rules import RuleEngine, RuleResult

logger = logging.getLogger(__name__)


SAFETY_SYSTEM_PROMPT = (
    "You are a content safety reviewer for novels. Judge whether the "
    "text is safe to publish. Consider: explicit violence in context, "
    "sexual content, hate speech, self-harm, and PII exposure. "
    "Novel-appropriate violence (e.g. in a thriller) is acceptable; "
    "hate speech, real-person PII, and explicit sexual content are NOT. "
    "Output your verdict as a single sentence: 'SAFE' or 'UNSAFE: <reason>'."
)

SAFETY_EVAL_SYSTEM_PROMPT = (
    "You are a strict content safety evaluator. Score the text on a 0.0-1.0 "
    "scale where 1.0 means SAFE to publish and 0.0 means UNSAFE. "
    "Consider: hate speech, explicit sexual content, self-harm promotion, "
    "real-person PII, and graphic violence without narrative purpose. "
    "Novel-appropriate violence (e.g. in a thriller) is acceptable. "
    "Respond with ONLY a JSON object: "
    '{"score": <float>, "feedback": "<one short sentence on safety concerns>"}. '
    "No prose, no markdown fences, no extra characters."
)

SAFETY_REFINE_SYSTEM_PROMPT = (
    "You are a safety reviewer. Review the text again considering the "
    "evaluator feedback. Output only the verdict: 'SAFE' or 'UNSAFE: <reason>'."
)


class ContentSafetyAgent(BaseAgent):
    """Role: content safety reviewer.

    Owns the SAFETY_REVIEW task kind. Combines a deterministic rule
    engine (regex-based, fast) with a three-stage LLM evaluator for
    nuanced judgment on edge cases.

    The rule engine runs first; if any BLOCK-severity rule matches,
    the LLM is NOT called (saving latency + cost). Otherwise the
    three-stage pipeline runs with a safety-specific system prompt.
    """

    name = "safety"

    def __init__(
        self,
        *,
        rule_engine: RuleEngine | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # Default rule engine if none provided — tests inject a custom one.
        self.rule_engine: RuleEngine = rule_engine or RuleEngine()

    async def handle(self, subtask: SubTask, dag: SubTaskDAG) -> dict[str, Any]:
        """Run safety review on the dep task outputs.

        Reads dep results (final_polish's content_text, or chapter_refine_N's
        content_text as fallback) and runs the two-phase safety check.
        """
        if subtask.kind != TaskKind.SAFETY_REVIEW:
            raise ValueError(
                f"ContentSafetyAgent cannot handle kind={subtask.kind.value} "
                f"(task {subtask.task_id})"
            )
        return await self._handle_safety_review(subtask, dag)

    async def _handle_safety_review(
        self, subtask: SubTask, dag: SubTaskDAG
    ) -> dict[str, Any]:
        """Two-phase safety review: rule engine + LLM evaluator."""
        # Collect text to review from deps.
        deps = self._dep_results(subtask, dag)
        review_text = self._collect_review_text(deps)

        if not review_text.strip():
            # No text to review — pass by default.
            logger.info(
                "SafetyAgent: no text to review (task %s) — passing",
                subtask.task_id,
            )
            return {
                "passed": True,
                "issues": "No text to review.",
            }

        # Phase 1: rule engine (deterministic, fast).
        rule_results = self.rule_engine.check(review_text)
        matched = RuleEngine.matched_results(rule_results)
        summary = RuleEngine.summarize(rule_results)

        if RuleEngine.should_block(rule_results):
            # Hard-blocked by a rule — short-circuit, no LLM call.
            issues = self._format_rule_issues(matched, summary)
            logger.warning(
                "SafetyAgent: BLOCK by rule engine (task %s) — %s",
                subtask.task_id,
                summary,
            )
            return {"passed": False, "issues": issues}

        # Phase 2: LLM evaluator for nuanced judgment.
        # Only run when rule engine says OK or WARNING.
        rule_context = self._format_rule_context(matched)
        user_prompt = self._build_user_prompt(review_text, rule_context)
        result = await self._run_three_stage(
            SAFETY_SYSTEM_PROMPT,
            user_prompt,
            refine_system=SAFETY_REFINE_SYSTEM_PROMPT,
            eval_system=SAFETY_EVAL_SYSTEM_PROMPT,
        )

        # Interpret the LLM verdict.
        verdict = result.content.strip()
        passed = verdict.upper().startswith("SAFE") and not verdict.upper().startswith("UNSAFE")
        # Treat low evaluator score as unsafe — use the configurable threshold
        # (not the generic writing quality threshold) to ensure consistency
        # with the docstring's stated 0.8 cutoff.
        if result.score < self.score_threshold:
            passed = False

        issues = self._build_issues_text(verdict, matched, summary, result.score)
        logger.info(
            "SafetyAgent: %s (task %s) — verdict=%r score=%.2f rule_summary=%s",
            "PASS" if passed else "FAIL",
            subtask.task_id,
            verdict[:80],
            result.score,
            summary,
        )
        await self._persist_evaluation(
            stage="safety",
            score=result.score,
            feedback=result.feedback,
            source=subtask.task_id,
        )
        return {"passed": passed, "issues": issues}

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _collect_review_text(deps: dict[str, Any]) -> str:
        """Pull the text to review from dependency task results.

        Priority: final_polish.content_text > any *_refine.content_text
        > any dep's content_text > concatenated str of all dep values.
        """
        if not deps:
            return ""
        # Prefer final_polish output (the polished final version).
        for dep_id, result in deps.items():
            if dep_id == "final_polish" and isinstance(result, dict):
                text = result.get("content_text", "")
                if text:
                    return text
        # Fall back to any chapter_refine_N output.
        for dep_id, result in deps.items():
            if "refine" in dep_id and isinstance(result, dict):
                text = result.get("content_text", "")
                if text:
                    return text
        # Last resort: any dep's content_text field.
        for result in deps.values():
            if isinstance(result, dict):
                text = result.get("content_text", "")
                if text:
                    return text
        # Truly last resort: concatenate all str values.
        parts: list[str] = []
        for result in deps.values():
            if isinstance(result, dict):
                for v in result.values():
                    if isinstance(v, str):
                        parts.append(v)
            elif isinstance(result, str):
                parts.append(result)
        return "\n\n".join(parts)

    @staticmethod
    def _format_rule_issues(
        matched: list[RuleResult], summary: dict
    ) -> str:
        """Build the issues string when the rule engine blocked.

        Lists each matched rule with its category and a snippet of evidence.
        """
        lines = [
            "BLOCKED by safety rules:",
            f"  matched_count: {summary['matched_count']}",
            f"  max_severity: {summary['max_severity']}",
            "",
        ]
        for r in matched:
            lines.append(
                f"  - [{r.severity.name}] {r.rule_name} ({r.category}): "
                f"evidence={r.evidence!r}"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_rule_context(matched: list[RuleResult]) -> str:
        """Inject matched-rule context into the LLM prompt.

        The LLM uses this to make a nuanced judgment (e.g. "the rule
        flagged 'violence' but in a thriller context that's fine").
        """
        if not matched:
            return ""
        lines = ["Rule engine pre-check found these flags:"]
        for r in matched:
            lines.append(
                f"  - [{r.severity.name}] {r.rule_name} ({r.category})"
            )
        lines.append(
            "Consider these in your verdict. WARNING/INFO rules do not "
            "automatically block — use your judgment."
        )
        return "\n".join(lines)

    def _build_user_prompt(self, review_text: str, rule_context: str) -> str:
        """Build the LLM user prompt: rule context + text to review."""
        # Truncate very long text to keep the prompt within token limits.
        # 8000 chars ~ 2000 tokens — safe for a single LLM call.
        max_chars = 8000
        if len(review_text) > max_chars:
            review_text = review_text[:max_chars] + "\n...[truncated]"
        prompt = ""
        if rule_context:
            prompt += rule_context + "\n\n"
        prompt += "Text to review:\n" + review_text + "\n\n"
        prompt += "Output your verdict: 'SAFE' or 'UNSAFE: <reason>'."
        return prompt

    @staticmethod
    def _build_issues_text(
        verdict: str,
        matched: list[RuleResult],
        summary: dict,
        score: float,
    ) -> str:
        """Build the issues string for the LLM-evaluated path.

        Includes the LLM verdict, score, and any rule-engine flags
        (for traceability).
        """
        lines = [f"LLM verdict: {verdict}", f"Safety score: {score:.2f}"]
        if matched:
            lines.append("")
            lines.append("Rule engine flags:")
            for r in matched:
                lines.append(
                    f"  - [{r.severity.name}] {r.rule_name} ({r.category})"
                )
        lines.append("")
        lines.append(f"Summary: {summary}")
        return "\n".join(lines)
