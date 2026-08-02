"""Tests for app.safety — RuleEngine, default rules, ContentSafetyAgent.

Covers P2-safe-1: validates the two-phase safety review system.
Phase 1 is deterministic (regex rule engine) — tested without any LLM.
Phase 2 uses the three-stage pipeline — mocked via patch on
`app.agents.base.llm_draft/refine/evaluate`.

Test surface:
  - Severity enum: ordering, names
  - Rule / RuleResult dataclasses
  - RuleEngine: register / unregister / has / list_rules
  - RuleEngine.check: matched and non-matched rules
  - RuleEngine.matched_results / max_severity / should_block / summarize
  - make_default_rules: each category present, expected severities
  - Default rules detect their patterns (positive + negative cases)
  - ContentSafetyAgent: rule-blocked path (no LLM call)
  - ContentSafetyAgent: LLM-evaluated path (passed/failed)
  - ContentSafetyAgent: empty text → pass
  - ContentSafetyAgent: rejection of unsupported TaskKinds
  - ContentSafetyAgent: dep text collection priority
  - Factory integration: SAFETY_REVIEW now registered
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import make_novel_orchestrator
from app.planner.spec import (
    SubTask,
    SubTaskDAG,
    SubTaskStatus,
    TaskKind,
    TaskSpec,
)
from app.safety import (
    ContentSafetyAgent,
    Rule,
    RuleEngine,
    RuleResult,
    Severity,
    make_default_rules,
)
from app.safety.agent import (
    SAFETY_REFINE_SYSTEM_PROMPT,
    SAFETY_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _eval_response(score: float, feedback: str = "ok"):
    return _fake_llm_response(
        '{"score": ' + str(score) + ', "feedback": "' + feedback + '"}'
    )


def _make_safety_subtask(
    *,
    dep_results: dict[str, dict] | None = None,
) -> tuple[SubTask, SubTaskDAG]:
    """Build a SAFETY_REVIEW SubTask (with optional DONE dep results).

    When `dep_results` is supplied, each entry becomes a DONE dep task
    whose result is set. The SAFETY_REVIEW task depends on all of them.
    """
    if dep_results is None:
        dep_results = {}
    specs = [
        TaskSpec(
            task_id=dep_id,
            kind=TaskKind.FINAL_POLISH,
            inputs={},
            expected_output_keys=tuple(result.keys()),
        )
        for dep_id, result in dep_results.items()
    ]
    specs.append(
        TaskSpec(
            task_id="safety_review",
            kind=TaskKind.SAFETY_REVIEW,
            inputs={"chapter_indices": [1]},
            depends_on=tuple(dep_results.keys()),
            expected_output_keys=("passed", "issues"),
        )
    )
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
    for dep_id, result in dep_results.items():
        dag.update_status(dep_id, SubTaskStatus.DONE, result=result)
    return dag.get("safety_review"), dag


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


# ---------------------------------------------------------------------------
# ContentSafetyAgent — rule-blocked path (no LLM call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safety_agent_rule_block_short_circuits_without_llm():
    """When a BLOCK rule matches, the agent returns passed=False without
    invoking the LLM (saves latency + cost).
    """
    agent = ContentSafetyAgent(
        rule_engine=_block_engine(pattern=r"BANNED_WORD"),
        max_iters=1,
        score_threshold=0.99,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": "This text has BANNED_WORD in it."}
    })
    # Patch LLM wrappers — they should NOT be awaited.
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("should not be called")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("should not be called")
        )) as m_refine,
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )) as m_eval,
    ):
        result = await agent.handle(sub, dag)

    assert result["passed"] is False
    assert "BLOCKED by safety rules" in result["issues"]
    assert "block_test" in result["issues"]
    # LLM was NOT called — short-circuited by rule engine.
    assert m_draft.await_count == 0
    assert m_refine.await_count == 0
    assert m_eval.await_count == 0


@pytest.mark.asyncio
async def test_safety_agent_rule_block_includes_evidence_in_issues():
    """The issues string includes evidence snippets for traceability."""
    agent = ContentSafetyAgent(
        rule_engine=_block_engine(pattern=r"SECRET_TOKEN"),
        max_iters=1,
        score_threshold=0.99,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": "Leaked: SECRET_TOKEN_HERE"}
    })
    with (
        patch("app.agents.base.llm_draft", AsyncMock()),
        patch("app.agents.base.llm_refine", AsyncMock()),
        patch("app.agents.base.llm_evaluate", AsyncMock()),
    ):
        result = await agent.handle(sub, dag)
    assert result["passed"] is False
    assert "SECRET_TOKEN" in result["issues"]


# ---------------------------------------------------------------------------
# ContentSafetyAgent — LLM-evaluated path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safety_agent_llm_path_passes_when_verdict_safe():
    """No rule match + LLM verdict 'SAFE' + score >= 0.5 → passed=True."""
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.5,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": "A benign chapter about tea."}
    })
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.9, "all good")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["passed"] is True
    assert "LLM verdict: SAFE" in result["issues"]
    assert "Safety score: 0.90" in result["issues"]


@pytest.mark.asyncio
async def test_safety_agent_llm_path_fails_when_verdict_unsafe():
    """No rule match + LLM verdict 'UNSAFE: ...' → passed=False."""
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.99,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": "Some questionable content."}
    })
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("UNSAFE: implicit hate speech")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("UNSAFE: implicit hate speech")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.6, "ok")
        )),
    ):
        result = await agent.handle(sub, dag)
    assert result["passed"] is False
    assert "UNSAFE: implicit hate speech" in result["issues"]


@pytest.mark.asyncio
async def test_safety_agent_llm_path_fails_when_score_below_half():
    """Even if verdict says SAFE, a low evaluator score (< 0.5) → passed=False.

    Treats the evaluator as a backstop in case the verdict is ambiguous
    or the LLM returns a non-YES/NO answer.
    """
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.99,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": "Some text."}
    })
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.3, "low confidence")
        )),
    ):
        result = await agent.handle(sub, dag)
    # Verdict says SAFE but score=0.3 < 0.5 → fails.
    assert result["passed"] is False
    assert "Safety score: 0.30" in result["issues"]


@pytest.mark.asyncio
async def test_safety_agent_llm_path_with_warning_flags_still_runs_llm():
    """WARNING-level rule matches don't block — LLM still runs and decides."""
    warn_engine = RuleEngine(rules=[
        Rule.from_string(
            name="violence_test",
            pattern=r"blood",
            severity=Severity.WARNING,
            category="violence",
        )
    ])
    agent = ContentSafetyAgent(
        rule_engine=warn_engine,
        max_iters=1,
        score_threshold=0.5,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": "There was blood on the floor."}
    })
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.8, "ok in thriller context")
        )),
    ):
        result = await agent.handle(sub, dag)
    # LLM was called (not short-circuited).
    assert m_draft.await_count == 1
    # Verdict SAFE + score 0.8 → pass.
    assert result["passed"] is True
    # Rule engine flags should appear in issues for traceability.
    assert "violence_test" in result["issues"]
    assert "Rule engine flags" in result["issues"]


@pytest.mark.asyncio
async def test_safety_agent_uses_safety_system_prompt():
    """The draft call's system prompt is the safety-specific one."""
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.99,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": "Some text."}
    })
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.9, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    sys_prompt = m_draft.call_args.args[0][0]["content"]
    assert sys_prompt == SAFETY_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_safety_agent_uses_safety_refine_system_prompt():
    """The refine call's system prompt is the safety-specific refine prompt."""
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.99,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": "Some text."}
    })
    with (
        patch("app.agents.base.llm_draft", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )) as m_refine,
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.5, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    refine_sys = m_refine.call_args.args[0][0]["content"]
    assert refine_sys == SAFETY_REFINE_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# ContentSafetyAgent — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safety_agent_empty_text_passes_without_llm_call():
    """No text to review → pass by default, no LLM call."""
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.99,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": ""}
    })
    with (
        patch("app.agents.base.llm_draft", AsyncMock()) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock()),
        patch("app.agents.base.llm_evaluate", AsyncMock()),
    ):
        result = await agent.handle(sub, dag)
    assert result["passed"] is True
    assert "No text to review" in result["issues"]
    assert m_draft.await_count == 0


@pytest.mark.asyncio
async def test_safety_agent_no_deps_passes_without_llm_call():
    """No deps at all → no text → pass by default."""
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.99,
    )
    # No dep_results → empty deps.
    specs = [
        TaskSpec(
            task_id="safety_review",
            kind=TaskKind.SAFETY_REVIEW,
            inputs={"chapter_indices": [1]},
            expected_output_keys=("passed", "issues"),
        )
    ]
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
    sub = dag.get("safety_review")
    with (
        patch("app.agents.base.llm_draft", AsyncMock()) as m_draft,
        patch("app.agents.base.llm_refine", AsyncMock()),
        patch("app.agents.base.llm_evaluate", AsyncMock()),
    ):
        result = await agent.handle(sub, dag)
    assert result["passed"] is True
    assert m_draft.await_count == 0


# ---------------------------------------------------------------------------
# ContentSafetyAgent — dep text collection priority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safety_agent_prefers_final_polish_dep_text():
    """When both final_polish and chapter_refine_N exist, prefer final_polish."""
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.99,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": "FINAL_POLISH_TEXT"},
        "chapter_refine_1": {"content_text": "REFINE_TEXT"},
    })
    captured: list[str] = []

    async def _draft(messages, *, stage_config=None):
        captured.append(messages[1]["content"])
        return _fake_llm_response("SAFE")

    with (
        patch("app.agents.base.llm_draft", AsyncMock(side_effect=_draft)),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.8, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    # The text passed to the LLM should be the final_polish output.
    assert "FINAL_POLISH_TEXT" in captured[0]
    # And NOT the chapter_refine_1 output.
    assert "REFINE_TEXT" not in captured[0]


@pytest.mark.asyncio
async def test_safety_agent_falls_back_to_chapter_refine_dep():
    """Without final_polish, fall back to chapter_refine_N's content_text."""
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.99,
    )
    sub, dag = _make_safety_subtask(dep_results={
        "chapter_refine_1": {"content_text": "REFINE_TEXT"},
        "outline": {"chapter_outline": "outline"},
    })
    captured: list[str] = []

    async def _draft(messages, *, stage_config=None):
        captured.append(messages[1]["content"])
        return _fake_llm_response("SAFE")

    with (
        patch("app.agents.base.llm_draft", AsyncMock(side_effect=_draft)),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.8, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    assert "REFINE_TEXT" in captured[0]


@pytest.mark.asyncio
async def test_safety_agent_truncates_long_text():
    """Text > 8000 chars is truncated to fit the LLM token budget."""
    agent = ContentSafetyAgent(
        rule_engine=_no_match_engine(),
        max_iters=1,
        score_threshold=0.99,
    )
    long_text = "x" * 10000
    sub, dag = _make_safety_subtask(dep_results={
        "final_polish": {"content_text": long_text}
    })
    captured: list[str] = []

    async def _draft(messages, *, stage_config=None):
        captured.append(messages[1]["content"])
        return _fake_llm_response("SAFE")

    with (
        patch("app.agents.base.llm_draft", AsyncMock(side_effect=_draft)),
        patch("app.agents.base.llm_refine", AsyncMock(
            return_value=_fake_llm_response("SAFE")
        )),
        patch("app.agents.base.llm_evaluate", AsyncMock(
            return_value=_eval_response(0.8, "ok")
        )),
    ):
        await agent.handle(sub, dag)
    # The captured user prompt should be shorter than the original 10000 chars.
    assert len(captured[0]) < 10000
    assert "[truncated]" in captured[0]


# ---------------------------------------------------------------------------
# ContentSafetyAgent — rejections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safety_agent_rejects_outline_kind():
    agent = ContentSafetyAgent(rule_engine=_no_match_engine())
    specs = [TaskSpec(
        task_id="o", kind=TaskKind.OUTLINE, inputs={},
        expected_output_keys=("chapter_outline",)
    )]
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
    sub = dag.get("o")
    with pytest.raises(ValueError, match="ContentSafetyAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_safety_agent_rejects_character_kind():
    agent = ContentSafetyAgent(rule_engine=_no_match_engine())
    specs = [TaskSpec(
        task_id="c", kind=TaskKind.CHARACTER, inputs={},
        expected_output_keys=("characters",)
    )]
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
    sub = dag.get("c")
    with pytest.raises(ValueError, match="ContentSafetyAgent cannot handle"):
        await agent.handle(sub, dag)


@pytest.mark.asyncio
async def test_safety_agent_rejects_chapter_draft_kind():
    agent = ContentSafetyAgent(rule_engine=_no_match_engine())
    specs = [TaskSpec(
        task_id="d", kind=TaskKind.CHAPTER_DRAFT, inputs={},
        expected_output_keys=("content_text", "summary")
    )]
    dag = SubTaskDAG(tasks={s.task_id: SubTask(spec=s) for s in specs})
    sub = dag.get("d")
    with pytest.raises(ValueError, match="ContentSafetyAgent cannot handle"):
        await agent.handle(sub, dag)


# ---------------------------------------------------------------------------
# Factory integration — make_novel_orchestrator
# ---------------------------------------------------------------------------


def test_factory_registers_safety_agent():
    """make_novel_orchestrator now registers SAFETY_REVIEW via ContentSafetyAgent."""
    orch = make_novel_orchestrator()
    assert TaskKind.SAFETY_REVIEW in orch._handlers
    handler = orch._handlers[TaskKind.SAFETY_REVIEW]
    assert isinstance(handler.__self__, ContentSafetyAgent)


def test_factory_passes_rule_engine_to_safety_agent():
    """A custom rule_engine propagates to the safety agent."""
    custom_engine = RuleEngine(rules=[])
    orch = make_novel_orchestrator(rule_engine=custom_engine)
    safety = orch._handlers[TaskKind.SAFETY_REVIEW].__self__
    assert safety.rule_engine is custom_engine


def test_factory_safety_agent_uses_default_rules_when_none_provided():
    """Without a custom rule_engine, the safety agent uses default rules."""
    orch = make_novel_orchestrator()
    safety = orch._handlers[TaskKind.SAFETY_REVIEW].__self__
    # Default engine has the built-in rules.
    assert safety.rule_engine.has("self_harm_explicit")
    assert safety.rule_engine.has("pii_email")
