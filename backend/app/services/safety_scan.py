"""交稿雷达 (R6-3) — pre-export safety preflight.

Only runs on demand (export click / manual button): scans the saved
chapters with the deterministic RuleEngine, masks PII evidence, and caches
the result keyed by (doc_id, content_hash) so repeated exports of unchanged
content cost nothing. It NEVER blocks saving or writing — findings are
advisory and the frontend lets the author ignore them and export anyway.
"""
from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.safety import RuleEngine, RuleResult
from app.services.chapter import list_chapters
from app.services.document import get_document

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_MAX_ENTRIES = 64
_MASKABLE_CATEGORIES = frozenset({"pii", "privacy"})


def compute_content_hash(sections: Iterable[tuple[str, str]]) -> str:
    """sha256 over (title, content) pairs — cheap change detector."""
    h = hashlib.sha256()
    for title, body in sections:
        h.update((title or "").encode("utf-8"))
        h.update(b"\x00")
        h.update((body or "").encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


def build_scan_text(chapters: Iterable) -> str:
    """Concatenate chapter titles + bodies for scanning (title line first)."""
    parts: list[str] = []
    for ch in chapters:
        title = getattr(ch, "title", "") or ""
        body = getattr(ch, "content_text", "") or ""
        parts.append(f"{title}\n{body}")
    return "\n".join(parts)


def _mask_evidence(category: str, sample: str) -> str:
    """Redact PII/privacy samples before returning them to the UI."""
    if category not in _MASKABLE_CATEGORIES or not sample:
        return sample
    if len(sample) <= 4:
        return sample[0] + "***"
    return sample[:3] + "*" * max(2, len(sample) - 5) + sample[-2:]


def _finding(rule_result: RuleResult, description: str) -> dict:
    return {
        "rule_name": rule_result.rule_name,
        "category": rule_result.category,
        "severity": rule_result.severity.name,
        "description": description,
        "count": len(rule_result.matches),
        "sample": _mask_evidence(rule_result.category, rule_result.evidence),
    }


def run_scan(
    text: str,
    *,
    max_chars: int | None = None,
    engine: RuleEngine | None = None,
) -> dict:
    """Run deterministic rules over text and return an advisory report.

    `max_chars` bounds cost on very long novels; the report marks
    `truncated=True` so the UI can say the scan covered a prefix only.
    """
    rule_engine = engine if engine is not None else RuleEngine()
    truncated = False
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    results = rule_engine.check(text)
    descriptions = {r.name: r.description for r in rule_engine.list_rules()}
    findings = [
        _finding(r, descriptions.get(r.rule_name, ""))
        for r in RuleEngine.matched_results(results)
    ]
    return {
        "truncated": truncated,
        "rules_checked": len(results),
        "summary": rule_engine.summarize(results),
        "findings": findings,
    }


class SafetyScanCache:
    """In-process report cache keyed by (doc_id, content_hash).

    A tiny LRU (OrderedDict) with a hard cap; entries expire naturally by
    eviction. Not persisted — repeat scans after a restart are allowed,
    keeping the cache simple and crash-safe.
    """

    def __init__(self, max_entries: int = _DEFAULT_CACHE_MAX_ENTRIES) -> None:
        self._max = max(1, int(max_entries))
        self._data: OrderedDict[tuple[int, str], dict] = OrderedDict()

    def get(self, doc_id: int, content_hash: str) -> dict | None:
        key = (doc_id, content_hash)
        entry = self._data.get(key)
        if entry is not None:
            self._data.move_to_end(key)
        return entry

    def put(self, doc_id: int, content_hash: str, report: dict) -> None:
        key = (doc_id, content_hash)
        self._data[key] = report
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


# Module-level cache: one process, one cache.
_scan_cache = SafetyScanCache()


def clear_scan_cache() -> None:
    """Exposed for tests / admin tooling."""
    _scan_cache.clear()


async def scan_document(session: AsyncSession, doc_id: int, *, owner_hash: str) -> dict:
    """Scan a document's saved chapters with the preflight rule set.

    Returns a report dict (schema: app.schemas.safety.SafetyScanReport).
    Owner-scoped lookups: raises DocumentNotFound for missing/foreign docs.
    """
    await get_document(session, doc_id, owner_key_hash=owner_hash)
    chapters, _ = await list_chapters(session, novel_id=doc_id, limit=500, offset=0)
    text = build_scan_text(chapters)
    content_hash = compute_content_hash(
        (getattr(ch, "title", ""), getattr(ch, "content_text", "")) for ch in chapters
    )

    cached = _scan_cache.get(doc_id, content_hash)
    if cached is not None:
        logger.info("safety-scan cache hit doc_id=%s", doc_id)
        report = dict(cached)
        report["cached"] = True
        return report

    report = run_scan(text, max_chars=settings.safety_scan_max_chars)
    report.update(
        {
            "doc_id": doc_id,
            "content_hash": content_hash,
            "cached": False,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _scan_cache.put(doc_id, content_hash, report)
    return report