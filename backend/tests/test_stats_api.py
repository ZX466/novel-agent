"""Tests for dashboard stats endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

_AUTH = {"X-API-Key": "test-key"}


class _Row:
    def __init__(self, day: datetime, word_count: int) -> None:
        self.day = day
        self.word_count = word_count


def _make_fake_session(rows: list[_Row]) -> AsyncMock:
    session = AsyncMock()
    result = AsyncMock()
    result.all.return_value = rows
    session.execute.return_value = result
    return session


def test_stats_empty_when_no_documents(app_client: TestClient) -> None:
    fake_session = _make_fake_session([])
    fake_stats = AsyncMock(return_value={
        "today_word_count": 0,
        "consecutive_days": 0,
        "curve": [{"date": "2026-07-19", "word_count": 0}] * 30,
    })

    with patch("app.api.stats._get_dashboard_stats", fake_stats):
        r = app_client.get("/v1/stats/dashboard", headers=_AUTH)

    assert r.status_code == 200
    body = r.json()
    assert body["today_word_count"] == 0
    assert body["consecutive_days"] == 0
    assert len(body["curve"]) == 30


def test_stats_returns_service_result(app_client: TestClient) -> None:
    payload = {
        "today_word_count": 1200,
        "consecutive_days": 3,
        "curve": [{"date": "2026-07-19", "word_count": 500}] * 30,
    }
    fake_stats = AsyncMock(return_value=payload)

    with patch("app.api.stats._get_dashboard_stats", fake_stats):
        r = app_client.get("/v1/stats/dashboard", headers=_AUTH)

    assert r.status_code == 200
    body = r.json()
    assert body == payload
