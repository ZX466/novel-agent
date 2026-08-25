"""SSE streaming tests for the /v1/chat BYOK flow.

Uses `async_app_client` (httpx.ASGITransport) to consume the Server-Sent
Events stream. `stream_pipeline` is monkeypatched so no real LLM call is made;
we only verify header parsing, credential forwarding, error branching, and
log redaction.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx
import litellm
import pytest
from fastapi import HTTPException

from app.schemas.chat import ProviderConfig, StageConfig


@pytest.mark.asyncio
async def test_embedding_provider_config_rejects_malformed_header():
    from app.api._deps import extract_embedding_stage

    with pytest.raises(HTTPException) as exc_info:
        await extract_embedding_stage('{"embedding": {"api_base": "https://x/v1", "api_key": "k", "model": 123}}')
    assert exc_info.value.status_code == 422

# --- helpers ---------------------------------------------------------------


def _make_stage(
    *,
    api_base: str = "https://api.openai.com/v1",
    api_key: str = "sk-test-key-abc123",
    model: str = "gpt-4o-mini",
    extra_headers: dict[str, str] | None = None,
) -> StageConfig:
    return StageConfig(
        api_base=api_base,
        api_key=api_key,
        model=model,
        extra_headers=extra_headers or {},
    )


def _make_provider_config(
    *,
    draft: StageConfig | None = None,
    refine: StageConfig | None = None,
    evaluate: StageConfig | None = None,
) -> ProviderConfig:
    return ProviderConfig(
        draft=draft or _make_stage(),
        refine=refine or _make_stage(),
        evaluate=evaluate or _make_stage(),
    )


def _byok_header(
    *,
    cfg: ProviderConfig | None = None,
    draft: StageConfig | None = None,
    refine: StageConfig | None = None,
    evaluate: StageConfig | None = None,
) -> dict[str, str]:
    """Build the X-Provider-Config header carrying a ProviderConfig JSON.

    IMPORTANT: we serialize via `model_dump()` and then `json.dumps()` rather
    than `model_dump_json()`, because the StageConfig.api_key field_serializer
    redacts the key on serialization. A real frontend client sends the raw
    (un-redacted) key in the header; the test must mirror that wire format.
    """
    cfg = cfg or _make_provider_config(draft=draft, refine=refine, evaluate=evaluate)
    raw = {
        "draft": {**cfg.draft.model_dump()},
        "refine": {**cfg.refine.model_dump()},
        "evaluate": {**cfg.evaluate.model_dump()},
    }
    # Restore the un-redacted api_keys (model_dump redacted them).
    raw["draft"]["api_key"] = cfg.draft.api_key
    raw["refine"]["api_key"] = cfg.refine.api_key
    raw["evaluate"]["api_key"] = cfg.evaluate.api_key
    return {"X-Provider-Config": json.dumps(raw)}


def _make_async_gen(chunks: list[str] | Exception):
    """Build an async generator function suitable for monkeypatching
    stream_pipeline. If `chunks` is an Exception, raising it on first iter.
    """

    if isinstance(chunks, Exception):
        async def _gen(topic, provider_config=None, **kwargs) -> AsyncIterator[str]:
            raise chunks
            yield  # pragma: no cover - makes this an async generator
    else:
        async def _gen(topic, provider_config=None, **kwargs) -> AsyncIterator[str]:
            for c in chunks:
                yield c

    return _gen


# --- header parsing --------------------------------------------------------


@pytest.mark.asyncio
async def test_full_header_forwards_provider_config(async_app_client, monkeypatch):
    """When X-Provider-Config header is present, stream_pipeline receives a
    fully populated ProviderConfig with all three stages."""
    captured: dict[str, object] = {}

    async def _spy(topic, provider_config=None, **kwargs) -> AsyncIterator[str]:
        captured["topic"] = topic
        captured["provider_config"] = provider_config
        yield "hi"
        return

    monkeypatch.setattr("app.api.chat.stream_pipeline", _spy)

    draft_stage = _make_stage(
        api_base="https://draft.example.com/v1",
        api_key="sk-draft-xxx",
        model="draft-model",
    )
    refine_stage = _make_stage(
        api_base="https://refine.example.com/v1",
        api_key="sk-refine-xxx",
        model="refine-model",
    )
    eval_stage = _make_stage(
        api_base="https://eval.example.com/v1",
        api_key="sk-eval-xxx",
        model="eval-model",
    )

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hello world"}]},
        headers=_byok_header(
            draft=draft_stage, refine=refine_stage, evaluate=eval_stage
        ),
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert response.status_code == 200
    assert captured["topic"] == "hello world"
    cfg = captured["provider_config"]
    assert isinstance(cfg, ProviderConfig)
    assert cfg.draft.api_base == "https://draft.example.com/v1"
    assert cfg.draft.api_key == "sk-draft-xxx"
    assert cfg.draft.model == "draft-model"
    assert cfg.refine.api_base == "https://refine.example.com/v1"
    assert cfg.refine.model == "refine-model"
    assert cfg.evaluate.api_base == "https://eval.example.com/v1"
    assert cfg.evaluate.model == "eval-model"
    # Wire format check: text-delta + finish event both present (AI SDK v5).
    assert '"type": "text-delta"' in body
    assert '"delta": "hi"' in body
    assert '"type": "finish"' in body
    assert '"finishReason": "stop"' in body


@pytest.mark.asyncio
async def test_missing_header_falls_back_to_none(async_app_client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "byok_fallback_to_env", True)
    captured: dict[str, object] = {}

    async def _spy(topic, provider_config=None, **kwargs) -> AsyncIterator[str]:
        captured["provider_config"] = provider_config
        yield ""
        return

    monkeypatch.setattr("app.api.chat.stream_pipeline", _spy)

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    ) as response:
        await response.aread()

    assert captured["provider_config"] is None


@pytest.mark.asyncio
async def test_invalid_json_header_returns_422(async_app_client):
    """Malformed X-Provider-Config JSON should return 422 to prevent silent
    fallback to .env credentials when the user intended BYOK."""
    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Provider-Config": "not-json"},
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_partial_provider_config_returns_422(async_app_client):
    """ProviderConfig missing one stage should fail validation -> 422."""
    bad_payload = json.dumps({
        "draft": {"api_base": "x", "api_key": "y", "model": "z"},
        "refine": {"api_base": "x", "api_key": "y", "model": "z"},
    })
    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Provider-Config": bad_payload},
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_extra_headers_per_stage(async_app_client, monkeypatch):
    """Each stage can carry its own extra_headers independently."""
    captured: dict[str, object] = {}

    async def _spy(topic, provider_config=None, **kwargs) -> AsyncIterator[str]:
        captured["provider_config"] = provider_config
        yield ""
        return

    monkeypatch.setattr("app.api.chat.stream_pipeline", _spy)

    cfg = _make_provider_config(
        draft=_make_stage(extra_headers={"X-Title": "Draft"}),
        refine=_make_stage(extra_headers={"HTTP-Referer": "https://refine.dev"}),
        evaluate=_make_stage(),  # no extra headers
    )

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=_byok_header(cfg=cfg),
    ) as response:
        await response.aread()

    pc = captured["provider_config"]
    assert isinstance(pc, ProviderConfig)
    assert pc.draft.extra_headers == {"X-Title": "Draft"}
    assert pc.refine.extra_headers == {"HTTP-Referer": "https://refine.dev"}
    assert pc.evaluate.extra_headers == {}


# --- BYOK_FALLBACK_TO_ENV=false short-circuit -----------------------------


@pytest.mark.asyncio
async def test_no_credentials_short_circuit_when_byok_required(
    async_app_client, monkeypatch
):
    """When BYOK_FALLBACK_TO_ENV=false and no header is supplied, the SSE
    stream must contain an error with '请先配置 API Key' without invoking
    stream_pipeline."""
    from app.config import settings

    monkeypatch.setattr(settings, "byok_fallback_to_env", False)

    invoked = False

    async def _should_not_run(topic, provider_config=None, **kwargs) -> AsyncIterator[str]:
        nonlocal invoked
        invoked = True
        yield ""
        return

    monkeypatch.setattr("app.api.chat.stream_pipeline", _should_not_run)

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert invoked is False
    assert '"type": "error"' in body
    assert "请先配置 API Key" in body
    # Finish event must still be emitted so the client closes cleanly.
    assert '"type": "finish"' in body
    assert '"finishReason": "stop"' in body


@pytest.mark.asyncio
async def test_empty_topic_short_circuits_to_finish_only(async_app_client, monkeypatch):
    invoked = False

    async def _should_not_run(topic, provider_config=None, **kwargs) -> AsyncIterator[str]:
        nonlocal invoked
        invoked = True
        yield ""
        return

    monkeypatch.setattr("app.api.chat.stream_pipeline", _should_not_run)

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "   "}]},
        headers=_byok_header(),
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert invoked is False
    # Only the finish event, no text deltas and no error events.
    assert '"type": "finish"' in body
    assert '"finishReason": "stop"' in body
    assert '"type": "text-delta"' not in body
    assert '"type": "error"' not in body


# --- error branching + redaction ------------------------------------------


@pytest.mark.asyncio
async def test_auth_error_branch_emits_auth_error_message(
    async_app_client, monkeypatch, caplog
):
    """AuthenticationError -> error event with auth error message and the raw
    sk- token in the exception message must NOT appear in any log record."""
    error = litellm.AuthenticationError(
        message="Invalid API key: sk-leaked-abc123-xyz",
        model="openai/gpt-4o-mini",
        llm_provider="openai",
    )
    monkeypatch.setattr(
        "app.api.chat.stream_pipeline", _make_async_gen(error)
    )

    caplog.set_level(logging.DEBUG)

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=_byok_header(),
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert '"type": "error"' in body
    assert "API Key 无效" in body
    # Finish event must still fire (finally clause).
    assert '"type": "finish"' in body
    assert '"finishReason": "stop"' in body
    # The raw leaked key must not appear in any captured log record.
    for record in caplog.records:
        msg = record.getMessage()
        assert "sk-leaked-abc123" not in msg, (
            f"Raw API key leaked in log: {msg}"
        )


@pytest.mark.asyncio
async def test_connection_error_branch(async_app_client, monkeypatch):
    error = litellm.APIConnectionError(
        message="Connection refused",
        model="openai/gpt-4o-mini",
        llm_provider="openai",
    )
    monkeypatch.setattr(
        "app.api.chat.stream_pipeline", _make_async_gen(error)
    )

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=_byok_header(),
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert '"type": "error"' in body
    assert "无法连接" in body


@pytest.mark.asyncio
async def test_not_found_error_branch(async_app_client, monkeypatch):
    error = litellm.NotFoundError(
        message="model not found",
        model="openai/does-not-exist",
        llm_provider="openai",
    )
    monkeypatch.setattr(
        "app.api.chat.stream_pipeline", _make_async_gen(error)
    )

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=_byok_header(),
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert '"type": "error"' in body
    assert "模型不存在" in body


@pytest.mark.asyncio
async def test_ssrf_rejection_branch(async_app_client, monkeypatch):
    """When stream_pipeline raises ValueError (SSRF rejection from
    _validate_api_base propagating up through the LLM call inside a node),
    the SSE stream must emit the SSRF rejection error message."""
    ssrf_error = ValueError("Blocked internal address: 169.254.169.254")
    monkeypatch.setattr(
        "app.api.chat.stream_pipeline", _make_async_gen(ssrf_error)
    )

    cfg = _make_provider_config(
        draft=_make_stage(api_base="http://169.254.169.254/v1"),
    )
    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=_byok_header(cfg=cfg),
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert '"type": "error"' in body
    assert "API Base URL 不被允许" in body


@pytest.mark.asyncio
async def test_generic_exception_branch(async_app_client, monkeypatch):
    monkeypatch.setattr(
        "app.api.chat.stream_pipeline", _make_async_gen(RuntimeError("boom"))
    )

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=_byok_header(),
    ) as response:
        body = (await response.aread()).decode("utf-8")

    assert '"type": "error"' in body
    assert "Pipeline 出错" in body


# --- multi-chunk streaming -------------------------------------------------


@pytest.mark.asyncio
async def test_multi_chunk_streaming(async_app_client, monkeypatch):
    monkeypatch.setattr(
        "app.api.chat.stream_pipeline", _make_async_gen(["Hel", "lo ", "World"])
    )

    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=_byok_header(),
    ) as response:
        body = (await response.aread()).decode("utf-8")

    # Each chunk becomes its own text-delta event (AI SDK v5).
    assert '"delta": "Hel"' in body
    assert '"delta": "lo "' in body
    assert '"delta": "World"' in body
    assert '"type": "finish"' in body
    assert '"finishReason": "stop"' in body


# --- api_key redaction in X-Provider-Config header ------------------------


@pytest.mark.asyncio
async def test_provider_config_header_redacts_keys_in_logs(
    async_app_client, monkeypatch, caplog
):
    """If X-Provider-Config JSON is malformed and contains an sk- key, the
    log warning from _extract_provider_config must redact it."""
    caplog.set_level(logging.DEBUG)

    # Send a header with malformed JSON that contains a fake sk- token.
    bad_header = '{"draft": {"api_key": "sk-leaked-in-header-xyz"'
    async with async_app_client.stream(
        "POST",
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Provider-Config": bad_header},
    ) as response:
        await response.aread()

    # The raw sk- token must NOT appear in any captured log record.
    for record in caplog.records:
        msg = record.getMessage()
        assert "sk-leaked-in-header-xyz" not in msg, (
            f"Raw API key leaked in log: {msg}"
        )


# --- POST /v1/chat/models (provider model list) ----------------------------


class _FakeModelsResponse:
    """Minimal stand-in for httpx.Response in the models endpoint."""

    def __init__(self, status_code: int = 200, json_body: dict | None = None):
        self.status_code = status_code
        self._json = json_body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=None, response=self  # type: ignore[arg-type]
            )

    def json(self):
        return self._json


@pytest.mark.asyncio
async def test_models_endpoint_returns_sorted_ids(async_app_client, monkeypatch):
    """POST /v1/chat/models returns the provider's model list, sorted."""

    async def _fake_get(self, url, **kwargs):
        assert "api.stepfun.com" in url
        assert kwargs["headers"]["Authorization"].startswith("Bearer ")
        return _FakeModelsResponse(
            200,
            {"data": [{"id": "step-3.7-flash"}, {"id": "step-3.5-flash"}, {"id": "step-3.5-flash"}]},
        )

    monkeypatch.setattr("httpx.AsyncClient.get", _fake_get)

    resp = await async_app_client.post(
        "/v1/chat/models",
        json={"api_base": "https://api.stepfun.com/step_plan/v1", "api_key": "sk-test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["models"] == ["step-3.5-flash", "step-3.7-flash"]
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_models_endpoint_rejects_bad_key(async_app_client, monkeypatch):
    """401 from provider surfaces as a friendly 401, not a raw 502."""

    async def _fake_get(self, url, **kwargs):
        return _FakeModelsResponse(401, {"error": {"message": "bad key"}})

    monkeypatch.setattr("httpx.AsyncClient.get", _fake_get)

    resp = await async_app_client.post(
        "/v1/chat/models",
        json={"api_base": "https://api.stepfun.com/step_plan/v1", "api_key": "sk-bad"},
    )
    assert resp.status_code == 401
    assert "API Key 无效" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_models_endpoint_rejects_empty_list(async_app_client, monkeypatch):
    """Provider returning no models → 502 with a clear message."""

    async def _fake_get(self, url, **kwargs):
        return _FakeModelsResponse(200, {"data": []})

    monkeypatch.setattr("httpx.AsyncClient.get", _fake_get)

    resp = await async_app_client.post(
        "/v1/chat/models",
        json={"api_base": "https://api.stepfun.com/step_plan/v1", "api_key": "sk-x"},
    )
    assert resp.status_code == 502
    assert "模型列表为空" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_models_endpoint_validates_ssrf(async_app_client):
    """Private/internal api_base must be rejected before any outbound call."""

    resp = await async_app_client.post(
        "/v1/chat/models",
        json={"api_base": "http://169.254.169.254/latest/meta-data", "api_key": "sk-x"},
    )
    assert resp.status_code == 400
    assert "Blocked" in resp.json()["detail"] or "不允许" in resp.json()["detail"]
