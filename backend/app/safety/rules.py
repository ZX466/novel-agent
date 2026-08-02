"""Rule engine — deterministic safety checks via regex patterns.

Runs before the LLM evaluator for two reasons:
  1. Speed: regex is O(text length) while an LLM call is 100-1000ms+
  2. Determinism: a known-bad pattern (e.g. an SSN) should always block,
     regardless of how the LLM reasons about context.

Each Rule has a Severity:
  - INFO:      log only, doesn't affect pass/fail
  - WARNING:   flagged but text still passes
  - BLOCK:     hard-block — agent returns passed=False immediately

The default rule set is intentionally conservative — false positives are
preferable to false negatives for safety. Deployments can override any
rule via `RuleEngine.register()` (same name replaces) or build a fresh
engine with `RuleEngine(rules=[])`.

Categories (used for reporting / aggregation):
  - violence:      explicit violence / gore
  - self_harm:     suicide / self-injury references
  - sexual:        explicit sexual content
  - hate:          hate speech slurs
  - pii:           emails / phone numbers / ID cards (redact before logging)
  - profanity:      swear words (severity=INFO by default)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable


class Severity(IntEnum):
    """Rule severity. Higher value = more serious.

    IntEnum so `max(results)` picks the highest severity directly.
    """

    INFO = 1
    WARNING = 2
    BLOCK = 3


@dataclass(frozen=True)
class Rule:
    """A named regex-based safety rule.

    `pattern` is a compiled regex (or string — engine will compile it).
    `category` groups rules for reporting (e.g. "violence", "pii").
    `severity` determines whether a match blocks / warns / logs.
    `description` is human-readable — shown in API responses and logs.
    """

    name: str
    pattern: re.Pattern
    severity: Severity
    category: str
    description: str = ""

    @classmethod
    def from_string(
        cls,
        *,
        name: str,
        pattern: str,
        severity: Severity,
        category: str,
        description: str = "",
        flags: int = 0,
    ) -> "Rule":
        """Build a Rule from a string pattern (auto-compiled)."""
        return cls(
            name=name,
            pattern=re.compile(pattern, flags),
            severity=severity,
            category=category,
            description=description,
        )


@dataclass(frozen=True)
class RuleResult:
    """Outcome of running a single Rule against text.

    `matched` is True when the regex found at least one match.
    `evidence` is the first matched substring (truncated) — for logging.
    `matches` is the full list of matched strings (capped at 10 to avoid
    log bloat on pathological inputs).
    """

    rule_name: str
    category: str
    severity: Severity
    matched: bool
    evidence: str = ""
    matches: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Default rule set — intentionally conservative
# ---------------------------------------------------------------------------

# Patterns are deliberately simple — they catch obvious cases. Real
# deployments should replace these with curated, language-aware rules.
# False positives on PII / profanity are acceptable; violence / self-harm
# / sexual / hate should err on the side of blocking.

_DEFAULT_RULE_DEFS: list[dict] = [
    # --- BLOCK-level rules (hard-block, no LLM needed) -------------------
    {
        "name": "self_harm_explicit",
        "pattern": r"\b(kill\s+myself|suicide|cut\s+myself|end\s+my\s+life|harm\s+myself)\b",
        "severity": Severity.BLOCK,
        "category": "self_harm",
        "description": "Explicit self-harm or suicide references.",
        "flags": re.IGNORECASE,
    },
    {
        "name": "sexual_explicit",
        "pattern": r"\b(pornograph(?:y|ic)|explicit\s+sex|sexual\s+intercourse)\b",
        "severity": Severity.BLOCK,
        "category": "sexual",
        "description": "Explicit sexual content.",
        "flags": re.IGNORECASE,
    },
    {
        "name": "hate_slur_n",
        "pattern": r"\bn[i1]gg[e3]r\b",
        "severity": Severity.BLOCK,
        "category": "hate",
        "description": "Racial slur (n-word with leet-speak variants).",
        "flags": re.IGNORECASE,
    },
    # --- WARNING-level rules (flagged, not blocked) -----------------------
    {
        "name": "violence_explicit",
        "pattern": r"\b(behead|disembowel|mutilate|massacre|gore)\b",
        "severity": Severity.WARNING,
        "category": "violence",
        "description": "Explicit violence / gore keywords.",
        "flags": re.IGNORECASE,
    },
    {
        "name": "pii_email",
        "pattern": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
        "severity": Severity.WARNING,
        "category": "pii",
        "description": "Email address detected.",
    },
    {
        "name": "pii_phone",
        # Loose phone pattern: 10+ digits with optional separators.
        "pattern": r"\b(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3,4}[\s.-]?\d{4}\b",
        "severity": Severity.WARNING,
        "category": "pii",
        "description": "Phone number detected.",
    },
    {
        "name": "pii_id_card_cn",
        # 18-digit Chinese ID card (basic structure check).
        "pattern": r"\b\d{17}[\dXx]\b",
        "severity": Severity.WARNING,
        "category": "pii",
        "description": "Possible Chinese ID card number.",
    },
    # --- INFO-level rules (log only) --------------------------------------
    {
        "name": "profanity_common",
        "pattern": r"\b(fuck|shit|bitch|asshole|dumbass)\b",
        "severity": Severity.INFO,
        "category": "profanity",
        "description": "Common profanity.",
        "flags": re.IGNORECASE,
    },
    # --- Chinese-language rules ------------------------------------------
    # The original rule set was English-only, leaving Chinese content
    # effectively unmoderated. These rules cover the same categories
    # (self-harm / sexual / hate / violence / pii) for Chinese text.
    # Patterns use alternation of common synonyms; deployments can refine.
    {
        "name": "self_harm_cn",
        "pattern": r"(自杀|自残|割腕|结束自己的生命|了结自己|不想活|跳楼|服毒|轻生)",
        "severity": Severity.BLOCK,
        "category": "self_harm",
        "description": "中文自残/自杀相关表述。",
    },
    {
        "name": "sexual_cn",
        "pattern": r"(色情|淫秽|性行为|性交|裸体描述|卖淫|嫖娼|强奸|迷奸)",
        "severity": Severity.BLOCK,
        "category": "sexual",
        "description": "中文涉黄/露骨性内容。",
    },
    {
        "name": "hate_cn",
        "pattern": r"(种族歧视|仇恨言论|纳粹|法西斯|辱华|黑鬼|劣等民族)",
        "severity": Severity.BLOCK,
        "category": "hate",
        "description": "中文仇恨言论/种族歧视。",
    },
    {
        "name": "violence_cn",
        "pattern": r"(斩首|分尸|肢解|屠杀|血腥暴力|虐杀|活剥|开膛破肚)",
        "severity": Severity.WARNING,
        "category": "violence",
        "description": "中文极端暴力/血腥关键词。",
    },
    {
        "name": "pii_phone_cn",
        # Chinese mobile: 1 + 10 digits (13x-19x).
        "pattern": r"1[3-9]\d{9}",
        "severity": Severity.WARNING,
        "category": "pii",
        "description": "可能的中文手机号。",
    },
    {
        "name": "profanity_cn",
        "pattern": r"(他妈的|操你|傻逼|王八蛋|滚蛋|狗屎)",
        "severity": Severity.INFO,
        "category": "profanity",
        "description": "中文常见粗口。",
    },
]


def make_default_rules() -> list[Rule]:
    """Build the default rule set.

    Returns a fresh list of Rule objects so callers can mutate the list
    (e.g. remove specific rules) without affecting future calls.
    """
    return [Rule.from_string(**d) for d in _DEFAULT_RULE_DEFS]


# ---------------------------------------------------------------------------
# RuleEngine — registry + check() runner
# ---------------------------------------------------------------------------


class RuleEngine:
    """Registry of safety rules + runner.

    Usage:
        engine = RuleEngine()  # loads default rules
        results = engine.check(text)
        if engine.should_block(results):
            # ... fail fast
    """

    def __init__(self, rules: Iterable[Rule] | None = None) -> None:
        # Use dict for name-indexed lookup (register replaces by name).
        self._rules: dict[str, Rule] = {}
        for rule in (rules if rules is not None else make_default_rules()):
            self.register(rule)

    def register(self, rule: Rule) -> None:
        """Add or replace a rule. Replacing by name is intentional — allows
        deployments to override defaults without mutating the default list.
        """
        self._rules[rule.name] = rule

    def unregister(self, name: str) -> bool:
        """Remove a rule by name. Returns True if it existed."""
        return self._rules.pop(name, None) is not None

    def list_rules(self) -> list[Rule]:
        """All registered rules (sorted by name for stable ordering)."""
        return sorted(self._rules.values(), key=lambda r: r.name)

    def has(self, name: str) -> bool:
        return name in self._rules

    def check(self, text: str) -> list[RuleResult]:
        """Run all rules against `text`. Returns one RuleResult per rule
        (matched or not).

        Non-matching rules are included with `matched=False` so callers
        can audit which rules ran. Use `matched_results()` to filter.
        """
        out: list[RuleResult] = []
        for rule in self.list_rules():
            matches = rule.pattern.findall(text)
            if matches:
                # Truncate evidence + cap match list to avoid log bloat.
                first = matches[0]
                evidence = (first[:80] + "...") if len(first) > 80 else first
                capped = tuple(str(m) for m in matches[:10])
                out.append(RuleResult(
                    rule_name=rule.name,
                    category=rule.category,
                    severity=rule.severity,
                    matched=True,
                    evidence=evidence,
                    matches=capped,
                ))
            else:
                out.append(RuleResult(
                    rule_name=rule.name,
                    category=rule.category,
                    severity=rule.severity,
                    matched=False,
                ))
        return out

    @staticmethod
    def matched_results(results: list[RuleResult]) -> list[RuleResult]:
        """Filter to only the rules that matched."""
        return [r for r in results if r.matched]

    @staticmethod
    def max_severity(results: list[RuleResult]) -> Severity:
        """Highest severity among matched results. INFO if nothing matched."""
        matched = [r for r in results if r.matched]
        if not matched:
            return Severity.INFO
        return max(r.severity for r in matched)

    @staticmethod
    def should_block(results: list[RuleResult]) -> bool:
        """True if any matched result has severity=BLOCK."""
        return any(r.matched and r.severity == Severity.BLOCK for r in results)

    @staticmethod
    def summarize(results: list[RuleResult]) -> dict:
        """Build a summary dict suitable for logging / API responses.

        Includes:
          - matched_count: number of rules that matched
          - max_severity: highest severity found (string)
          - should_block: whether to block
          - by_category: {category: [rule_name, ...]} for matched rules
        """
        matched = [r for r in results if r.matched]
        by_cat: dict[str, list[str]] = {}
        for r in matched:
            by_cat.setdefault(r.category, []).append(r.rule_name)
        return {
            "matched_count": len(matched),
            "max_severity": RuleEngine.max_severity(results).name,
            "should_block": RuleEngine.should_block(results),
            "by_category": by_cat,
        }
