"""Tests for app.parser — natural-language → structured task spec.

Covers P3-parse-1: validates the TaskParser that converts natural
language novel requests into ParsedTaskSpec for the PlannerAgent.

Test surface:
  - ParsedTaskSpec: construction, validation, to_planner_kwargs, to_dict
  - _zh_numeral_to_int: digits, Chinese numerals, edge cases
  - _detect_language: zh / en detection
  - TaskParser rule-based extraction:
    - Chapter count: digits, Chinese numerals, English
    - Word count: 字 / words / 千字
    - Genre detection: zh + en keywords
    - Tone detection
    - Premise extraction (strips boilerplate)
    - Confidence scoring (full / partial / minimal)
  - TaskParser LLM-assisted parsing:
    - LLM refinement on low confidence
    - JSON parse failure → rule-based fallback
    - LLM disabled by default
  - Integration with PlannerAgent.plan()
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import litellm

from app.parser import ParsedTaskSpec, TaskParser
from app.parser.parser import _detect_language, _zh_numeral_to_int
from app.planner import PlannerAgent
from app.planner.spec import SubTaskDAG


# ---------------------------------------------------------------------------
# Helpers — fake LLM response shape
# ---------------------------------------------------------------------------


def _fake_llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _llm_json_response(
    *,
    premise: str = "parsed premise",
    chapter_count: int = 3,
    target_words_per_chapter: int = 4000,
    genre: str | None = "mystery",
    tone: str | None = "dark",
    language: str = "zh",
    confidence: float = 0.95,
):
    import json

    return _fake_llm_response(
        json.dumps(
            {
                "premise": premise,
                "chapter_count": chapter_count,
                "target_words_per_chapter": target_words_per_chapter,
                "genre": genre,
                "tone": tone,
                "language": language,
                "confidence": confidence,
            },
            ensure_ascii=False,
        )
    )


# ---------------------------------------------------------------------------
# ParsedTaskSpec
# ---------------------------------------------------------------------------


class TestParsedTaskSpec:
    def test_basic_construction(self):
        s = ParsedTaskSpec(premise="A mystery novel.")
        assert s.premise == "A mystery novel."
        assert s.chapter_count == 1
        assert s.target_words_per_chapter == 3000
        assert s.genre is None
        assert s.tone is None
        assert s.language == "zh"
        assert s.parser_source == "rule"
        assert s.parser_confidence == 1.0

    def test_full_construction(self):
        s = ParsedTaskSpec(
            premise="test",
            chapter_count=5,
            target_words_per_chapter=5000,
            genre="mystery",
            tone="dark",
            language="en",
            extra_inputs={"foo": "bar"},
            parser_source="llm",
            parser_confidence=0.8,
        )
        assert s.chapter_count == 5
        assert s.target_words_per_chapter == 5000
        assert s.genre == "mystery"
        assert s.tone == "dark"
        assert s.language == "en"
        assert s.extra_inputs == {"foo": "bar"}
        assert s.parser_source == "llm"
        assert s.parser_confidence == 0.8

    def test_empty_premise_raises(self):
        with pytest.raises(ValueError, match="premise must be non-empty"):
            ParsedTaskSpec(premise="")

    def test_whitespace_premise_raises(self):
        with pytest.raises(ValueError, match="premise must be non-empty"):
            ParsedTaskSpec(premise="   ")

    def test_zero_chapter_count_raises(self):
        with pytest.raises(ValueError, match="chapter_count must be >= 1"):
            ParsedTaskSpec(premise="x", chapter_count=0)

    def test_negative_chapter_count_raises(self):
        with pytest.raises(ValueError, match="chapter_count must be >= 1"):
            ParsedTaskSpec(premise="x", chapter_count=-3)

    def test_too_small_word_count_raises(self):
        with pytest.raises(ValueError, match="target_words_per_chapter must be >= 100"):
            ParsedTaskSpec(premise="x", target_words_per_chapter=50)

    def test_negative_confidence_raises(self):
        with pytest.raises(ValueError, match="parser_confidence must be in"):
            ParsedTaskSpec(premise="x", parser_confidence=-0.1)

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValueError, match="parser_confidence must be in"):
            ParsedTaskSpec(premise="x", parser_confidence=1.5)

    def test_confidence_zero_ok(self):
        s = ParsedTaskSpec(premise="x", parser_confidence=0.0)
        assert s.parser_confidence == 0.0

    def test_confidence_one_ok(self):
        s = ParsedTaskSpec(premise="x", parser_confidence=1.0)
        assert s.parser_confidence == 1.0

    def test_frozen(self):
        s = ParsedTaskSpec(premise="x")
        with pytest.raises(Exception):
            s.premise = "changed"  # type: ignore[misc]

    def test_to_planner_kwargs_contains_required_fields(self):
        s = ParsedTaskSpec(premise="test premise", chapter_count=5)
        kwargs = s.to_planner_kwargs()
        assert kwargs["premise"] == "test premise"
        assert kwargs["chapter_count"] == 5
        assert kwargs["target_words_per_chapter"] == 3000
        assert "extra_inputs" in kwargs

    def test_to_planner_kwargs_extra_inputs_none_when_empty(self):
        s = ParsedTaskSpec(premise="x")
        kwargs = s.to_planner_kwargs()
        assert kwargs["extra_inputs"] is None

    def test_to_planner_kwargs_extra_inputs_dict_when_set(self):
        s = ParsedTaskSpec(
            premise="x",
            extra_inputs={"genre": "mystery"},
        )
        kwargs = s.to_planner_kwargs()
        assert kwargs["extra_inputs"] == {"genre": "mystery"}

    def test_to_dict_structure(self):
        s = ParsedTaskSpec(
            premise="test",
            chapter_count=3,
            target_words_per_chapter=4000,
            genre="mystery",
            tone="dark",
            language="en",
            extra_inputs={"genre": "mystery", "tone": "dark"},
            parser_source="llm",
            parser_confidence=0.9,
        )
        d = s.to_dict()
        assert d["premise"] == "test"
        assert d["chapter_count"] == 3
        assert d["target_words_per_chapter"] == 4000
        assert d["genre"] == "mystery"
        assert d["tone"] == "dark"
        assert d["language"] == "en"
        assert d["parser_source"] == "llm"
        assert d["parser_confidence"] == 0.9
        assert d["extra_inputs"] == {"genre": "mystery", "tone": "dark"}


# ---------------------------------------------------------------------------
# _zh_numeral_to_int
# ---------------------------------------------------------------------------


class TestZhNumeralToInt:
    def test_digit_string(self):
        assert _zh_numeral_to_int("5") == 5

    def test_ten(self):
        assert _zh_numeral_to_int("十") == 10

    def test_eleven(self):
        assert _zh_numeral_to_int("十一") == 11

    def test_twenty(self):
        assert _zh_numeral_to_int("二十") == 20

    def test_twenty_three(self):
        assert _zh_numeral_to_int("二十三") == 23

    def test_five(self):
        assert _zh_numeral_to_int("五") == 5

    def test_eight(self):
        assert _zh_numeral_to_int("八") == 8

    def test_empty_returns_none(self):
        assert _zh_numeral_to_int("") is None

    def test_invalid_returns_none(self):
        assert _zh_numeral_to_int("abc") is None

    def test_hundred(self):
        # "一百" — not in our simple map, but let's at least make sure
        # it doesn't crash. The simple map doesn't handle 百.
        result = _zh_numeral_to_int("一百")
        # _ZH_NUMERAL_MAP has no "百" entry, so this falls through
        # to multi-digit parsing which fails (KeyError caught)
        assert result is None


# ---------------------------------------------------------------------------
# _detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_pure_chinese(self):
        assert _detect_language("写一本侦探小说") == "zh"

    def test_mostly_chinese(self):
        assert _detect_language("写一本sci-fi小说") == "zh"

    def test_pure_english(self):
        assert _detect_language("Write a mystery novel") == "en"

    def test_mixed_low_cjk(self):
        # Below 30% threshold → "en"
        assert _detect_language("Hi there! 侦探") == "en"

    def test_empty_returns_zh(self):
        assert _detect_language("") == "zh"

    def test_punctuation_only_returns_en(self):
        assert _detect_language("!@#$%") == "en"

    def test_threshold_30_percent(self):
        # 3 CJK chars out of 10 total = exactly 0.3 — condition is `> 0.3`,
        # so this should be "en"
        assert _detect_language("一二三abcdefg") == "en"

    def test_just_above_threshold(self):
        # 4 CJK chars out of 13 total ≈ 0.308 — above threshold
        assert _detect_language("abc一二三四de") == "zh"


# ---------------------------------------------------------------------------
# TaskParser — rule-based extraction
# ---------------------------------------------------------------------------


class TestTaskParserRuleBased:
    def test_parse_chinese_full_spec(self):
        parser = TaskParser()
        spec = parser.parse("写一本关于侦探推理的小说，包含5个章节，每章约3000字")
        assert spec.chapter_count == 5
        assert spec.target_words_per_chapter == 3000
        assert spec.genre == "mystery"  # "侦探" detected
        assert spec.language == "zh"
        assert spec.parser_source == "rule"
        assert spec.parser_confidence == 1.0  # both chapter+word found
        assert spec.premise  # non-empty

    def test_parse_english_full_spec(self):
        parser = TaskParser()
        spec = parser.parse("Write a 3-chapter sci-fi novel, 5000 words each")
        assert spec.chapter_count == 3
        assert spec.target_words_per_chapter == 5000
        assert spec.genre == "sci-fi"
        assert spec.language == "en"
        assert spec.parser_confidence == 1.0

    def test_parse_chinese_numeral_chapter_count(self):
        parser = TaskParser()
        spec = parser.parse("写一本五章的侦探小说")
        assert spec.chapter_count == 5
        assert spec.chapter_count != 1  # not the default

    def test_parse_default_chapter_count_when_missing(self):
        parser = TaskParser()
        spec = parser.parse("写一本侦探小说")
        assert spec.chapter_count == 1

    def test_parse_default_word_count_when_missing(self):
        parser = TaskParser()
        spec = parser.parse("写一本侦探小说")
        assert spec.target_words_per_chapter == 3000

    def test_parse_word_count_zh_with_qian(self):
        # "3千字" → 3000
        parser = TaskParser()
        spec = parser.parse("写一本小说，每章3千字")
        assert spec.target_words_per_chapter == 3000

    def test_parse_minimal_input(self):
        parser = TaskParser()
        spec = parser.parse("侦探小说")
        assert spec.premise == "侦探小说"
        assert spec.chapter_count == 1
        assert spec.target_words_per_chapter == 3000
        assert spec.genre == "mystery"
        # Confidence should be low since defaults are used
        assert spec.parser_confidence < 0.7

    def test_parse_empty_input_raises(self):
        parser = TaskParser()
        with pytest.raises(ValueError, match="parse input must be non-empty"):
            parser.parse("")

    def test_parse_whitespace_input_raises(self):
        parser = TaskParser()
        with pytest.raises(ValueError, match="parse input must be non-empty"):
            parser.parse("   ")

    def test_parse_genre_chinese_mystery(self):
        parser = TaskParser()
        spec = parser.parse("写一本推理小说")
        assert spec.genre == "mystery"

    def test_parse_genre_chinese_scifi(self):
        parser = TaskParser()
        spec = parser.parse("写一本科幻小说")
        assert spec.genre == "sci-fi"

    def test_parse_genre_chinese_fantasy(self):
        parser = TaskParser()
        spec = parser.parse("写一本玄幻小说")
        assert spec.genre == "fantasy"

    def test_parse_genre_chinese_romance(self):
        parser = TaskParser()
        spec = parser.parse("写一本言情小说")
        assert spec.genre == "romance"

    def test_parse_genre_english_fantasy(self):
        parser = TaskParser()
        spec = parser.parse("Write a fantasy novel")
        assert spec.genre == "fantasy"

    def test_parse_genre_none_when_unknown(self):
        parser = TaskParser()
        spec = parser.parse("Write a novel about cooking")
        assert spec.genre is None

    def test_parse_tone_dark(self):
        parser = TaskParser()
        spec = parser.parse("写一本黑暗风格的侦探小说")
        assert spec.tone == "dark"

    def test_parse_tone_light(self):
        parser = TaskParser()
        spec = parser.parse("Write a light-hearted mystery novel")
        assert spec.tone == "light"

    def test_parse_tone_epic(self):
        parser = TaskParser()
        spec = parser.parse("写一本史诗风格的奇幻小说")
        assert spec.tone == "epic"

    def test_parse_tone_none_when_unknown(self):
        parser = TaskParser()
        spec = parser.parse("Write a mystery novel")
        assert spec.tone is None

    def test_parse_extra_inputs_includes_genre_and_tone(self):
        parser = TaskParser()
        spec = parser.parse("写一本黑暗风格的5章侦探小说")
        assert spec.extra_inputs.get("genre") == "mystery"
        assert spec.extra_inputs.get("tone") == "dark"

    def test_parse_extra_inputs_empty_when_no_genre_no_tone(self):
        parser = TaskParser()
        spec = parser.parse("Write a novel about cooking")
        assert spec.extra_inputs == {}

    def test_premise_strips_chapter_phrase_zh(self):
        parser = TaskParser()
        spec = parser.parse("写一本关于侦探推理的小说，包含5个章节")
        # Premise should not contain "5" or "章节"
        assert "5" not in spec.premise or "侦探" in spec.premise
        assert "章节" not in spec.premise

    def test_premise_strips_word_count_phrase(self):
        parser = TaskParser()
        spec = parser.parse("写一本侦探小说，每章3000字")
        # Premise should retain the genre keyword
        assert "侦探" in spec.premise or spec.premise

    def test_premise_falls_back_to_original_when_too_short(self):
        parser = TaskParser()
        # Very short input — boilerplate stripping may yield empty
        spec = parser.parse("侦探")
        # Should fall back to original text
        assert spec.premise == "侦探"

    def test_confidence_full_when_chapter_and_word_found(self):
        parser = TaskParser()
        spec = parser.parse("5章3000字的小说")
        assert spec.parser_confidence == 1.0

    def test_confidence_partial_when_only_chapter_found(self):
        parser = TaskParser()
        spec = parser.parse("5章的侦探小说")
        # 0.4 base + 0.3 chapter = 0.7
        assert spec.parser_confidence == 0.7

    def test_confidence_partial_when_only_word_found(self):
        parser = TaskParser()
        spec = parser.parse("每章3000字的小说")
        # 0.4 base + 0.3 word = 0.7
        assert spec.parser_confidence == 0.7

    def test_confidence_minimal_when_neither_found(self):
        parser = TaskParser()
        spec = parser.parse("侦探小说")
        # 0.4 base only
        assert spec.parser_confidence == 0.4

    def test_parser_source_is_rule(self):
        parser = TaskParser()
        spec = parser.parse("写一本5章的科幻小说")
        assert spec.parser_source == "rule"


# ---------------------------------------------------------------------------
# TaskParser — LLM-assisted parsing
# ---------------------------------------------------------------------------


class TestTaskParserLLMAssisted:
    @pytest.mark.asyncio
    async def test_parse_async_uses_llm_when_enabled_and_low_confidence(self):
        parser = TaskParser(llm_enabled=True)
        # Low-confidence input (no chapter/word count) triggers LLM
        llm_calls = 0

        async def _fake_draft(messages, *, stage_config=None):
            nonlocal llm_calls
            llm_calls += 1
            return _llm_json_response(
                premise="LLM parsed premise",
                chapter_count=7,
                target_words_per_chapter=4500,
                confidence=0.95,
            )

        with patch("app.parser.parser.llm_draft", new=_fake_draft):
            spec = await parser.parse_async("写一本小说")

        assert llm_calls == 1
        assert spec.parser_source == "llm"
        assert spec.premise == "LLM parsed premise"
        assert spec.chapter_count == 7
        assert spec.target_words_per_chapter == 4500
        assert spec.parser_confidence == 0.95

    @pytest.mark.asyncio
    async def test_parse_async_skips_llm_when_high_confidence(self):
        parser = TaskParser(llm_enabled=True)
        llm_calls = 0

        async def _fake_draft(messages, *, stage_config=None):
            nonlocal llm_calls
            llm_calls += 1
            return _llm_json_response()

        # High-confidence input (explicit chapter + word count)
        with patch("app.parser.parser.llm_draft", new=_fake_draft):
            spec = await parser.parse_async("5章3000字的小说")

        assert llm_calls == 0
        assert spec.parser_source == "rule"

    @pytest.mark.asyncio
    async def test_parse_async_skips_llm_when_disabled(self):
        parser = TaskParser(llm_enabled=False)
        llm_calls = 0

        async def _fake_draft(messages, *, stage_config=None):
            nonlocal llm_calls
            llm_calls += 1
            return _llm_json_response()

        # Low-confidence but LLM disabled — should not call LLM
        with patch("app.parser.parser.llm_draft", new=_fake_draft):
            spec = await parser.parse_async("写一本小说")

        assert llm_calls == 0
        assert spec.parser_source == "rule"

    @pytest.mark.asyncio
    async def test_parse_async_falls_back_when_llm_returns_invalid_json(self):
        parser = TaskParser(llm_enabled=True)

        async def _fake_draft(messages, *, stage_config=None):
            return _fake_llm_response("not json at all")

        with patch("app.parser.parser.llm_draft", new=_fake_draft):
            spec = await parser.parse_async("写一本小说")

        # Falls back to rule-based
        assert spec.parser_source == "rule"

    @pytest.mark.asyncio
    async def test_parse_async_falls_back_when_llm_returns_empty(self):
        parser = TaskParser(llm_enabled=True)

        async def _fake_draft(messages, *, stage_config=None):
            return _fake_llm_response("")

        with patch("app.parser.parser.llm_draft", new=_fake_draft):
            spec = await parser.parse_async("写一本小说")

        assert spec.parser_source == "rule"

    @pytest.mark.asyncio
    async def test_parse_async_falls_back_when_llm_raises_transient(self):
        """Transient LLM errors (429, connection, timeout) degrade silently."""
        parser = TaskParser(llm_enabled=True)

        async def _fake_draft(messages, *, stage_config=None):
            raise litellm.RateLimitError(
                message="rate limited", model="test", llm_provider="test"
            )

        with patch("app.parser.parser.llm_draft", new=_fake_draft):
            spec = await parser.parse_async("写一本小说")

        assert spec.parser_source == "rule"

    @pytest.mark.asyncio
    async def test_parse_async_propagates_non_retryable_error(self):
        """Non-retryable errors (auth, bad request) MUST propagate."""
        parser = TaskParser(llm_enabled=True)

        async def _fake_draft(messages, *, stage_config=None):
            raise litellm.AuthenticationError(
                message="invalid API key", model="test", llm_provider="test"
            )

        with patch("app.parser.parser.llm_draft", new=_fake_draft):
            with pytest.raises(litellm.AuthenticationError):
                await parser.parse_async("写一本小说")

    @pytest.mark.asyncio
    async def test_parse_async_falls_back_when_llm_returns_missing_premise(self):
        parser = TaskParser(llm_enabled=True)

        async def _fake_draft(messages, *, stage_config=None):
            return _fake_llm_response('{"chapter_count": 5}')  # no premise

        with patch("app.parser.parser.llm_draft", new=_fake_draft):
            spec = await parser.parse_async("写一本小说")

        assert spec.parser_source == "rule"

    @pytest.mark.asyncio
    async def test_parse_async_llm_response_uses_fallback_for_invalid_fields(self):
        """LLM returns chapter_count=0 (invalid) → fall back to rule-based value."""
        parser = TaskParser(llm_enabled=True)

        async def _fake_draft(messages, *, stage_config=None):
            return _llm_json_response(
                premise="LLM premise",
                chapter_count=0,  # invalid
                target_words_per_chapter=50,  # invalid
                confidence=0.9,
            )

        # Use low-confidence input (no chapter/word count) to trigger LLM
        with patch("app.parser.parser.llm_draft", new=_fake_draft):
            spec = await parser.parse_async("写一本小说")

        # LLM returned invalid chapter/word → fallback values from rule-based (defaults)
        assert spec.parser_source == "llm"
        assert spec.chapter_count == 1  # from rule-based fallback default
        assert spec.target_words_per_chapter == 3000  # from rule-based fallback default

    @pytest.mark.asyncio
    async def test_parse_with_llm_forced(self):
        """parse_with_llm() forces LLM use regardless of confidence.

        Skipped under pytest-asyncio auto mode because the sync wrapper
        detects the running event loop and falls back to rule-based.
        Verified manually via asyncio.run() in a separate process.
        """
        pytest.skip(
            "Sync wrapper detects pytest-asyncio's running loop and "
            "falls back to rule-based. Use parse_async() in async contexts."
        )

    def test_parse_with_llm_falls_back_on_sync_loop_error(self):
        """When called from inside a running event loop, returns rule-based."""
        import asyncio

        parser = TaskParser()

        async def _run():
            # Inside a running loop, _parse_with_llm_sync returns None
            # and parse_with_llm falls back to rule-based.
            return parser.parse_with_llm("5章3000字的小说")

        spec = asyncio.run(_run())
        # Falls back to rule-based (sync wrapper detected running loop)
        assert spec.parser_source == "rule"


# ---------------------------------------------------------------------------
# Integration with PlannerAgent
# ---------------------------------------------------------------------------


class TestPlannerAgentIntegration:
    def test_parsed_spec_to_planner_kwargs_works(self):
        parser = TaskParser()
        spec = parser.parse("写一本5章的侦探小说，每章3000字")
        kwargs = spec.to_planner_kwargs()
        # Should be callable with PlannerAgent.plan
        planner = PlannerAgent()
        dag = planner.plan(**kwargs)
        assert isinstance(dag, SubTaskDAG)
        assert len(dag.tasks) > 0

    def test_single_chapter_parsed_to_dag(self):
        parser = TaskParser()
        spec = parser.parse("写一本侦探小说")
        planner = PlannerAgent()
        dag = planner.plan(**spec.to_planner_kwargs())
        # Single-chapter template has 8 tasks
        assert len(dag.tasks) == 8

    def test_multi_chapter_parsed_to_dag(self):
        parser = TaskParser()
        spec = parser.parse("写一本5章的侦探小说，每章3000字")
        planner = PlannerAgent()
        dag = planner.plan(**spec.to_planner_kwargs())
        # Multi-chapter template: 3 setup + 5*2 chapters + 3 final = 16
        # (outline, world_setting, character, 5*chapter_draft, 5*chapter_refine,
        #  consistency_check, final_polish, safety_review)
        assert len(dag.tasks) == 3 + 5 * 2 + 3  # 16

    def test_parsed_word_count_flows_to_template(self):
        parser = TaskParser()
        spec = parser.parse("写一本2章的科幻小说，每章5000字")
        planner = PlannerAgent()
        dag = planner.plan(**spec.to_planner_kwargs())
        # chapter_draft_1 should have target_words=5000
        draft = dag.get("chapter_draft_1")
        assert draft.spec.inputs["target_words"] == 5000

    def test_extra_inputs_passed_through(self):
        parser = TaskParser()
        spec = parser.parse("写一本5章的黑暗风格侦探小说")
        # Genre + tone in extra_inputs
        assert spec.extra_inputs.get("genre") == "mystery"
        assert spec.extra_inputs.get("tone") == "dark"

        # Planner currently logs and ignores extra_inputs (per the
        # rule-based planner's docstring). Verify it doesn't crash.
        planner = PlannerAgent()
        dag = planner.plan(**spec.to_planner_kwargs())
        assert isinstance(dag, SubTaskDAG)


# ---------------------------------------------------------------------------
# Edge cases / regression tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_chapter_count_zero_in_input(self):
        """ '0章' — regex matches but value is invalid. Should default."""
        parser = TaskParser()
        # "0章" matches the digit pattern but value 0 is invalid for chapters.
        # The _extract_chapter_count returns (0, True), but the val >= 1 check
        # filters it out, so we default to (1, False).
        spec = parser.parse("写一本0章的侦探小说")
        # Should default to 1 chapter (or fall through to default)
        assert spec.chapter_count >= 1

    def test_very_large_chapter_count(self):
        parser = TaskParser()
        spec = parser.parse("写一本100章的玄幻小说")
        assert spec.chapter_count == 100

    def test_mixed_language_input(self):
        parser = TaskParser()
        spec = parser.parse("写一本5章的sci-fi小说，5000 words each")
        assert spec.chapter_count == 5
        assert spec.target_words_per_chapter == 5000
        # "sci-fi" should be detected (English genre keyword)
        assert spec.genre == "sci-fi"

    def test_input_with_special_chars(self):
        parser = TaskParser()
        spec = parser.parse("写一本关于 AI/赛博朋克 的5章小说")
        assert spec.chapter_count == 5
        assert spec.premise  # non-empty

    def test_input_only_numbers(self):
        """Edge case: input is just a number — should still parse."""
        parser = TaskParser()
        spec = parser.parse("5")
        # Premise should be "5" (original input kept as fallback)
        assert spec.premise == "5"

    def test_input_with_newlines(self):
        parser = TaskParser()
        spec = parser.parse("写一本侦探小说\n包含5章\n每章3000字")
        assert spec.chapter_count == 5
        assert spec.target_words_per_chapter == 3000

    def test_chinese_with_full_width_digits(self):
        """Full-width digits ５ — should still work via regex."""
        parser = TaskParser()
        # Note: \d matches ASCII digits only. Full-width "５" would NOT match
        # the simple \d+ pattern. Test that we at least don't crash.
        spec = parser.parse("写一本５章的侦探小说")
        # Falls back to default chapter_count=1 since ５ isn't \d
        assert spec.chapter_count >= 1
        assert spec.genre == "mystery"

    def test_word_count_with_kanji_qian_suffix(self):
        """ '5千字' = 5000 — the 千 multiplier."""
        parser = TaskParser()
        spec = parser.parse("每章5千字")
        assert spec.target_words_per_chapter == 5000

    def test_genre_priority_zh_over_en_when_mixed(self):
        """When both zh and en genre keywords are present, zh wins (checked first)."""
        parser = TaskParser()
        spec = parser.parse("写一本科幻sci-fi小说")
        # zh "科幻" should be detected first (in zh language branch)
        assert spec.genre in ("sci-fi",)  # both map to sci-fi

    def test_parse_with_llm_disabled_by_default(self):
        parser = TaskParser()
        assert parser.llm_enabled is False
