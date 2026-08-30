"""Safety subpackage — deterministic rule engine.

Public API:
  - Severity: rule severity enum (INFO / WARNING / BLOCK)
  - Rule: a named regex-based safety rule
  - RuleResult: outcome of running a Rule against text
  - RuleEngine: registry + check() runner
  - make_default_rules(): built-in rule set (violence, self-harm, sexual,
    hate, PII, profanity)

Design:
  - Rule engine is deterministic and fast (regex-based) — runs in the
    pipeline's safety_check node before/alongside the LLM stages.
  - All rules are configurable — production deployments can extend
    or replace the default set via `RuleEngine.register()`.
"""
from app.safety.rules import (  # noqa: F401
    Rule,
    RuleEngine,
    RuleResult,
    Severity,
    make_default_rules,
)
