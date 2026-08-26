"""Regression tests for chat rate limiting and persisted HTML sanitization."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import _deps
from app.config import settings
from app.services.document import sanitize_content_html


class _FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None


def test_sanitize_content_html_removes_active_content() -> None:
    html = '<p onclick="alert(1)">safe</p><script>alert(2)</script><a href="javascript:alert(3)">bad</a>'
    cleaned = sanitize_content_html(html)
    assert "onclick" not in cleaned
    assert "<script" not in cleaned
    assert "javascript:" not in cleaned
    assert "safe" in cleaned


@pytest.mark.asyncio
async def test_chat_rate_limit_rejects_request_over_quota(monkeypatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(_deps, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings, "chat_rate_limit_per_minute", 1)

    assert await _deps.enforce_chat_rate_limit("test-key") == "test-key"
    with pytest.raises(HTTPException) as exc_info:
        await _deps.enforce_chat_rate_limit("test-key")
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"]


@pytest.mark.asyncio
async def test_chat_rate_limit_fails_closed_when_redis_is_unavailable(monkeypatch) -> None:
    def unavailable():
        raise ConnectionError("unavailable")

    monkeypatch.setattr(_deps, "get_redis", unavailable)
    with pytest.raises(HTTPException) as exc_info:
        await _deps.enforce_chat_rate_limit("test-key")
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_require_api_key_unconfigured_returns_503_with_setup_guidance(monkeypatch) -> None:
    """L8: empty API_KEYS must yield 503 with actionable deployment guidance."""
    monkeypatch.setattr(settings, "api_keys", [])
    with pytest.raises(HTTPException) as exc_info:
        await _deps.require_api_key("any-key")
    assert exc_info.value.status_code == 503
    detail = exc_info.value.detail
    assert "API_KEYS" in detail
    assert "backend/.env" in detail
    assert "deploy/README.md" in detail
    # Guidance must never leak configured key material.
    assert "sk-" not in detail


@pytest.mark.asyncio
async def test_require_api_key_configured_behavior_unchanged(monkeypatch) -> None:
    """L8: with API_KEYS set, valid keys pass and invalid keys still get 401."""
    monkeypatch.setattr(settings, "api_keys", ["test-key"])
    assert await _deps.require_api_key("test-key") == "test-key"
    with pytest.raises(HTTPException) as exc_info:
        await _deps.require_api_key("wrong-key")
    assert exc_info.value.status_code == 401
