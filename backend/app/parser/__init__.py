"""Parser subpackage — natural-language → structured task spec.

Public API:
  - ParsedTaskSpec: structured fields extracted from NL input
  - TaskParser: rule-based + optional LLM-assisted parser

Design:
  - Rule-based parser is the default — deterministic, fast, no LLM cost.
    Extracts chapter_count, target_words_per_chapter, genre, tone,
    language via regex on common patterns ("5章", "5 chapters",
    "3000字", "3000 words", "侦探", "sci-fi").
  - LLM-assisted parser is optional — when rule-based confidence is
    low (< 0.6), an LLM can refine ambiguous fields. The LLM is asked
    to respond with strict JSON; failures fall back to rule-based.
  - The parser produces ParsedTaskSpec which can be passed directly
    to PlannerAgent.plan(**spec.to_planner_kwargs()).

Integration:
    from app.parser import TaskParser
    from app.planner import PlannerAgent

    spec = TaskParser().parse("写一本5章的侦探小说，每章3000字")
    dag = PlannerAgent().plan(**spec.to_planner_kwargs())
"""
from app.parser.parser import TaskParser  # noqa: F401
from app.parser.spec import ParsedTaskSpec  # noqa: F401
