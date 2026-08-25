"""Tests for 交稿雷达 (R6-3) — pre-export safety preflight.

Covers:
  - New preflight default rules (copyright / privacy / sensitive)
  - compute_content_hash determinism + change detection
  - build_scan_text / run_scan (pure, no DB)
  - SafetyScanCache (in-process result cache with LRU cap)
  - scan_document service via MockAsyncSession
  - GET /v1/documents/{id}/safety-scan API (cached/uncached, 404, auth)
  - Export tenant-isolation regression (no cross-owner export)
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.safety import RuleEngine, Severity
from app.services import safety_scan as scan_module
from tests.conftest import _FakeResult

_AUTH = {"X-API-Key": "test-key"}
_OTHER_AUTH = {"X-API-Key": "other-key"}

_PREFLIGHT_RULES = (
    "copyright_url",
    "copyright_statement",
    "privacy_qq",
    "privacy_wechat",
    "sensitive_platform",
)


@pytest.fixture(autouse=True)
def _clear_scan_cache() -> None:
    """Keep the in-process scan cache isolated between tests."""
    scan_module.clear_scan_cache()
    yield
    scan_module.clear_scan_cache()


def _engine() -> RuleEngine:
    return RuleEngine()


# ---------------------------------------------------------------------------
# Preflight default rules
# ---------------------------------------------------------------------------


def test_preflight_rules_registered_as_non_blocking_warnings() -> None:
    engine = _engine()
    for name in _PREFLIGHT_RULES:
        assert engine.has(name), name
        rule = next(r for r in engine.list_rules() if r.name == name)
        assert rule.severity == Severity.WARNING
        assert rule.category in {"copyright", "privacy", "sensitive"}


def test_copyright_url_rule_detects_urls() -> None:
    engine = _engine()
    matched = [r.rule_name for r in engine.check("详见 https://example.com/a 更多") if r.matched]
    assert "copyright_url" in matched
    assert not any(r.matched for r in engine.check("这里没有网址"))


def test_copyright_statement_rule_detects_attribution() -> None:
    engine = _engine()
    assert any(r.matched for r in engine.check("转载自某论坛，侵删"))
    assert any(r.matched for r in engine.check("版权所有 2024"))
    assert not any(r.matched for r in engine.check("他正在写小说，灵感来自生活"))


def test_privacy_rules_detect_qq_and_wechat() -> None:
    engine = _engine()
    assert any(r.rule_name == "privacy_qq" and r.matched for r in engine.check("加我 QQ群 123456789"))
    assert any(r.rule_name == "privacy_wechat" and r.matched for r in engine.check("wxid_ab12cd34ef 加我"))
    assert any(r.rule_name == "privacy_wechat" and r.matched for r in engine.check("微信号：ZhaoXue_888"))
    assert not any(r.matched for r in engine.check("他数了 123456 次"))
    assert not any(r.matched for r in engine.check("正常社交不涉及联系方式"))


def test_sensitive_platform_rule_detects_common_terms() -> None:
    engine = _engine()
    assert any(r.rule_name == "sensitive_platform" and r.matched for r in engine.check("网络赌博害人不浅"))
    assert any(r.rule_name == "sensitive_platform" and r.matched for r in engine.check("传销骗局曝光"))
    assert not any(r.matched for r in engine.check("今天阳光很好"))


def test_preflight_warnings_never_block() -> None:
    engine = _engine()
    text = "联系 13812345678，详见 https://example.com，转载自某处，微信 wxid_ab12cd34"
    results = engine.check(text)
    assert not engine.should_block(results)
    assert engine.max_severity(results) <= Severity.WARNING


# ---------------------------------------------------------------------------
# Hash / text assembly / scan (pure)
# ---------------------------------------------------------------------------


def test_compute_content_hash_deterministic_and_change_sensitive() -> None:
    h1 = scan_module.compute_content_hash([("t1", "abc"), ("t2", "def")])
    h2 = scan_module.compute_content_hash([("t1", "abc"), ("t2", "def")])
    h3 = scan_module.compute_content_hash([("t1", "abx"), ("t2", "def")])
    h4 = scan_module.compute_content_hash([("t2", "def"), ("t1", "abc")])
    assert h1 == h2
    assert h1 != h3
    assert h1 != h4


def test_build_scan_text_joins_title_and_body() -> None:
    chapters = [
        SimpleNamespace(title="第一章", content_text="正文一"),
        SimpleNamespace(title="第二章", content_text="正文二"),
    ]
    text = scan_module.build_scan_text(chapters)
    assert "第一章" in text and "正文一" in text
    assert "第二章" in text and "正文二" in text
    assert text.index("第一章") < text.index("第二章")


def test_run_scan_finds_pii_and_masks_evidence() -> None:
    text = "联系电话 13812345678，邮箱 aaa@example.com，转载自某处"
    report = scan_module.run_scan(text)
    cats = {f["category"] for f in report["findings"]}
    assert "pii" in cats and "copyright" in cats
    pii_samples = [f["sample"] for f in report["findings"] if f["category"] == "pii"]
    assert pii_samples
    assert all("13812345678" not in s for s in pii_samples)
    assert any(s.startswith("138") and "*" in s for s in pii_samples)
    assert report["summary"]["matched_count"] >= 3
    assert report["rules_checked"] == len(_engine().list_rules())


def test_run_scan_empty_text_is_clean() -> None:
    report = scan_module.run_scan("")
    assert report["findings"] == []
    assert report["summary"]["matched_count"] == 0
    assert report["summary"]["should_block"] is False


def test_run_scan_truncates_over_max_chars() -> None:
    # A phone number at the very end is cut off when truncation applies.
    report = scan_module.run_scan("很长的正文" * 100 + " 13812345678", max_chars=120)
    assert report["truncated"] is True
    assert all(f["category"] != "pii" for f in report["findings"])


# ---------------------------------------------------------------------------
# SafetyScanCache
# ---------------------------------------------------------------------------


def test_cache_hit_put_get_replace() -> None:
    cache = scan_module.SafetyScanCache(max_entries=4)
    cache.put(1, "h1", {"n": 1})
    assert cache.get(1, "h1") == {"n": 1}
    cache.put(1, "h1", {"n": 2})
    assert cache.get(1, "h1") == {"n": 2}
    assert cache.get(1, "h2") is None
    assert cache.get(2, "h1") is None


def test_cache_lru_eviction() -> None:
    cache = scan_module.SafetyScanCache(max_entries=2)
    cache.put(1, "a", {"v": 1})
    cache.put(2, "b", {"v": 2})
    cache.put(3, "c", {"v": 3})
    assert cache.get(1, "a") is None
    assert cache.get(2, "b") == {"v": 2}
    assert cache.get(3, "c") == {"v": 3}


# ---------------------------------------------------------------------------
# scan_document service (MockAsyncSession)
# ---------------------------------------------------------------------------


def _chapters(*items: tuple[str, str]):
    return [SimpleNamespace(title=t, content_text=c) for t, c in items]


def _arm_service_session(mock_session, doc_id: int, chapters) -> None:
    """(Re-)arm the MockAsyncSession queues — each scan_document call
    consumes one scalar (get_document) + one scalar (list_chapters count)
    + one execute result, so the mock must be re-armed per call."""
    mock_session.set_scalar_results([SimpleNamespace(id=doc_id, status="active"), len(chapters)])
    mock_session.set_execute_results([_FakeResult(scalars=chapters)])


@pytest.mark.asyncio
async def test_scan_document_service_caches_by_content_hash(mock_session) -> None:
    dirty = _chapters(("第一章", "13812345678 转载自某处"), ("第二章", "干净正文"))
    _arm_service_session(mock_session, 7, dirty)

    r1 = await scan_module.scan_document(mock_session, 7, owner_hash="owner-1")
    assert r1["doc_id"] == 7
    assert r1["cached"] is False
    assert r1["content_hash"]
    assert r1["summary"]["matched_count"] >= 2

    # Same content -> cache hit (cache keyed by content hash).
    _arm_service_session(mock_session, 7, dirty)
    r2 = await scan_module.scan_document(mock_session, 7, owner_hash="owner-1")
    assert r2["cached"] is True
    assert r2["content_hash"] == r1["content_hash"]

    # Content changed -> new hash -> cache miss.
    _arm_service_session(mock_session, 7, _chapters(("第一章", "干净正文"), ("第二章", "干净正文")))
    r3 = await scan_module.scan_document(mock_session, 7, owner_hash="owner-1")
    assert r3["cached"] is False
    assert r3["summary"]["matched_count"] == 0


@pytest.mark.asyncio
async def test_scan_document_respects_max_chars_setting(mock_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "safety_scan_max_chars", 10)
    doc = SimpleNamespace(id=8, status="active")
    mock_session.set_scalar_results([doc, 1])
    mock_session.set_execute_results([_FakeResult(scalars=_chapters(("第一章", "很长很长的正文内容 13812345678")))])
    r = await scan_module.scan_document(mock_session, 8, owner_hash="owner-1")
    assert r["truncated"] is True


# ---------------------------------------------------------------------------
# Safety-scan API
# ---------------------------------------------------------------------------


def _create_doc_with_chapter(app_client: TestClient, title: str, body: str) -> tuple[int, int]:
    create = app_client.post("/v1/documents", json={"title": title}, headers=_AUTH)
    assert create.status_code == 201
    doc_id = create.json()["id"]
    ch = app_client.post(
        f"/v1/documents/{doc_id}/chapters",
        json={"chapter_index": 0, "title": "第一章", "content_text": body},
        headers=_AUTH,
    )
    assert ch.status_code == 201
    return doc_id, ch.json()["id"]


def test_safety_scan_api_reports_findings_then_caches(app_client: TestClient) -> None:
    doc_id, chapter_id = _create_doc_with_chapter(app_client, "雷达测试", "电话 13812345678，转载自论坛")
    r1 = app_client.get(f"/v1/documents/{doc_id}/safety-scan", headers=_AUTH)
    assert r1.status_code == 200
    body = r1.json()
    assert body["doc_id"] == doc_id
    assert body["cached"] is False
    assert body["summary"]["matched_count"] >= 2
    cats = {f["category"] for f in body["findings"]}
    assert "pii" in cats and "copyright" in cats
    pii_samples = [f["sample"] for f in body["findings"] if f["category"] == "pii"]
    assert pii_samples
    assert all("13812345678" not in s for s in pii_samples)

    r2 = app_client.get(f"/v1/documents/{doc_id}/safety-scan", headers=_AUTH)
    assert r2.status_code == 200
    assert r2.json()["cached"] is True
    assert r2.json()["content_hash"] == body["content_hash"]

    # Content change invalidates the cached result.
    patch = app_client.patch(
        f"/v1/documents/{doc_id}/chapters/{chapter_id}",
        json={"content_text": "干净的正文"},
        headers=_AUTH,
    )
    assert patch.status_code == 200
    r3 = app_client.get(f"/v1/documents/{doc_id}/safety-scan", headers=_AUTH)
    assert r3.json()["cached"] is False
    assert r3.json()["summary"]["matched_count"] == 0


def test_safety_scan_404_for_missing_document(app_client: TestClient) -> None:
    r = app_client.get("/v1/documents/9999/safety-scan", headers=_AUTH)
    assert r.status_code == 404


def test_safety_scan_404_for_foreign_document(app_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_keys", ["test-key", "other-key"])
    doc_id, _ = _create_doc_with_chapter(app_client, "隔离测试", "正文")
    r = app_client.get(f"/v1/documents/{doc_id}/safety-scan", headers=_OTHER_AUTH)
    assert r.status_code == 404


def test_safety_scan_requires_api_key(app_client: TestClient) -> None:
    r = app_client.get("/v1/documents/1/safety-scan")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Export tenant isolation regression (R6-3 security follow-up)
# ---------------------------------------------------------------------------


def test_export_rejects_foreign_owner_document(app_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_keys", ["test-key", "other-key"])
    doc_id, _ = _create_doc_with_chapter(app_client, "导出隔离", "正文")
    r_foreign = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "md"}, headers=_OTHER_AUTH)
    assert r_foreign.status_code == 404
    r_owner = app_client.get(f"/v1/documents/{doc_id}/export", params={"format": "md"}, headers=_AUTH)
    assert r_owner.status_code == 200