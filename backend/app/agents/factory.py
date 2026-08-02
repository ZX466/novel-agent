"""Factory for the novel-writing orchestrator.

Wires the role-specialized agents (PlotterAgent, CharacterAgent,
EditorAgent, ContentSafetyAgent) into a single Orchestrator with all
TaskKind handlers registered.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.character import CharacterAgent
from app.agents.editor import EditorAgent
from app.agents.plotter import PlotterAgent
from app.planner.orchestrator import Orchestrator
from app.planner.spec import TaskKind
from app.schemas.chat import ProviderConfig

# NOTE: ContentSafetyAgent / RuleEngine are imported lazily inside
# make_novel_orchestrator() to avoid a circular import at module load time.
# The cycle is: app.safety.__init__ → app.safety.agent → app.agents (base)
# → app.agents.__init__ → app.agents.factory → app.safety (closes).
# Moving the import to call-time ensures app.safety is fully initialized
# before we pull ContentSafetyAgent from it.


def make_novel_orchestrator(
    *,
    session: AsyncSession | None = None,
    provider_config: ProviderConfig | None = None,
    max_iters: int = 3,
    score_threshold: float = 0.8,
    rule_engine: RuleEngine | None = None,
    evaluator: Any = None,  # ReviewMatrixRunner | None
    novel_id: int = 0,
) -> Orchestrator:
    """Build an Orchestrator with all role-specialized agents registered.

    Each agent shares the same session (for future tool calls) and
    provider_config (BYOK credentials flow to all three LLM stages).
    The max_iters and score_threshold apply to each agent's three-stage
    pipeline independently.

    ContentSafetyAgent uses both the rule engine (deterministic, fast)
    and the three-stage LLM pipeline for nuanced judgment. A custom
    rule_engine can be injected — defaults to `RuleEngine()` with the
    built-in rule set.

    `evaluator` (optional ReviewMatrixRunner) replaces the single
    llm_evaluate call in each agent's three-stage loop with a
    multi-dimensional review matrix. When None, agents use the original
    single-evaluator path. The ContentSafetyAgent ignores `evaluator`
    because it has its own safety-specific evaluation prompt.
    """
    # Lazy import — see module-level note about circular import.
    from app.safety import ContentSafetyAgent, RuleEngine

    shared_kwargs: dict[str, Any] = {
        "session": session,
        "provider_config": provider_config,
        "max_iters": max_iters,
        "score_threshold": score_threshold,
        "evaluator": evaluator,
        "novel_id": novel_id,
    }
    plotter = PlotterAgent(**shared_kwargs)
    character = CharacterAgent(**shared_kwargs)
    editor = EditorAgent(**shared_kwargs)
    # ContentSafetyAgent has its own safety-specific evaluation prompt,
    # so it ignores the multi-dimensional evaluator. We pass only the
    # non-evaluator kwargs to keep its evaluation path unchanged.
    safety_kwargs = {k: v for k, v in shared_kwargs.items() if k != "evaluator"}
    safety = ContentSafetyAgent(rule_engine=rule_engine, **safety_kwargs)

    orch = Orchestrator()
    # PlotterAgent handles structure / worldbuilding / consistency
    orch.register(TaskKind.OUTLINE, plotter.handle)
    orch.register(TaskKind.WORLD_SETTING, plotter.handle)
    orch.register(TaskKind.CONSISTENCY_CHECK, plotter.handle)
    # CharacterAgent handles character design
    orch.register(TaskKind.CHARACTER, character.handle)
    # EditorAgent handles prose
    orch.register(TaskKind.CHAPTER_DRAFT, editor.handle)
    orch.register(TaskKind.CHAPTER_REFINE, editor.handle)
    orch.register(TaskKind.FINAL_POLISH, editor.handle)
    orch.register(TaskKind.REFLECTION, editor.handle)
    # ContentSafetyAgent handles safety review
    orch.register(TaskKind.SAFETY_REVIEW, safety.handle)
    return orch
