"""Setting-consistency service (R5-3 设定一致性哨兵).

Scans a draft against the novel's stored character settings and records
"suspected contradiction" rows with supporting evidence for one-click
navigation back to the rework point.

Pipeline (all deterministic + unit-testable; RAG is mocked in tests):
  1. find which characters the draft mentions (longest-name matching)
  2. extract numeric facts (value + unit) from the draft and from each
     character's stored profile (attributes / description / arc_summary)
  3. compare per canonical unit: same unit, different value -> conflict
  4. attach the best RAG evidence hit (reuses the 5-collection retrieval)
  5. persist one `ConsistencyCheck` row per finding (verdict pass|conflict)

The numeric comparison is deliberately rule-based (not LLM) so results are
deterministic and cheap. Semantic nuance (personality shifts, relationship
drift) is surfaced via the evidence snippet for the author to judge.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.chapter import Chapter
from app.models.consistency_check import ConsistencyCheck
from app.schemas.chat import StageConfig
from app.services.retrieval import retrieve

logger = logging.getLogger(__name__)

# --- numeric fact extraction -------------------------------------------------

# Multi-character units must appear before their prefixes so alternation
# matches greedily (Python `re` is leftmost-first, not longest-first).
_NUMBER_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(万|千)?\s*"
    r"(厘米|小时|分钟|千克|公斤|公里|千米|年份|岁|年|月|日|天|时|分|秒|米|斤|级|章|次|个|元|%|％)"
)

# Canonicalise equivalent units so "1 千克" and "2 公斤" compare equal.
_UNIT_NORMALIZE = {
    "千克": "公斤",
    "公里": "公里",
    "千米": "公里",
    "％": "%",
}

# Friendly label used in the human-readable conflict message.
_UNIT_LABEL = {
    "岁": "年龄",
    "公斤": "体重",
    "斤": "体重",
}

# Map structured attribute keys -> canonical unit for profile fact building.
_UNIT_BY_KEY = {
    "age": "岁",
    "年龄": "岁",
    "height": "厘米",
    "身高": "厘米",
    "weight": "公斤",
    "体重": "公斤",
}

_SNIPPET_LEN = 200


def normalize_unit(unit: str) -> str:
    return _UNIT_NORMALIZE.get(unit, unit)


def extract_numeric_facts(text: str) -> list[tuple[float, str]]:
    """Return [(value, canonical_unit)] for every numeric fact in `text`.

    Supports decimal values and Chinese 万/千 scaling ("1.5万" -> 15000).
    """
    facts: list[tuple[float, str]] = []
    for match in _NUMBER_UNIT_RE.finditer(text):
        value = float(match.group(1))
        scale = match.group(2)
        if scale == "万":
            value *= 10_000
        elif scale == "千":
            value *= 1_000
        unit = normalize_unit(match.group(3))
        facts.append((value, unit))
    return facts


def _profile_fact_text(c: Character) -> str:
    """Build the fact-bearing text of a character profile.

    Structured attributes with known numeric keys are rendered with their
    unit so the generic extractor can compare them against draft facts.
    """
    parts: list[str] = []
    if c.description:
        parts.append(c.description)
    if c.arc_summary:
        parts.append(c.arc_summary)
    if c.attributes:
        for key, value in c.attributes.items():
            unit = _UNIT_BY_KEY.get(str(key).lower())
            if isinstance(value, (int, float)) and unit:
                parts.append(f"{value}{unit}")
    return "\n".join(p for p in parts if p)


def detect_fact_conflicts(
    draft_facts: list[tuple[float, str]],
    profile_facts: list[tuple[float, str]],
) -> list[str]:
    """Compare draft vs stored facts by canonical unit.

    Returns human-readable conflict messages for every draft fact whose
    value differs from ALL stored values of the same unit.
    """
    by_unit: dict[str, list[float]] = {}
    for value, unit in profile_facts:
        by_unit.setdefault(unit, []).append(value)

    conflicts: list[str] = []
    for value, unit in draft_facts:
        stored = by_unit.get(unit)
        if stored and not any(abs(s - value) <= 1e-9 for s in stored):
            label = _UNIT_LABEL.get(unit, unit)
            conflicts.append(
                f"{label}: 草稿 {value:g}{unit} 与设定 {stored[0]:g}{unit} 不一致"
            )
    return conflicts


# --- character mention extraction --------------------------------------------


def extract_mentioned_characters(
    text: str,
    characters: list[Character],
    min_len: int = 2,
) -> list[Character]:
    """Return the characters whose names appear in the draft, in profile order.

    Longest names are matched first so "李小明" wins over "小明", and a
    matched occurrence is consumed so shorter overlapping names do not
    re-match inside it. Names shorter than `min_len` are ignored to avoid
    single-character noise.
    """
    matched: list[Character] = []
    working = text
    for c in sorted(characters, key=lambda x: len(x.name), reverse=True):
        name = c.name
        if len(name) < min_len or not name or name not in working:
            continue
        working = working.replace(name, " " * len(name))
        matched.append(c)
    # Restore profile order (sorted above breaks it).
    order = {id(c): i for i, c in enumerate(characters)}
    matched.sort(key=lambda c: order[id(c)])
    return matched


# --- evidence -----------------------------------------------------------------


def _snippet_from_hit(hit) -> str:
    """Extract a short displayable snippet from a retrieval hit's payload."""
    payload = hit.payload
    for key in ("summary", "description", "content_text", "content", "title", "name"):
        text = payload.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()[:_SNIPPET_LEN]
    return ""


async def _collect_evidence(
    session: AsyncSession,
    *,
    novel_id: int,
    character_name: str,
    query: str,
    stage_config: StageConfig | None,
    k: int,
) -> tuple[str, int, str] | None:
    """Reuse the 5-collection RAG retrieval to find the best evidence hit.

    Prefers a direct character-profile match, then any hit whose payload
    text mentions the character. Returns (evidence_type, evidence_id,
    snippet) or None when nothing relevant is found.
    """
    hits = await retrieve(
        session, query, novel_id=novel_id,
        k_per_collection=k, stage_config=stage_config,
    )
    for hit in hits:
        if hit.entity_type == "character" and hit.payload.get("name") == character_name:
            snippet = _snippet_from_hit(hit) or character_name
            return (hit.entity_type, hit.entity_id, snippet)
    for hit in hits:
        snippet = _snippet_from_hit(hit)
        if character_name in snippet:
            return (hit.entity_type, hit.entity_id, snippet)
    return None


# --- orchestration -------------------------------------------------------------


async def _chapter_text(session: AsyncSession, chapter_id: int) -> str:
    ch = await session.scalar(select(Chapter).where(Chapter.id == chapter_id))
    if ch is None:
        raise ValueError("章节不存在")
    return ch.content_text or ""


async def _load_characters(session: AsyncSession, novel_id: int) -> list[Character]:
    result = await session.execute(
        select(Character).where(Character.novel_id == novel_id)
    )
    return list(result.scalars().all())


async def check_draft(
    session: AsyncSession,
    *,
    novel_id: int,
    owner_key_hash: str = "",
    chapter_id: int | None = None,
    content_text: str | None = None,
    stage_config: StageConfig | None = None,
    k: int = 5,
) -> list[ConsistencyCheck]:
    """Scan a draft for setting contradictions and persist the findings.

    `content_text` takes precedence; when absent and `chapter_id` is given
    the stored chapter content is used. Returns the created rows.
    """
    text = (content_text or "").strip()
    if not text and chapter_id is not None:
        text = await _chapter_text(session, chapter_id)
    text = text.strip()
    if not text:
        return []

    characters = await _load_characters(session, novel_id)
    mentioned = extract_mentioned_characters(text, characters)
    if not mentioned:
        return []

    draft_facts = extract_numeric_facts(text)
    created: list[ConsistencyCheck] = []

    for c in mentioned:
        profile_facts = extract_numeric_facts(_profile_fact_text(c))
        conflicts = detect_fact_conflicts(draft_facts, profile_facts)
        evidence = await _collect_evidence(
            session, novel_id=novel_id, character_name=c.name,
            query=text, stage_config=stage_config, k=k,
        )

        if conflicts:
            for detail in conflicts:
                created.append(
                    ConsistencyCheck(
                        novel_id=novel_id, owner_key_hash=owner_key_hash,
                        chapter_id=chapter_id, target_type="character",
                        target_id=c.id, target_name=c.name,
                        verdict="conflict", detail=detail,
                        evidence_type=evidence[0] if evidence else None,
                        evidence_id=evidence[1] if evidence else None,
                        evidence_snippet=evidence[2] if evidence else None,
                    )
                )
        elif evidence:
            created.append(
                ConsistencyCheck(
                    novel_id=novel_id, owner_key_hash=owner_key_hash,
                    chapter_id=chapter_id, target_type="character",
                    target_id=c.id, target_name=c.name,
                    verdict="pass", detail=f"{c.name} 未检出数值设定矛盾",
                    evidence_type=evidence[0], evidence_id=evidence[1],
                    evidence_snippet=evidence[2],
                )
            )

    if created:
        session.add_all(created)
        await session.commit()
        logger.info(
            "consistency: novel_id=%d checks=%d (conflict=%d)",
            novel_id, len(created),
            sum(1 for row in created if row.verdict == "conflict"),
        )
    return created


async def list_checks(
    session: AsyncSession,
    *,
    novel_id: int,
    owner_key_hash: str = "",
    chapter_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ConsistencyCheck], int]:
    """Return (items, total) for the novel's checks, newest first."""
    total_stmt = select(func.count(ConsistencyCheck.id)).where(
        ConsistencyCheck.novel_id == novel_id,
        ConsistencyCheck.owner_key_hash == owner_key_hash,
    )
    list_stmt = select(ConsistencyCheck).where(
        ConsistencyCheck.novel_id == novel_id,
        ConsistencyCheck.owner_key_hash == owner_key_hash,
    )
    if chapter_id is not None:
        total_stmt = total_stmt.where(ConsistencyCheck.chapter_id == chapter_id)
        list_stmt = list_stmt.where(ConsistencyCheck.chapter_id == chapter_id)
    total = await session.scalar(total_stmt)
    list_stmt = (
        list_stmt.order_by(ConsistencyCheck.created_at.desc(), ConsistencyCheck.id.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(list_stmt)
    return list(result.scalars().all()), int(total or 0)