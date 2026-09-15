"""09-15: /v1/chat/test connection-test — two fixes verified here.

1. stage binding: the endpoint declared `stage: str = "draft"` — FastAPI
   reads bare scalars from the QUERY string, so the frontend's JSON body
   {"stage": "embedding"} was silently ignored and every 测试连接 actually
   probed the DRAFT stage's credentials. Fixed with Body(embed=True).
2. timeout bound: the embedding branches hardcoded timeout=30 — a stalled
   provider hung the 测试连接 button 30s. Both embedding branches now use
   settings.connection_test_timeout_seconds (default 8s, max_retries=0).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import litellm
import pytest

from app.config import settings


@pytest.mark.asyncio
@pytest.mark.parametrize("byok", [True, False], ids=["byok", "env-fallback"])
async def test_embedding_connection_test_uses_body_stage_and_short_timeout(
    async_app_client, monkeypatch, byok
):
    """POST with JSON body {"stage": "embedding"} must probe the EMBEDDING
    stage's credentials via an openai client built with the configured
    short timeout — in both BYOK and .env-fallback paths."""
    monkeypatch.setattr(settings, "connection_test_timeout_seconds", 8.0)
    if not byok:
        monkeypatch.setattr(settings, "byok_fallback_to_env", True)
        monkeypatch.setattr(settings, "embedding_api_key", "sk-env-fallback")
        monkeypatch.setattr(
            settings, "embedding_api_base", "https://env-fallback.example/v1"
        )
        monkeypatch.setattr(settings, "embedding_model", "env-embed-model")

    captured: dict = {}

    class _FakeEmbeddings:
        create = AsyncMock(
            return_value=SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1] * 1024)]
            )
        )

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.embeddings = _FakeEmbeddings()

    # Force the chat branch to fail with "model does not exist" so the
    # endpoint falls back to the embeddings branch we're asserting on.
    async def _fake_acompletion(**kwargs):
        raise litellm.BadRequestError(
            message="Model `x` does not exist",
            model=kwargs.get("model", "x"),
            llm_provider="openai",
        )

    headers = {"X-API-Key": "test-key"}
    if byok:
        chat_stage = {
            "api_base": "https://byok.example/v1",
            "api_key": "sk-byok",
            "model": "byok-chat",
        }
        # ProviderConfig requires draft/refine/evaluate; we're testing the
        # embedding branch, the chat stages just satisfy the schema.
        headers["X-Provider-Config"] = json.dumps(
            {
                "draft": chat_stage,
                "refine": chat_stage,
                "evaluate": chat_stage,
                "embedding": {
                    "api_base": "https://byok.example/v1",
                    "api_key": "sk-byok",
                    "model": "byok-embed",
                },
            }
        )

    with patch.object(litellm, "acompletion", _fake_acompletion), patch(
        "openai.AsyncOpenAI", _FakeAsyncOpenAI
    ):
        resp = await async_app_client.post(
            "/v1/chat/test", json={"stage": "embedding"}, headers=headers
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    # Fix 2: short timeout, no retries.
    assert captured["timeout"] == 8.0
    assert captured["max_retries"] == 0
    # Fix 1: the EMBEDDING stage's base was probed (not draft's).
    expected_base = (
        "https://byok.example/v1" if byok else "https://env-fallback.example/v1"
    )
    assert captured["base_url"] == expected_base
