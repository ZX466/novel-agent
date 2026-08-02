"""TaskParser — converts natural-language input into ParsedTaskSpec.

Two parsing modes:
  1. Rule-based (default): deterministic regex extraction of
     chapter count, word count, genre, language. Fast and predictable.
     Returns parser_confidence = 1.0 when explicit numbers are found,
     lower when defaults are used.
  2. LLM-assisted (optional): when rule-based extraction yields low
     confidence or ambiguous results, calls an LLM (via
     app.llm.clients.draft) to interpret the input. The LLM is asked
     to respond with a strict JSON spec — failures fall back to the
     rule-based result.

Supported natural-language patterns (rule-based):
  - Chapter count: "5章", "5 chapters", "五章", "5个章节"
  - Word count:    "3000字", "3000 words", "3000字每章",
                   "每章3000字", "3000 words per chapter"
  - Genre hints:   "侦探", "科幻", "悬疑", "玄幻", "言情",
                   "sci-fi", "fantasy", "mystery", "romance"
  - Language:      auto-detected by CJK character ratio

Examples that parse cleanly:
  - "写一本关于侦探推理的小说，包含5个章节，每章约3000字"
    → premise="关于侦探推理的小说", chapter_count=5, words=3000,
      genre="侦探", language="zh"
  - "Write a 3-chapter sci-fi novel, 5000 words each"
    → premise="sci-fi novel", chapter_count=3, words=5000,
      genre="sci-fi", language="en"
  - "侦探小说"
    → premise="侦探小说", chapter_count=1, words=3000,
      genre="侦探", language="zh", confidence=0.5 (defaults used)

Integration with PlannerAgent:
    spec = TaskParser().parse("写一本5章的侦探小说")
    dag = PlannerAgent().plan(**spec.to_planner_kwargs())
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import litellm

from app.llm import draft as llm_draft
from app.parser.spec import ParsedTaskSpec

logger = logging.getLogger(__name__)


# Errors that are transient (infra-level) — safe to fall back to rule-based
# parsing after _call_with_retry has exhausted its own retries.
# Non-retryable errors (AuthenticationError, BadRequestError, NotFoundError)
# MUST propagate so the caller sees the misconfiguration.
_RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.InternalServerError,
    TimeoutError,      # raised by _call_with_retry on asyncio.TimeoutError
)


# ---------------------------------------------------------------------------
# Genre dictionaries — extend as needed
# ---------------------------------------------------------------------------

_GENRE_ZH = {
    "侦探": "mystery",
    "推理": "mystery",
    "悬疑": "suspense",
    "科幻": "sci-fi",
    "玄幻": "fantasy",
    "奇幻": "fantasy",
    "武侠": "wuxia",
    "仙侠": "xianxia",
    "言情": "romance",
    "爱情": "romance",
    "历史": "historical",
    "都市": "urban",
    "现实": "realistic",
    "恐怖": "horror",
    "惊悚": "thriller",
    "战争": "war",
    "冒险": "adventure",
    "喜剧": "comedy",
    "青春": "young_adult",
}

_GENRE_EN = {
    "sci-fi": "sci-fi",
    "science fiction": "sci-fi",
    "fantasy": "fantasy",
    "mystery": "mystery",
    "romance": "romance",
    "thriller": "thriller",
    "horror": "horror",
    "historical": "historical",
    "wuxia": "wuxia",
    "adventure": "adventure",
    "comedy": "comedy",
    "young adult": "young_adult",
}

# Tone keywords (broad — match anywhere in input)
_TONE_KEYWORDS = {
    "dark": ["dark", "黑暗", "阴郁"],
    "light": ["light", "轻松", "明亮"],
    "comedic": ["comedy", "comedic", "喜剧", "搞笑"],
    "serious": ["serious", "严肃"],
    "epic": ["epic", "史诗"],
    "tragic": ["tragic", "tragedy", "悲剧"],
    "hopeful": ["hopeful", "希望", "温暖"],
}


# ---------------------------------------------------------------------------
# Regex patterns — chapter / word count extraction
# ---------------------------------------------------------------------------

# Chinese patterns: "5章", "五章", "5个章节", "共5章"
_CHAPTER_PATTERNS_ZH = [
    re.compile(r"(\d+)\s*[个]?[章章节]"),           # 5章, 5章节, 5个章节
    re.compile(r"([零一二三四五六七八九十百]+)\s*[个]?[章章节]"),  # 五章
]

# English patterns: "5 chapters", "5-chapter"
_CHAPTER_PATTERNS_EN = [
    re.compile(r"(\d+)\s*[-\s]*chapter", re.IGNORECASE),
]

# Chinese word-count patterns: "3000字", "3000字每章", "每章3000字"
_WORD_COUNT_PATTERNS_ZH = [
    re.compile(r"(\d+)\s*[千]?\s*字\s*(?:每章|/章)?"),  # 3000字, 3000字每章
    re.compile(r"每章\s*(\d+)\s*[千]?\s*字"),           # 每章3000字
]

# English word count: "3000 words", "3000 words per chapter", "3000-word"
_WORD_COUNT_PATTERNS_EN = [
    re.compile(r"(\d+)\s*[-\s]*words?", re.IGNORECASE),
]

# Chinese numeral map for "五章" → 5
_ZH_NUMERAL_MAP = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_ZH_NUMERAL_TENS = re.compile(r"([零一二三四五六七八九十]+)")


def _zh_numeral_to_int(s: str) -> int | None:
    """Convert a Chinese numeral string to int. Returns None on failure."""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    # Simple cases: "十" = 10, "十一" = 11, "二十" = 20, "二十三" = 23
    if s == "十":
        return 10
    if s.startswith("十"):
        rest = s[1:]
        return 10 + (_ZH_NUMERAL_MAP.get(rest, 0) if rest else 0)
    if s.endswith("十"):
        head = s[:-1]
        return (_ZH_NUMERAL_MAP.get(head, 0) if head else 1) * 10
    if "十" in s:
        parts = s.split("十")
        head_val = _ZH_NUMERAL_MAP.get(parts[0], 0) if parts[0] else 1
        tail_val = _ZH_NUMERAL_MAP.get(parts[1], 0) if parts[1] else 0
        return head_val * 10 + tail_val
    # Multi-digit Chinese numeral (no "十"): "一二三" = 123
    try:
        return int("".join(str(_ZH_NUMERAL_MAP[c]) for c in s))
    except (KeyError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def _detect_language(text: str) -> str:
    """Detect 'zh' or 'en' based on CJK character ratio.

    Returns "zh" if more than 30% of the characters are CJK, else "en".
    Threshold of 30% allows mixed-input like "写一本sci-fi小说" to still
    count as Chinese (the premise's primary language).
    """
    if not text:
        return "zh"
    cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return "zh" if cjk_count / len(text) > 0.3 else "en"


# ---------------------------------------------------------------------------
# TaskParser
# ---------------------------------------------------------------------------


class TaskParser:
    """Parses natural-language novel requests into ParsedTaskSpec.

    Two modes:
      - `parse()` (default): rule-based extraction. Fast, deterministic.
        Returns parser_confidence = 1.0 when explicit numbers are found,
        lower when defaults are used.
      - `parse_with_llm()` (optional): rule-based first, then optionally
        calls an LLM to refine ambiguous fields. The LLM is asked to
        respond with a strict JSON spec; on failure, the rule-based
        result is returned.
    """

    def __init__(self, *, llm_enabled: bool = False) -> None:
        """Construct a parser.

        Args:
            llm_enabled: when True, `parse()` automatically falls back
                to LLM refinement when rule-based confidence is low
                (< 0.6). When False (default), `parse()` is purely
                rule-based. `parse_with_llm()` always uses LLM.
        """
        self.llm_enabled = llm_enabled

    def parse(self, text: str) -> ParsedTaskSpec:
        """Parse natural-language text into a ParsedTaskSpec.

        Rule-based extraction. When llm_enabled and confidence is low
        (< 0.6), falls back to LLM refinement (sync call to draft LLM).
        Transient infra errors (429, connection, timeout, 5xx) degrade
        silently to rule-based results; non-retryable errors (401, 403,
        400, 404) propagate so the caller sees the misconfiguration.
        """
        spec, confidence = self._parse_rules(text)
        if self.llm_enabled and confidence < 0.6:
            try:
                llm_spec = self._parse_with_llm_sync(text, fallback=spec)
                if llm_spec is not None:
                    return llm_spec
            except _RETRYABLE_ERRORS as e:
                logger.warning("TaskParser LLM fallback failed (transient): %r", e)
            # Non-retryable errors (Auth, BadRequest, NotFound) propagate.
        return spec

    async def parse_async(self, text: str) -> ParsedTaskSpec:
        """Async version of parse(). Uses LLM via await when needed.

        Transient infra errors degrade silently to rule-based results;
        non-retryable errors propagate.
        """
        spec, confidence = self._parse_rules(text)
        if self.llm_enabled and confidence < 0.6:
            try:
                llm_spec = await self._parse_with_llm(text, fallback=spec)
                if llm_spec is not None:
                    return llm_spec
            except _RETRYABLE_ERRORS as e:
                logger.warning("TaskParser LLM fallback failed (transient): %r", e)
            # Non-retryable errors (Auth, BadRequest, NotFound) propagate.
        return spec

    def parse_with_llm(self, text: str) -> ParsedTaskSpec:
        """Force LLM-assisted parsing (rule-based first, LLM refines).

        Transient infra errors degrade silently to rule-based results;
        non-retryable errors propagate.
        """
        spec, _ = self._parse_rules(text)
        try:
            llm_spec = self._parse_with_llm_sync(text, fallback=spec)
            if llm_spec is not None:
                return llm_spec
        except _RETRYABLE_ERRORS as e:
            logger.warning("TaskParser LLM parse failed (transient): %r", e)
        # Non-retryable errors (Auth, BadRequest, NotFound) propagate.
        return spec

    # --- rule-based extraction -------------------------------------------

    def _parse_rules(self, text: str) -> tuple[ParsedTaskSpec, float]:
        """Extract ParsedTaskSpec via regex. Returns (spec, confidence).

        Confidence is 1.0 when both chapter_count and word_count are
        explicitly extracted, 0.7 when only one is, 0.4 when neither
        (defaults used).
        """
        if not text or not text.strip():
            raise ValueError("parse input must be non-empty")
        text = text.strip()
        language = _detect_language(text)

        chapter_count, chapter_found = self._extract_chapter_count(text, language)
        word_count, word_found = self._extract_word_count(text, language)
        genre = self._extract_genre(text, language)
        tone = self._extract_tone(text)

        premise = self._extract_premise(text, language)

        # Confidence scoring
        confidence = 0.4  # base: premise only
        if chapter_found:
            confidence += 0.3
        if word_found:
            confidence += 0.3

        extra_inputs: dict[str, Any] = {}
        if genre:
            extra_inputs["genre"] = genre
        if tone:
            extra_inputs["tone"] = tone

        spec = ParsedTaskSpec(
            premise=premise,
            chapter_count=chapter_count,
            target_words_per_chapter=word_count,
            genre=genre,
            tone=tone,
            language=language,
            extra_inputs=extra_inputs,
            parser_source="rule",
            parser_confidence=round(confidence, 2),
        )
        return spec, confidence

    def _extract_chapter_count(
        self, text: str, language: str
    ) -> tuple[int, bool]:
        """Extract chapter count. Returns (count, found)."""
        patterns = (
            _CHAPTER_PATTERNS_ZH + _CHAPTER_PATTERNS_EN
            if language == "zh"
            else _CHAPTER_PATTERNS_EN + _CHAPTER_PATTERNS_ZH
        )
        for pat in patterns:
            m = pat.search(text)
            if m:
                raw = m.group(1)
                val = _zh_numeral_to_int(raw) if not raw.isdigit() else int(raw)
                if val is not None and val >= 1:
                    return val, True
        return 1, False  # default

    def _extract_word_count(
        self, text: str, language: str
    ) -> tuple[int, bool]:
        """Extract target words per chapter. Returns (count, found)."""
        patterns = (
            _WORD_COUNT_PATTERNS_ZH + _WORD_COUNT_PATTERNS_EN
            if language == "zh"
            else _WORD_COUNT_PATTERNS_EN + _WORD_COUNT_PATTERNS_ZH
        )
        for pat in patterns:
            m = pat.search(text)
            if m:
                try:
                    val = int(m.group(1))
                except ValueError:
                    continue
                # Handle "千" suffix BEFORE sanity check — e.g. "5千字" = 5000
                full_match = m.group(0)
                if "千" in full_match and val < 100:
                    val *= 1000
                if val >= 100:  # sanity check after multiplier
                    return val, True
        return 3000, False  # default

    def _extract_genre(self, text: str, language: str) -> str | None:
        """Extract genre hint. Returns None when no genre detected."""
        text_lower = text.lower()
        # Try Chinese genres first when language is zh
        if language == "zh":
            for keyword, genre in _GENRE_ZH.items():
                if keyword in text:
                    return genre
        # English genres
        for keyword, genre in _GENRE_EN.items():
            if keyword in text_lower:
                return genre
        # Cross-language: even zh input may contain "sci-fi"
        for keyword, genre in _GENRE_EN.items():
            if keyword in text_lower:
                return genre
        return None

    def _extract_tone(self, text: str) -> str | None:
        """Extract tone hint. Returns None when no tone detected."""
        text_lower = text.lower()
        for tone, keywords in _TONE_KEYWORDS.items():
            for kw in keywords:
                if kw in text or kw in text_lower:
                    return tone
        return None

    def _extract_premise(self, text: str, language: str) -> str:
        """Extract the premise text.

        Heuristic: strip out chapter-count / word-count phrases, then
        use the remaining text as the premise. If the result is empty
        or too short, fall back to the original text.

        Examples:
          - "写一本关于侦探推理的小说，包含5个章节，每章约3000字"
            → "关于侦探推理的小说"
          - "Write a 3-chapter sci-fi novel, 5000 words each"
            → "Write a sci-fi novel"
        """
        result = text
        # Strip chapter-count phrases
        for pat in _CHAPTER_PATTERNS_ZH + _CHAPTER_PATTERNS_EN:
            result = pat.sub(" ", result)
        # Strip word-count phrases
        for pat in _WORD_COUNT_PATTERNS_ZH + _WORD_COUNT_PATTERNS_EN:
            result = pat.sub(" ", result)
        # Strip common boilerplate
        boilerplate_zh = [
            "写一本", "写一部", "创作一本", "创作一部",
            "包含", "共", "约", "的小说", "小说",
        ]
        boilerplate_en = [
            "write a", "write an", "create a", "create an",
            "novel", "story",
        ]
        for b in boilerplate_zh:
            result = result.replace(b, "")
        if language == "en":
            for b in boilerplate_en:
                result = re.sub(re.escape(b), " ", result, flags=re.IGNORECASE)
        # Collapse whitespace
        result = re.sub(r"\s+", " ", result).strip(" ，,。.、的")
        # If we stripped too much, fall back to original text
        if len(result) < 4:
            return text
        return result

    # --- LLM-assisted parsing -------------------------------------------

    _LLM_SYSTEM_PROMPT = (
        "You are a task parser for a novel-writing system. Given a "
        "natural-language novel request, extract structured fields. "
        "Respond with ONLY a JSON object with these keys: "
        '"premise" (string, the core story premise), '
        '"chapter_count" (int, >=1, default 1), '
        '"target_words_per_chapter" (int, >=100, default 3000), '
        '"genre" (string or null), '
        '"tone" (string or null), '
        '"language" ("zh" or "en"), '
        '"confidence" (float 0.0-1.0). '
        "No prose, no markdown fences, ONLY the JSON object."
    )

    def _build_llm_messages(self, text: str, fallback: ParsedTaskSpec) -> list[dict]:
        fallback_json = json.dumps(fallback.to_dict(), ensure_ascii=False)
        user_prompt = (
            f"User input: {text}\n\n"
            f"Rule-based fallback (use as defaults when LLM is unsure):\n"
            f"{fallback_json}\n\n"
            "Extract the structured spec. Respond with ONLY the JSON object."
        )
        return [
            {"role": "system", "content": self._LLM_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    def _parse_llm_response(
        self, raw: str, fallback: ParsedTaskSpec
    ) -> ParsedTaskSpec | None:
        """Parse LLM JSON response. Returns None on parse failure."""
        if not raw:
            return None
        cleaned = re.sub(
            r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE
        ).strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        premise = str(data.get("premise", "")).strip()
        if not premise:
            return None
        try:
            chapter_count = int(data.get("chapter_count", fallback.chapter_count))
            word_count = int(
                data.get("target_words_per_chapter", fallback.target_words_per_chapter)
            )
        except (TypeError, ValueError):
            return None
        if chapter_count < 1:
            chapter_count = fallback.chapter_count
        if word_count < 100:
            word_count = fallback.target_words_per_chapter
        genre = data.get("genre")
        if not isinstance(genre, str) or not genre:
            genre = fallback.genre
        tone = data.get("tone")
        if not isinstance(tone, str) or not tone:
            tone = fallback.tone
        language = str(data.get("language", fallback.language))
        if language not in ("zh", "en"):
            language = fallback.language
        try:
            confidence = float(data.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        confidence = max(0.0, min(1.0, confidence))

        extra_inputs: dict[str, Any] = {}
        if genre:
            extra_inputs["genre"] = genre
        if tone:
            extra_inputs["tone"] = tone

        return ParsedTaskSpec(
            premise=premise,
            chapter_count=chapter_count,
            target_words_per_chapter=word_count,
            genre=genre,
            tone=tone,
            language=language,
            extra_inputs=extra_inputs,
            parser_source="llm",
            parser_confidence=round(confidence, 2),
        )

    async def _parse_with_llm(
        self, text: str, fallback: ParsedTaskSpec
    ) -> ParsedTaskSpec | None:
        """Async LLM-assisted parsing. Returns None on failure."""
        messages = self._build_llm_messages(text, fallback)
        resp = await llm_draft(messages)
        raw = resp.choices[0].message.content or ""
        return self._parse_llm_response(raw, fallback)

    def _parse_with_llm_sync(
        self, text: str, fallback: ParsedTaskSpec
    ) -> ParsedTaskSpec | None:
        """Sync wrapper around the async LLM call.

        Used by `parse()` and `parse_with_llm()` — runs the coroutine
        via asyncio.run. Not safe to call from inside a running event
        loop (use `parse_async()` instead).
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                logger.warning(
                    "TaskParser._parse_with_llm_sync called from running "
                    "event loop — returning rule-based fallback"
                )
                return None
        except RuntimeError:
            pass
        return asyncio.run(self._parse_with_llm(text, fallback))
