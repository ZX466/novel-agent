"""Unit tests for app.llm.clients — BYOK kwargs, SSRF validation, key redaction."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.llm import clients
from app.llm.clients import APIBaseNotAllowed
from app.schemas.chat import ProviderConfig, StageConfig


def _make_stage(
    *,
    api_base: str = "https://api.openai.com/v1",
    api_key: str = "sk-test-abc123",
    model: str = "gpt-4o-mini",
    extra_headers: dict[str, str] | None = None,
) -> StageConfig:
    return StageConfig(
        api_base=api_base,
        api_key=api_key,
        model=model,
        extra_headers=extra_headers or {},
    )


def _make_cfg(
    *,
    draft: StageConfig | None = None,
    refine: StageConfig | None = None,
    evaluate: StageConfig | None = None,
) -> ProviderConfig:
    """Build a ProviderConfig with the given stages (defaults to a generic one for all three)."""
    return ProviderConfig(
        draft=draft or _make_stage(),
        refine=refine or _make_stage(),
        evaluate=evaluate or _make_stage(),
    )


def _mock_response() -> SimpleNamespace:
    """Minimal litellm-like response object."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello"),
                delta=SimpleNamespace(content=None),
            )
        ]
    )


# --- BYOK kwarg forwarding --------------------------------------------------


@pytest.mark.asyncio
async def test_draft_forwards_byok_kwargs():
    mock_acompletion = AsyncMock(return_value=_mock_response())
    with patch.object(clients, "acompletion", mock_acompletion):
        stage = _make_stage(extra_headers={"X-Title": "Project11"})
        await clients.draft(
            [{"role": "user", "content": "hi"}], stage_config=stage
        )
    assert mock_acompletion.call_count == 1
    kwargs = mock_acompletion.call_args.kwargs
    assert kwargs["model"] == "openai/gpt-4o-mini"
    assert kwargs["api_key"] == "sk-test-abc123"
    assert kwargs["api_base"] == "https://api.openai.com/v1"
    assert kwargs["extra_headers"] == {"X-Title": "Project11"}
    assert kwargs["temperature"] == 0.7
    assert kwargs["stream"] is False


@pytest.mark.asyncio
async def test_refine_forwards_byok_kwargs():
    mock_acompletion = AsyncMock(return_value=_mock_response())
    with patch.object(clients, "acompletion", mock_acompletion):
        stage = _make_stage()
        await clients.refine(
            [{"role": "user", "content": "hi"}], stream=True, stage_config=stage
        )
    kwargs = mock_acompletion.call_args.kwargs
    assert kwargs["model"] == "openai/gpt-4o-mini"
    assert kwargs["temperature"] == 0.4
    assert kwargs["stream"] is True
    # extra_headers should be omitted entirely when empty (not an empty dict).
    assert "extra_headers" not in kwargs


@pytest.mark.asyncio
async def test_evaluate_forwards_byok_kwargs():
    mock_acompletion = AsyncMock(return_value=_mock_response())
    with patch.object(clients, "acompletion", mock_acompletion):
        stage = _make_stage()
        await clients.evaluate(
            [{"role": "user", "content": "hi"}], stage_config=stage
        )
    kwargs = mock_acompletion.call_args.kwargs
    assert kwargs["model"] == "openai/gpt-4o-mini"
    assert kwargs["temperature"] == 0.0
    assert kwargs["stream"] is False
    assert kwargs["max_tokens"] == 512


@pytest.mark.asyncio
async def test_draft_uses_draft_stage_independent_of_others():
    """draft() must use the draft stage's credentials, not refine/evaluate."""
    mock_acompletion = AsyncMock(return_value=_mock_response())
    with patch.object(clients, "acompletion", mock_acompletion):
        draft_stage = _make_stage(
            api_base="https://draft.example.com/v1",
            api_key="sk-draft-key",
            model="draft-model",
        )
        await clients.draft(
            [{"role": "user", "content": "hi"}], stage_config=draft_stage
        )
    kwargs = mock_acompletion.call_args.kwargs
    assert kwargs["api_base"] == "https://draft.example.com/v1"
    assert kwargs["api_key"] == "sk-draft-key"
    assert kwargs["model"] == "openai/draft-model"


# --- .env fallback ----------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_falls_back_to_env_when_no_stage_config(monkeypatch):
    """Without stage_config, draft must use settings.deepseek_* fields."""
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "env-deepseek-key")
    monkeypatch.setattr(settings, "deepseek_model", "deepseek-v4-flash")

    mock_acompletion = AsyncMock(return_value=_mock_response())
    with patch.object(clients, "acompletion", mock_acompletion):
        await clients.draft([{"role": "user", "content": "hi"}])
    kwargs = mock_acompletion.call_args.kwargs
    assert kwargs["model"] == "deepseek/deepseek-v4-flash"
    assert kwargs["api_key"] == "env-deepseek-key"
    assert "api_base" not in kwargs or kwargs.get("api_base") is None


@pytest.mark.asyncio
async def test_evaluate_falls_back_to_env_relay(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "relay_api_key", "env-relay-key")
    monkeypatch.setattr(settings, "relay_api_base", "https://relay.example.com/v1")
    monkeypatch.setattr(settings, "relay_claude_model", "claude-sonnet-4-5")

    mock_acompletion = AsyncMock(return_value=_mock_response())
    with patch.object(clients, "acompletion", mock_acompletion):
        await clients.evaluate([{"role": "user", "content": "hi"}])
    kwargs = mock_acompletion.call_args.kwargs
    assert kwargs["model"] == "openai/claude-sonnet-4-5"
    assert kwargs["api_key"] == "env-relay-key"
    assert kwargs["api_base"] == "https://relay.example.com/v1"


# --- SSRF validation --------------------------------------------------------


def test_validate_api_base_rejects_hostname_resolving_to_private_ip(monkeypatch):
    monkeypatch.setattr(
        clients.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("169.254.169.254", 0))],
    )
    with pytest.raises(APIBaseNotAllowed, match="Blocked internal address"):
        clients._validate_api_base("https://metadata.google.internal/v1")


def test_validate_api_base_rejects_cloud_metadata():
    with pytest.raises(APIBaseNotAllowed, match="Blocked internal address"):
        clients._validate_api_base("http://169.254.169.254/v1")


def test_validate_api_base_rejects_rfc1918_10():
    with pytest.raises(APIBaseNotAllowed):
        clients._validate_api_base("http://10.0.0.1/v1")


def test_validate_api_base_rejects_rfc1918_192():
    with pytest.raises(APIBaseNotAllowed):
        clients._validate_api_base("http://192.168.1.1/v1")


def test_validate_api_base_rejects_rfc1918_172():
    with pytest.raises(APIBaseNotAllowed):
        clients._validate_api_base("http://172.16.0.1/v1")


def test_validate_api_base_rejects_non_http_scheme():
    with pytest.raises(APIBaseNotAllowed, match="Unsupported URL scheme"):
        clients._validate_api_base("ftp://example.com/v1")


def test_validate_api_base_rejects_empty_host():
    with pytest.raises(APIBaseNotAllowed, match="no host"):
        clients._validate_api_base("http:///v1")


def test_validate_api_base_allows_public_domain():
    # Should not raise.
    clients._validate_api_base("https://api.openai.com/v1")


def test_validate_api_base_allows_localhost_by_default():
    # Should not raise when BYOK_ALLOW_LOCAL_API_BASE is enabled.
    from app.config import settings
    from unittest.mock import patch as _p
    with _p.object(settings, "byok_allow_local_api_base", True):
        clients._validate_api_base("http://localhost:11434/v1")
        clients._validate_api_base("http://127.0.0.1:8080/v1")


def test_validate_api_base_rejects_localhost_when_disabled(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "byok_allow_local_api_base", False)
    with pytest.raises(APIBaseNotAllowed, match="Local API base is disabled"):
        clients._validate_api_base("http://localhost:11434/v1")


def test_validate_api_base_rejects_loopback_ip_when_disabled(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "byok_allow_local_api_base", False)
    with pytest.raises(APIBaseNotAllowed, match="Local API base is disabled"):
        clients._validate_api_base("http://127.0.0.1:8080/v1")


def test_byok_kwargs_raises_on_ssrf():
    """StageConfig with SSRF api_base must raise before calling litellm."""
    stage = _make_stage(api_base="http://169.254.169.254/v1")
    with pytest.raises(APIBaseNotAllowed, match="Blocked internal address"):
        clients._byok_kwargs(stage)


# --- API key redaction ------------------------------------------------------


def test_redact_key_redacts_bearer_and_url_credentials():
    message = "Bearer eyJhbGciOiJIUzI1NiJ9.secret.sig https://user:password@example.com/v1"
    redacted = clients._redact_key(message)
    assert "eyJhbGci" not in redacted
    assert "password" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_key_redacts_sk_token():
    assert clients._redact_key("error: sk-abc123xyz happened") == "error: [REDACTED] happened"


def test_redact_key_handles_empty():
    assert clients._redact_key("") == ""


def test_redact_key_no_match_returns_input():
    assert clients._redact_key("no secrets here") == "no secrets here"


def test_redact_key_redacts_multiple_tokens():
    out = clients._redact_key("k1=sk-aaa-bbb k2=sk-ccc-ddd")
    assert "sk-aaa" not in out
    assert "sk-ccc" not in out
    assert out.count("[REDACTED]") == 2


# --- StageConfig / ProviderConfig serialization redaction ---------------------------------


def test_stage_config_serializes_api_key_as_redacted():
    stage = _make_stage(api_key="sk-supersecret123")
    data = stage.model_dump()
    # The redacted form appears in serialized output, not the raw key.
    assert "sk-supersecret123" not in data["api_key"]
    # v[:6] + "***" — "sk-sup" is the first 6 chars of "sk-supersecret123".
    assert data["api_key"] == "sk-sup***"
    assert data["api_key"].endswith("***")


def test_provider_config_serializes_all_three_stages_redacted():
    """All three stages' api_keys must be redacted on serialization."""
    cfg = ProviderConfig(
        draft=_make_stage(api_key="sk-draft-secret123"),
        refine=_make_stage(api_key="sk-refine-secret123"),
        evaluate=_make_stage(api_key="sk-eval-secret123"),
    )
    data = cfg.model_dump()
    assert data["draft"]["api_key"] == "sk-dra***"
    assert data["refine"]["api_key"] == "sk-ref***"
    assert data["evaluate"]["api_key"] == "sk-eva***"
    # Raw keys must not leak anywhere in the dump.
    dumped_json = cfg.model_dump_json()
    assert "sk-draft-secret123" not in dumped_json
    assert "sk-refine-secret123" not in dumped_json
    assert "sk-eval-secret123" not in dumped_json


# --- ProviderConfig validation ---------------------------------------------


def test_provider_config_requires_all_three_stages():
    """Missing any stage must raise ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProviderConfig(draft=_make_stage(), refine=_make_stage())  # no evaluate
    with pytest.raises(ValidationError):
        ProviderConfig(draft=_make_stage(), evaluate=_make_stage())  # no refine
    with pytest.raises(ValidationError):
        ProviderConfig(refine=_make_stage(), evaluate=_make_stage())  # no draft


def test_provider_config_accepts_three_different_providers():
    """Three stages may point at completely different providers."""
    cfg = ProviderConfig(
        draft=_make_stage(
            api_base="http://localhost:11434/v1",
            api_key="ollama-no-key",
            model="llama3.1",
        ),
        refine=_make_stage(
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-dashscope-xxx",
            model="qwen-max",
        ),
        evaluate=_make_stage(
            api_base="https://openrouter.ai/api/v1",
            api_key="sk-or-xxx",
            model="anthropic/claude-3.5-sonnet",
        ),
    )
    assert cfg.draft.model == "llama3.1"
    assert cfg.refine.model == "qwen-max"
    assert cfg.evaluate.model == "anthropic/claude-3.5-sonnet"
