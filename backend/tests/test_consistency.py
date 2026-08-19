"""Tests for the setting-consistency service and API (R5-3 设定一致性哨兵).

Service tests use MockAsyncSession + a patched `retrieve` so no real DB or
embedding call is made. API tests mock the service layer and `load_parent`,
following the same pattern as the knowledge-docs endpoint tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.models.character import Character
from app.models.chapter import Chapter
from app.models.consistency_check import ConsistencyCheck
from app.schemas.novel_memory import RetrievalHit
from app.services import consistency as cs
from tests.conftest import _FakeResult

_AUTH = {"X-API-Key": "test-key"}


def _char(cid: int, name: str, **attrs) -> Character:
    return Character(
        id=cid, novel_id=7, name=name, role="主角",
        description="", attributes=attrs, arc_summary="",
    )


def _hit(etype: str, eid: int, payload: dict) -> RetrievalHit:
    return RetrievalHit(entity_type=etype, entity_id=eid, score=0.8, payload=payload)


# ===========================================================================
# extract_numeric_facts
# ===========================================================================


def test_extract_facts_basic_and_multi():
    assert cs.extract_numeric_facts("小明25岁，身高175厘米") == [
        (25.0, "岁"), (175.0, "厘米"),
    ]


def test_extract_facts_long_unit_wins():
    # 厘米 must not be read as 米.
    assert cs.extract_numeric_facts("柱子高180厘米") == [(180.0, "厘米")]


def test_extract_facts_wan_qian_scaling():
    assert cs.extract_numeric_facts("他活了1.5万年") == [(15000.0, "年")]
    assert cs.extract_numeric_facts("此城存在3千年") == [(3000.0, "年")]


def test_extract_facts_normalizes_units():
    assert cs.extract_numeric_facts("重2千克，含量50％") == [
        (2.0, "公斤"), (50.0, "%"),
    ]


def test_extract_facts_empty():
    assert cs.extract_numeric_facts("没有数字的文本") == []
    assert cs.extract_numeric_facts("") == []


# ===========================================================================
# extract_mentioned_characters
# ===========================================================================


def test_mention_longest_name_wins():
    chars = [_char(1, "李小明"), _char(2, "小明")]
    got = cs.extract_mentioned_characters("李小明走进来", chars)
    assert [c.id for c in got] == [1]


def test_mention_respects_min_len_and_dedup():
    chars = [_char(1, "陈"), _char(2, "阿芳")]
    got = cs.extract_mentioned_characters("阿芳和陈", chars, min_len=2)
    assert [c.id for c in got] == [2]


def test_mention_preserves_profile_order():
    chars = [_char(1, "王铁柱"), _char(2, "铁柱")]
    got = cs.extract_mentioned_characters("铁柱在门口等王铁柱", chars)
    assert [c.id for c in got] == [1, 2]


# ===========================================================================
# detect_fact_conflicts
# ===========================================================================


def test_conflict_same_unit_diff_value():
    msgs = cs.detect_fact_conflicts([(25.0, "岁")], [(28.0, "岁")])
    assert len(msgs) == 1
    assert "年龄" in msgs[0] and "25岁" in msgs[0] and "28岁" in msgs[0]


def test_conflict_matches_any_stored_value():
    assert cs.detect_fact_conflicts([(25.0, "岁")], [(20.0, "岁"), (25.0, "岁")]) == []


def test_conflict_different_units_ignored():
    assert cs.detect_fact_conflicts([(25.0, "岁")], [(25.0, "公斤")]) == []


def test_conflict_empty():
    assert cs.detect_fact_conflicts([], [(28.0, "岁")]) == []
    assert cs.detect_fact_conflicts([(25.0, "岁")], []) == []


# ===========================================================================
# _profile_fact_text
# ===========================================================================


def test_profile_fact_text_renders_attribute_numbers():
    c = _char(1, "李小明", age=28, height=175, weight=None)
    text = cs._profile_fact_text(c)
    assert "28岁" in text and "175厘米" in text


# ===========================================================================
# check_draft (service)
# ===========================================================================


@pytest.mark.asyncio
async def test_check_draft_conflict_persists_with_evidence(mock_session):
    chars = [_char(1, "李小明", age=28)]
    mock_session.set_execute_results([_FakeResult(scalars=chars)])
    evidence = _hit("world_setting", 3, {"title": "门规", "content_text": "李小明 28岁 门规"})

    with patch.object(cs, "retrieve", AsyncMock(return_value=[evidence])) as ret:
        rows = await cs.check_draft(
            mock_session, novel_id=7, owner_key_hash="owner-hash",
            content_text="李小明今年25岁",
        )

    ret.assert_awaited_once()
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "conflict"
    assert row.target_type == "character" and row.target_id == 1
    assert row.target_name == "李小明"
    assert "25岁" in row.detail and "28岁" in row.detail
    assert row.evidence_type == "world_setting" and row.evidence_id == 3
    assert row.evidence_snippet.startswith("李小明 28岁")
    assert mock_session.commits == 1
    assert len(mock_session.added) == 1


@pytest.mark.asyncio
async def test_check_draft_pass_with_evidence(mock_session):
    chars = [_char(1, "李小明", age=28)]
    mock_session.set_execute_results([_FakeResult(scalars=chars)])
    evidence = _hit("character", 1, {"name": "李小明", "description": "28岁"})

    with patch.object(cs, "retrieve", AsyncMock(return_value=[evidence])):
        rows = await cs.check_draft(
            mock_session, novel_id=7, owner_key_hash="h",
            content_text="李小明推开大门",
        )
    assert len(rows) == 1
    assert rows[0].verdict == "pass"
    assert rows[0].detail == "李小明 未检出数值设定矛盾"


@pytest.mark.asyncio
async def test_check_draft_no_evidence_no_rows(mock_session):
    chars = [_char(1, "李小明")]
    mock_session.set_execute_results([_FakeResult(scalars=chars)])

    with patch.object(cs, "retrieve", AsyncMock(return_value=[])):
        rows = await cs.check_draft(
            mock_session, novel_id=7, owner_key_hash="h",
            content_text="李小明看向远方",
        )
    assert rows == []
    assert mock_session.commits == 0


@pytest.mark.asyncio
async def test_check_draft_empty_or_no_mention(mock_session):
    with patch.object(cs, "retrieve", AsyncMock()) as ret:
        assert await cs.check_draft(mock_session, novel_id=7, content_text="   ") == []
        mock_session.set_execute_results([_FakeResult(scalars=[_char(1, "李小明")])])
        assert await cs.check_draft(mock_session, novel_id=7, content_text="没有人") == []
    ret.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_draft_reads_chapter_content(mock_session):
    chars = [_char(1, "李小明", age=28)]
    chapter = Chapter(
        id=9, novel_id=7, chapter_index=1, title="t",
        content_text="李小明今年30岁",
    )
    mock_session.set_scalar_results([chapter])
    mock_session.set_execute_results([_FakeResult(scalars=chars)])
    with patch.object(cs, "retrieve", AsyncMock(return_value=[])):
        rows = await cs.check_draft(
            mock_session, novel_id=7, owner_key_hash="h", chapter_id=9,
        )
    assert len(rows) == 1 and rows[0].verdict == "conflict"


@pytest.mark.asyncio
async def test_check_draft_missing_chapter_raises(mock_session):
    mock_session.set_scalar_results([None])
    with pytest.raises(ValueError, match="章节不存在"):
        await cs.check_draft(mock_session, novel_id=7, owner_key_hash="h", chapter_id=9)


@pytest.mark.asyncio
async def test_check_draft_rejects_foreign_novel_chapter(mock_session):
    """P0 regression: a chapter belonging to another novel must be refused
    (no content read, no existence oracle) — same error as a missing one."""
    foreign = Chapter(
        id=9, novel_id=999, chapter_index=1, title="t",
        content_text="李小明今年20岁",
    )
    mock_session.set_scalar_results([foreign])
    mock_session.set_execute_results([_FakeResult(scalars=[])])
    with patch.object(cs, "retrieve", AsyncMock()) as ret:
        with pytest.raises(ValueError, match="章节不存在"):
            await cs.check_draft(
                mock_session, novel_id=7, owner_key_hash="h", chapter_id=9,
            )
    ret.assert_not_awaited()
    assert mock_session.commits == 0


# ===========================================================================
# list_checks (service)
# ===========================================================================


@pytest.mark.asyncio
async def test_list_checks_returns_items_and_total(mock_session):
    chk = ConsistencyCheck(
        id=1, novel_id=7, owner_key_hash="h", target_type="character",
        target_id=1, target_name="李小明", verdict="conflict",
        detail="年龄: 草稿 25岁 与设定 28岁 不一致",
        created_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
    )
    mock_session.set_scalar_results([1])
    mock_session.set_execute_results([_FakeResult(scalars=[chk])])

    items, total = await cs.list_checks(mock_session, novel_id=7, owner_key_hash="h")
    assert total == 1 and len(items) == 1
    assert items[0].verdict == "conflict"


# ===========================================================================
# HTTP API
# ===========================================================================


def _check_item() -> SimpleNamespace:
    return SimpleNamespace(
        id=1, novel_id=7, chapter_id=None, target_type="character", target_id=1,
        target_name="李小明", verdict="conflict",
        detail="年龄: 草稿 25岁 与设定 28岁 不一致",
        evidence_type="world_setting", evidence_id=3,
        evidence_snippet="门规 李小明 28岁",
        created_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
    )


def test_check_requires_auth(app_client: TestClient) -> None:
    r = app_client.post("/v1/documents/7/consistency/check", json={"content_text": "x"})
    assert r.status_code == 422


def test_check_rejects_missing_source(app_client: TestClient) -> None:
    r = app_client.post(
        "/v1/documents/7/consistency/check", json={}, headers=_AUTH,
    )
    assert r.status_code == 422


def test_check_returns_created_rows(app_client: TestClient) -> None:
    with patch("app.api.consistency.load_parent", new=AsyncMock()), \
            patch("app.api.consistency.check_draft",
                  new=AsyncMock(return_value=[_check_item()])):
        r = app_client.post(
            "/v1/documents/7/consistency/check",
            json={"content_text": "李小明今年25岁"},
            headers=_AUTH,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["verdict"] == "conflict"
    assert body["items"][0]["evidence_id"] == 3


def test_check_400_when_chapter_missing(app_client: TestClient) -> None:
    async def _raise(*a, **k):
        raise ValueError("章节不存在")

    with patch("app.api.consistency.load_parent", new=AsyncMock()), \
            patch("app.api.consistency.check_draft", new=_raise):
        r = app_client.post(
            "/v1/documents/7/consistency/check",
            json={"chapter_id": 999},
            headers=_AUTH,
        )
    assert r.status_code == 400
    assert r.json()["detail"] == "章节不存在"


def test_check_404_when_novel_missing(app_client: TestClient) -> None:
    async def _raise(*a, **k):
        raise HTTPException(status_code=404, detail="作品不存在")

    with patch("app.api.consistency.load_parent", new=_raise):
        r = app_client.post(
            "/v1/documents/999/consistency/check",
            json={"content_text": "x"},
            headers=_AUTH,
        )
    assert r.status_code == 404


def test_list_checks_endpoint(app_client: TestClient) -> None:
    with patch("app.api.consistency.load_parent", new=AsyncMock()), \
            patch("app.api.consistency.list_checks",
                  new=AsyncMock(return_value=([_check_item()], 1))):
        r = app_client.get(
            "/v1/documents/7/consistency/checks", headers=_AUTH,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["target_name"] == "李小明"


def test_list_checks_requires_auth(app_client: TestClient) -> None:
    r = app_client.get("/v1/documents/7/consistency/checks")
    assert r.status_code == 422