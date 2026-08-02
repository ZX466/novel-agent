"""Unit tests for app.llm.embedding.

Production uses `openai.AsyncOpenAI` directly (NOT litellm). The seam these
tests patch is `embedding._get_client`, which returns the AsyncOpenAI client;
the fake client exposes only `.embeddings.create` (the sole method used).

Verifies:
  - .env credentials flow through when no stage_config supplied
  - BYOK stage_config overrides .env credentials
  - the RAW model name is sent (the `openai/` prefix is litellm-only)
  - `dimensions` is never sent (SiliconFlow BAAI/bge-m3 rejects it, code 20015)
  - SSRF rejection reuses _validate_api_base
  - empty input raises ValueError
  - batch call preserves order and uses `.index` to sort
  - _maybe_truncate pads / truncates / passes through, and updates _actual_dim
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.llm import embedding
from app.schemas.chat import StageConfig


class _FakeEmbeddingItem:
    """One entry of an OpenAI embeddings response.

    Production reads these by ATTRIBUTE (`d.index`, `d.embedding`), so a
    dict would raise AttributeError -- this mirrors the real SDK objects.
    """

    def __init__(self, index: int, emb: list[float]):
        self.index = index
        self.embedding = emb


def _mock_embedding_response(values: list[list[float]]) -> SimpleNamespace:
    """Build an OpenAI-like CreateEmbeddingResponse with len(values) entries."""
    return SimpleNamespace(
        data=[_FakeEmbeddingItem(i, vec) for i, vec in enumerate(values)]
    )


def _make_stage(
    *,
    api_base: str = "https://api.openai.com/v1",
    api_key: str = "sk-test-abc123",
    model: str = "text-embedding-3-small",
) -> StageConfig:
    return StageConfig(api_base=api_base, api_key=api_key, model=model)


def _client_with_create(resp):
    """Fake AsyncOpenAI client whose .embeddings.create returns *resp*."""
    return SimpleNamespace(
        embeddings=SimpleNamespace(create=AsyncMock(return_value=resp))
    )


# ---------------------------------------------------------------------------
# embed_text tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_text_uses_env_credentials(monkeypatch):
    """Without stage_config, embed_text reads settings.* and calls the
    OpenAI client with the correct model, input, and no `dimensions` kwarg."""
    monkeypatch.setattr(settings, "embedding_api_key", "env-emb-key")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-3-small")
    monkeypatch.setattr(settings, "embedding_api_base", "https://api.openai.com/v1")
    monkeypatch.setattr(settings, "embedding_dim", 3)

    fake_resp = _mock_embedding_response([[0.1, 0.2, 0.3]])
    fake_client = _client_with_create(fake_resp)
    with patch.object(embedding, "_get_client", return_value=fake_client) as mock_gc:
        vec = await embedding.embed_text("hello")

    assert vec == [0.1, 0.2, 0.3]
    # _get_client was called with stage_config=None (env path).
    mock_gc.assert_awaited_once_with(None)
    create_kw = fake_client.embeddings.create.call_args.kwargs
    # AsyncOpenAI receives the RAW model name -- no 'openai/' prefix.
    assert create_kw["model"] == "text-embedding-3-small"
    assert create_kw["input"] == "hello"
    # dimensions is deliberately NOT sent -- see embedding.py:99-101.
    assert "dimensions" not in create_kw


@pytest.mark.asyncio
async def test_embed_text_forwards_byok_kwargs(monkeypatch):
    """With a BYOK stage_config the model name is forwarded verbatim."""
    monkeypatch.setattr(settings, "embedding_dim", 1)

    fake_resp = _mock_embedding_response([[0.5]])
    fake_client = _client_with_create(fake_resp)
    stage = _make_stage(
        api_base="https://embed.example.com/v1",
        api_key="sk-byok-embed",
        model="voyage-large-2",
    )
    with patch.object(embedding, "_get_client", return_value=fake_client):
        await embedding.embed_text("hello", stage_config=stage)

    create_kw = fake_client.embeddings.create.call_args.kwargs
    # Raw model name -- no 'openai/' prefix.
    assert create_kw["model"] == "voyage-large-2"


@pytest.mark.asyncio
async def test_embed_text_rejects_empty_input():
    with pytest.raises(ValueError, match="empty"):
        await embedding.embed_text("")
    with pytest.raises(ValueError, match="empty"):
        await embedding.embed_text("   ")


@pytest.mark.asyncio
async def test_embed_text_rejects_ssrf_api_base():
    """SSRF protection from app.llm.clients._validate_api_base applies."""
    with pytest.raises(ValueError, match="Blocked internal address"):
        stage = _make_stage(api_base="http://169.254.169.254/v1")
        await embedding.embed_text("x", stage_config=stage)


# ---------------------------------------------------------------------------
# embed_batch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_batch_preserves_order(monkeypatch):
    """Provider may return embeddings out of order -- sort by .index."""
    monkeypatch.setattr(settings, "embedding_dim", 1)

    fake_resp = _mock_embedding_response([[0.1], [0.2], [0.3]])
    fake_client = _client_with_create(fake_resp)
    with patch.object(embedding, "_get_client", return_value=fake_client):
        vecs = await embedding.embed_batch(["a", "b", "c"])
    assert vecs == [[0.1], [0.2], [0.3]]


@pytest.mark.asyncio
async def test_embed_batch_sorts_unsorted_response(monkeypatch):
    """Provider returns embeddings out of order -- must sort by index."""
    monkeypatch.setattr(settings, "embedding_dim", 1)

    items = [_FakeEmbeddingItem(2, [0.3]), _FakeEmbeddingItem(0, [0.1]),
             _FakeEmbeddingItem(1, [0.2])]
    unordered = SimpleNamespace(data=items)
    fake_client = _client_with_create(unordered)
    with patch.object(embedding, "_get_client", return_value=fake_client):
        vecs = await embedding.embed_batch(["a", "b", "c"])
    assert vecs == [[0.1], [0.2], [0.3]]


@pytest.mark.asyncio
async def test_embed_batch_empty_input_returns_empty():
    result = await embedding.embed_batch([])
    assert result == []


@pytest.mark.asyncio
async def test_embed_batch_rejects_empty_string_in_list():
    with pytest.raises(ValueError, match="empty"):
        await embedding.embed_batch(["a", "", "c"])


# ---------------------------------------------------------------------------
# _maybe_truncate tests -- the auto-dimension-adaptation logic
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_actual_dim():
    """Reset the module-global _actual_dim between tests so ordering
    doesn't leak state."""
    embedding._actual_dim = None
    yield
    embedding._actual_dim = None


def test_maybe_truncate_shorter_vector_is_zero_padded(monkeypatch):
    """A vector shorter than embedding_dim is zero-padded, original values
    preserved at the front."""
    monkeypatch.setattr(settings, "embedding_dim", 5)
    result = embedding._maybe_truncate([0.1, 0.2, 0.3])
    assert len(result) == 5
    assert result[:3] == [0.1, 0.2, 0.3]
    assert result[3:] == [0.0, 0.0]
    assert embedding._actual_dim == 3


def test_maybe_truncate_longer_vector_is_truncated(monkeypatch):
    """A vector longer than embedding_dim is truncated to exactly that
    length."""
    monkeypatch.setattr(settings, "embedding_dim", 3)
    result = embedding._maybe_truncate([0.1, 0.2, 0.3, 0.4, 0.5])
    assert result == [0.1, 0.2, 0.3]
    assert embedding._actual_dim == 5


def test_maybe_truncate_equal_vector_returned_unchanged(monkeypatch):
    """A vector already at the right dimension is returned as-is."""
    monkeypatch.setattr(settings, "embedding_dim", 3)
    vec = [0.1, 0.2, 0.3]
    result = embedding._maybe_truncate(vec)
    assert result is vec
    assert embedding._actual_dim == 3


def test_get_embedding_dim_reflects_last_actual_dim(monkeypatch):
    """After _maybe_truncate runs, get_embedding_dim() reports the
    auto-detected dimension, not the configured default."""
    monkeypatch.setattr(settings, "embedding_dim", 1536)
    assert embedding.get_embedding_dim() == 1536  # nothing detected yet

    embedding._maybe_truncate([1.0, 2.0, 3.0])
    assert embedding.get_embedding_dim() == 3  # last detected actual dim
