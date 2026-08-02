"""Safety subpackage — rule engine + ContentSafetyAgent.

Public API:
  - Severity: rule severity enum (INFO / WARNING / BLOCK)
  - Rule: a named regex-based safety rule
  - RuleResult: outcome of running a Rule against text
  - RuleEngine: registry + check() runner
  - make_default_rules(): built-in rule set (violence, self-harm, sexual,
    hate, PII, profanity)
  - ContentSafetyAgent: handles TaskKind.SAFETY_REVIEW

Design:
  - Rule engine is deterministic and fast (regex-based) — runs first.
  - If any BLOCK-severity rule matches, the agent short-circuits and
    returns passed=False without invoking the LLM.
  - Otherwise, the three-stage pipeline (draft → refine → evaluate)
    runs with a safety-specific system prompt for nuanced judgment
    on edge cases the regex rules don't cover.
  - All rules are configurable — production deployments can extend
    or replace the default set via `RuleEngine.register()`.
"""
from app.safety.agent import (  # noqa: F401
    ContentSafetyAgent,
)
from app.safety.rules import (  # noqa: F401
    Rule,
    RuleEngine,
    RuleResult,
    Severity,
    make_default_rules,
)
