"""Tests for dashboard stats endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import _FakeResult

_AUTH = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_stats_service_builds_real_sql(mock_session) -> None:
    """The service must construct executable SQL.

    Regression: `cast(Document.updated_at, date)` passed the Python
    ``datetime.date`` class instead of SQLAlchemy ``Date``, which only
    exploded at statement-execution time (TypeError: missing argument
    'year'). Building the statement in this test evaluates the cast, so
    the shadowing bug can never ship again.
    """
    from app.services import stats

    mock_session.set_execute_results([
        _FakeResult(scalars=[]),  # daily aggregation
        _FakeResult(scalars=[SimpleNamespace(docs=1, chapters=2, words=300)]),  # totals
    ])
    result = await stats.get_dashboard_stats(mock_session)
    assert len(result["daily_words"]) == 30
    assert result["total_documents"] == 1
    assert result["total_chapters"] == 2
    assert result["total_words"] == 300


class _Row:
    def __init__(self, day: datetime, word_count: int) -> None:
        self.day = day
        self.word_count = word_count


def _make_fake_session(rows: list[_Row], totals: tuple[int, int, int] | None = None) -> AsyncMock:
    session = AsyncMock()
    daily_result = AsyncMock()
    daily_result.all.return_value = rows

    totals_row = AsyncMock()
    totals_row.docs = totals[0] if totals else 0
    totals_row.chapters = totals[1] if totals else 0
    totals_row.words = totals[2] if totals else 0
    totals_result = AsyncMock()
    totals_result.one.return_value = totals_row

    def _execute_side_effect(stmt):
        text = str(stmt)
        if "count(Chapter" in text:
            return totals_result
        return daily_result

    session.execute.side_effect = _execute_side_effect
    return session


def test_stats_empty_when_no_documents(app_client: TestClient) -> None:
    fake_session = _make_fake_session([], totals=(0, 0, 0))

    with patch("app.api.stats._get_dashboard_stats", AsyncMock(return_value={
        "total_documents": 0,
        "total_chapters": 0,
        "total_words": 0,
        "streak_days": 0,
        "today_words": 0,
        "daily_words": [{"date": "2026-07-19", "words": 0}] * 30,
    })):
        r = app_client.get("/v1/stats/dashboard", headers=_AUTH)

    assert r.status_code == 200
    body = r.json()
    assert body["total_documents"] == 0
    assert body["total_chapters"] == 0
    assert body["total_words"] == 0
    assert body["streak_days"] == 0
    assert body["today_words"] == 0
    assert len(body["daily_words"]) == 30


def test_stats_returns_service_result(app_client: TestClient) -> None:
    payload = {
        "total_documents": 5,
        "total_chapters": 42,
        "total_words": 128000,
        "streak_days": 7,
        "today_words": 1200,
        "daily_words": [{"date": "2026-07-19", "words": 500}] * 30,
    }

    with patch("app.api.stats._get_dashboard_stats", AsyncMock(return_value=payload)):
        r = app_client.get("/v1/stats/dashboard", headers=_AUTH)

    assert r.status_code == 200
    body = r.json()
    assert body == payload
