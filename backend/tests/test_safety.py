"""Tests for app.safety — RuleEngine and default rules.

The deterministic regex safety engine used by pipeline safety_check.

Test surface:
  - Severity enum: ordering, names
  - Rule / RuleResult dataclasses
  - RuleEngine: register / unregister / has / list_rules
  - RuleEngine.check: matched and non-matched rules
  - RuleEngine.matched_results / max_severity / should_block / summarize
  - make_default_rules: each category present, expected severities
  - Default rules detect their patterns (positive + negative cases)
"""
from __future__ import annotations

import re

import pytest


from app.safety import (
    Rule,
    RuleEngine,
    RuleResult,
    Severity,
    make_default_rules,
)



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_match_engine() -> RuleEngine:
    """A RuleEngine with no rules — guaranteed no matches / no blocks."""
    return RuleEngine(rules=[])


def _block_engine(pattern: str = r"BLOCKED_KEYWORD") -> RuleEngine:
    """A RuleEngine with one BLOCK rule matching `pattern`."""
    return RuleEngine(rules=[
        Rule.from_string(
            name="block_test",
            pattern=pattern,
            severity=Severity.BLOCK,
            category="test",
            description="Test block rule.",
        )
    ])


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


def test_severity_ordering():
    """Higher value = more serious."""
    assert Severity.INFO < Severity.WARNING < Severity.BLOCK


def test_severity_names():
    assert Severity.INFO.name == "INFO"
    assert Severity.WARNING.name == "WARNING"
    assert Severity.BLOCK.name == "BLOCK"


def test_severity_max_function():
    """max() picks the highest severity."""
    assert max(Severity.INFO, Severity.BLOCK) == Severity.BLOCK
    assert max(Severity.WARNING, Severity.INFO) == Severity.WARNING


# ---------------------------------------------------------------------------
# Rule / RuleResult dataclasses
# ---------------------------------------------------------------------------


def test_rule_from_string_compiles_pattern():
    rule = Rule.from_string(
        name="r1",
        pattern=r"\btest\b",
        severity=Severity.WARNING,
        category="test",
    )
    assert rule.name == "r1"
    assert isinstance(rule.pattern, re.Pattern)
    assert rule.severity == Severity.WARNING
    assert rule.category == "test"
    assert rule.description == ""


def test_rule_from_string_with_flags():
    """Flags are passed to re.compile."""
    rule = Rule.from_string(
        name="r",
        pattern=r"hello",
        severity=Severity.INFO,
        category="test",
        flags=re.IGNORECASE,
    )
    assert rule.pattern.search("HELLO world") is not None


def test_rule_result_default_fields():
    r = RuleResult(
        rule_name="r",
        category="test",
        severity=Severity.INFO,
        matched=False,
    )
    assert r.evidence == ""
    assert r.matches == ()


def test_rule_result_with_evidence_and_matches():
    r = RuleResult(
        rule_name="r",
        category="test",
        severity=Severity.WARNING,
        matched=True,
        evidence="snippet",
        matches=("m1", "m2"),
    )
    assert r.matched is True
    assert r.evidence == "snippet"
    assert r.matches == ("m1", "m2")


# ---------------------------------------------------------------------------
# RuleEngine — registration / lookup
# ---------------------------------------------------------------------------


def test_engine_starts_with_default_rules():
    engine = RuleEngine()
    names = {r.name for r in engine.list_rules()}
    # Should include the canonical default rules.
    assert "self_harm_explicit" in names
    assert "sexual_explicit" in names
    assert "hate_slur_n" in names
    assert "pii_email" in names
    assert "profanity_common" in names


def test_engine_starts_empty_with_empty_rules():
    engine = RuleEngine(rules=[])
    assert engine.list_rules() == []
    assert engine.has("anything") is False


def test_engine_register_adds_rule():
    engine = RuleEngine(rules=[])
    rule = Rule.from_string(
        name="x",
        pattern=r"x",
        severity=Severity.INFO,
        category="test",
    )
    engine.register(rule)
    assert engine.has("x")
    assert engine.list_rules()[0] is rule


def test_engine_register_replaces_by_name():
    """Registering with an existing name replaces the rule."""
    engine = RuleEngine(rules=[])
    original = Rule.from_string(
        name="x", pattern=r"original", severity=Severity.INFO, category="c"
    )
    replacement = Rule.from_string(
        name="x", pattern=r"new", severity=Severity.BLOCK, category="c"
    )
    engine.register(original)
    engine.register(replacement)
    rules = engine.list_rules()
    assert len(rules) == 1
    assert rules[0].pattern.pattern == "new"
    assert rules[0].severity == Severity.BLOCK


def test_engine_unregister_returns_true_when_present():
    engine = RuleEngine(rules=[])
    engine.register(Rule.from_string(
        name="x", pattern=r"x", severity=Severity.INFO, category="c"
    ))
    assert engine.unregister("x") is True
    assert engine.has("x") is False


def test_engine_unregister_returns_false_when_absent():
    engine = RuleEngine(rules=[])
    assert engine.unregister("nope") is False


def test_engine_list_rules_sorted_by_name():
    """list_rules() returns a stable, name-sorted list."""
    engine = RuleEngine(rules=[])
    engine.register(Rule.from_string(
        name="z", pattern=r"z", severity=Severity.INFO, category="c"
    ))
    engine.register(Rule.from_string(
        name="a", pattern=r"a", severity=Severity.INFO, category="c"
    ))
    engine.register(Rule.from_string(
        name="m", pattern=r"m", severity=Severity.INFO, category="c"
    ))
    names = [r.name for r in engine.list_rules()]
    assert names == ["a", "m", "z"]


# ---------------------------------------------------------------------------
# RuleEngine.check — matched / non-matched
# ---------------------------------------------------------------------------


def test_check_returns_result_per_rule():
    """Every registered rule produces a RuleResult (matched or not)."""
    engine = RuleEngine(rules=[
        Rule.from_string(
            name="hello", pattern=r"hello", severity=Severity.INFO, category="greeting"
        ),
        Rule.from_string(
            name="world", pattern=r"world", severity=Severity.INFO, category="greeting"
        ),
    ])
    results = engine.check("hello there")
    assert len(results) == 2
    by_name = {r.rule_name: r for r in results}
    assert by_name["hello"].matched is True
    assert by_name["world"].matched is False


def test_check_captures_evidence_and_matches():
    engine = RuleEngine(rules=[
        Rule.from_string(
            name="email", pattern=r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
            severity=Severity.WARNING, category="pii",
        )
    ])
    text = "Contact me at alice@example.com or bob@test.io"
    results = engine.check(text)
    assert len(results) == 1
    r = results[0]
    assert r.matched is True
    assert r.evidence == "alice@example.com"
    assert "alice@example.com" in r.matches
    assert "bob@test.io" in r.matches


def test_check_truncates_long_evidence():
    """Long matches get truncated to 80 chars + '...'."""
    long_email = "a" * 100 + "@example.com"
    engine = RuleEngine(rules=[
        Rule.from_string(
            name="email", pattern=r"\S+@example\.com",
            severity=Severity.WARNING, category="pii",
        )
    ])
    results = engine.check(long_email)
    assert results[0].matched is True
    assert results[0].evidence.endswith("...")
    assert len(results[0].evidence) == 83  # 80 + "..."


def test_check_caps_matches_at_ten():
    """Match list is capped at 10 to avoid log bloat."""
    engine = RuleEngine(rules=[
        Rule.from_string(
            name="digits", pattern=r"\d", severity=Severity.INFO, category="test"
        )
    ])
    text = "0123456789"  # 10 digits → exactly the cap
    results = engine.check(text)
    assert len(results[0].matches) == 10
    # 11 digits → still capped at 10.
    text = "0123456789012"
    results = engine.check(text)
    assert len(results[0].matches) == 10


# ---------------------------------------------------------------------------
# RuleEngine static helpers — matched_results / max_severity / should_block / summarize
# ---------------------------------------------------------------------------


def test_matched_results_filters_to_matched_only():
    engine = RuleEngine(rules=[
        Rule.from_string(
            name="a", pattern=r"a", severity=Severity.INFO, category="x"
        ),
        Rule.from_string(
            name="b", pattern=r"b", severity=Severity.INFO, category="x"
        ),
    ])
    results = engine.check("a")
    matched = RuleEngine.matched_results(results)
    assert len(matched) == 1
    assert matched[0].rule_name == "a"


def test_max_severity_returns_info_when_no_matches():
    results = [
        RuleResult("a", "x", Severity.WARNING, matched=False),
        RuleResult("b", "x", Severity.BLOCK, matched=False),
    ]
    assert RuleEngine.max_severity(results) == Severity.INFO


def test_max_severity_returns_highest_matched():
    results = [
        RuleResult("a", "x", Severity.INFO, matched=True),
        RuleResult("b", "x", Severity.BLOCK, matched=False),
        RuleResult("c", "x", Severity.WARNING, matched=True),
    ]
    # Highest MATCHED is WARNING (the BLOCK rule didn't match).
    assert RuleEngine.max_severity(results) == Severity.WARNING


def test_should_block_true_when_block_rule_matches():
    results = [
        RuleResult("a", "x", Severity.INFO, matched=True),
        RuleResult("b", "x", Severity.BLOCK, matched=True),
    ]
    assert RuleEngine.should_block(results) is True


def test_should_block_false_when_no_block_match():
    results = [
        RuleResult("a", "x", Severity.INFO, matched=True),
        RuleResult("b", "x", Severity.BLOCK, matched=False),
    ]
    assert RuleEngine.should_block(results) is False


def test_should_block_false_when_no_matches_at_all():
    results = [
        RuleResult("a", "x", Severity.BLOCK, matched=False),
    ]
    assert RuleEngine.should_block(results) is False


def test_summarize_no_matches():
    results = [RuleResult("a", "x", Severity.WARNING, matched=False)]
    s = RuleEngine.summarize(results)
    assert s["matched_count"] == 0
    assert s["max_severity"] == "INFO"
    assert s["should_block"] is False
    assert s["by_category"] == {}


def test_summarize_with_matches_across_categories():
    results = [
        RuleResult("email", "pii", Severity.WARNING, matched=True),
        RuleResult("phone", "pii", Severity.WARNING, matched=True),
        RuleResult("violence", "violence", Severity.BLOCK, matched=False),
    ]
    s = RuleEngine.summarize(results)
    assert s["matched_count"] == 2
    assert s["max_severity"] == "WARNING"
    assert s["should_block"] is False
    assert s["by_category"] == {"pii": ["email", "phone"]}


def test_summarize_with_block_match():
    results = [
        RuleResult("self_harm", "self_harm", Severity.BLOCK, matched=True),
        RuleResult("email", "pii", Severity.WARNING, matched=True),
    ]
    s = RuleEngine.summarize(results)
    assert s["should_block"] is True
    assert s["max_severity"] == "BLOCK"
    assert "self_harm" in s["by_category"]["self_harm"]


# ---------------------------------------------------------------------------
# make_default_rules — built-in rule set
# ---------------------------------------------------------------------------


def test_make_default_rules_returns_list():
    rules = make_default_rules()
    assert isinstance(rules, list)
    assert len(rules) > 0


def test_make_default_rules_includes_each_category():
    rules = make_default_rules()
    categories = {r.category for r in rules}
    # Built-in categories — see module docstring.
    assert "self_harm" in categories
    assert "sexual" in categories
    assert "hate" in categories
    assert "violence" in categories
    assert "pii" in categories
    assert "profanity" in categories


def test_make_default_rules_self_harm_is_block():
    rules = make_default_rules()
    self_harm = next(r for r in rules if r.category == "self_harm")
    assert self_harm.severity == Severity.BLOCK


def test_make_default_rules_hate_is_block():
    rules = make_default_rules()
    hate = next(r for r in rules if r.category == "hate")
    assert hate.severity == Severity.BLOCK


def test_make_default_rules_sexual_is_block():
    rules = make_default_rules()
    sexual = next(r for r in rules if r.category == "sexual")
    assert sexual.severity == Severity.BLOCK


def test_make_default_rules_profanity_is_info():
    rules = make_default_rules()
    profanity = next(r for r in rules if r.category == "profanity")
    assert profanity.severity == Severity.INFO


def test_make_default_rules_pii_is_warning():
    """All PII rules (email/phone/ID card) are WARNING severity."""
    rules = make_default_rules()
    pii_rules = [r for r in rules if r.category == "pii"]
    assert len(pii_rules) >= 2
    for r in pii_rules:
        assert r.severity == Severity.WARNING


def test_make_default_rules_returns_fresh_list():
    """Each call returns a new list — callers can mutate without side effects."""
    a = make_default_rules()
    b = make_default_rules()
    assert a is not b
    a.clear()
    assert len(b) > 0  # unaffected


# ---------------------------------------------------------------------------
# Default rules — positive + negative detection tests
# ---------------------------------------------------------------------------


def test_default_self_harm_rule_detects_keyword():
    engine = RuleEngine()
    results = engine.check("I want to kill myself tonight")
    matched = [r for r in results if r.matched and r.category == "self_harm"]
    assert len(matched) >= 1
    assert RuleEngine.should_block(results) is True


def test_default_self_harm_rule_does_not_flag_safe_text():
    engine = RuleEngine()
    results = engine.check("The detective solved the mystery.")
    assert not any(r.matched and r.category == "self_harm" for r in results)


def test_default_email_rule_detects_email():
    engine = RuleEngine()
    results = engine.check("Contact: alice@example.com for details.")
    matched = [r for r in results if r.matched and r.rule_name == "pii_email"]
    assert len(matched) == 1
    assert "alice@example.com" in matched[0].matches
    assert RuleEngine.should_block(results) is False  # WARNING, not BLOCK


def test_default_phone_rule_detects_us_phone():
    engine = RuleEngine()
    results = engine.check("Call me at (555) 123-4567")
    matched = [r for r in results if r.matched and r.rule_name == "pii_phone"]
    assert len(matched) == 1


def test_default_id_card_rule_detects_18_digit_id():
    engine = RuleEngine()
    results = engine.check("ID: 110101199001011234")
    matched = [r for r in results if r.matched and r.rule_name == "pii_id_card_cn"]
    assert len(matched) == 1


def test_default_profanity_rule_detects_word():
    engine = RuleEngine()
    results = engine.check("What the fuck is going on")
    matched = [r for r in results if r.matched and r.category == "profanity"]
    assert len(matched) >= 1
    # Profanity is INFO — doesn't block.
    assert RuleEngine.should_block(results) is False
    assert RuleEngine.max_severity(results) == Severity.INFO


def test_default_violence_rule_flags_warning():
    engine = RuleEngine()
    results = engine.check("The massacre was brutal and gory.")
    matched = [r for r in results if r.matched and r.category == "violence"]
    assert len(matched) >= 1
    # Violence is WARNING — doesn't block.
    assert RuleEngine.should_block(results) is False
    assert RuleEngine.max_severity(results) == Severity.WARNING


def test_default_hate_rule_blocks_slur():
    engine = RuleEngine()
    # Use a variant the regex catches (with leet-speak normalization).
    results = engine.check("You are a n1gger")
    assert RuleEngine.should_block(results) is True
