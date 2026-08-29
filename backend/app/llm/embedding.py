"""Embedding service — wraps OpenAI-compatible embedding API for the memory layer.

Uses openai.AsyncOpenAI directly (not litellm) to ensure the /embeddings
endpoint is called correctly. Auto-detects the actual embedding dimension
from the first API response, so any model works without manual config.

BYOK: if a StageConfig is supplied (api_base + api_key + model), it
overrides .env defaults.

Caching: identical (text, model, identity) inputs hit an in-memory TTL cache,
so repeated prompts (e.g. the same RAG query across pipeline runs, or a chapter
summary re-embedded on every edit) skip the LLM call entirely. The cache key
is ``identity | model | sha256(text)`` where ``identity`` is the SHA-256 of the
BYOK api_base + API key (env defaults when no stage_config is supplied) — so
two tenants using the same model never share vectors. Raw query text and raw
API keys are never retained in memory (embeddings of user prompts may contain
story premises / secrets).
"""
from __future__ import annotations

import hashlib
import logging
import time

from app.config import settings
from app.llm.clients import _validate_api_base
from app.schemas.chat import StageConfig

logger = logging.getLogger(__name__)

# Auto-detected embedding dimension. None until the first successful call.
_actual_dim: int | None = None

# --- In-memory embedding cache ----------------------------------------------
# Small, bounded, TTL-based. Embeds are immutable per (text, model), so a
# plain dict keyed by hash is sufficient — no LRU machinery needed.
_EMBED_CACHE_TTL_SECONDS = 3600
_EMBED_CACHE_MAX_ENTRIES = 4096

_embed_cache: dict[str, tuple[float, list[float]]] = {}


def get_embedding_dim() -> int:
    """Return the actual embedding dimension (auto-detected or from config)."""
    return _actual_dim or settings.embedding_dim


def clear_embedding_cache() -> None:
    """Drop all cached embeddings.

    Call when the embedding model or EMBEDDING_DIM changes at runtime so
    stale vectors (cached under the old model / truncated to the old dim)
    are not reused.
    """
    _embed_cache.clear()


def _cache_identity(stage_config: StageConfig | None) -> str:
    """Irreversible identity fingerprint of the embedding endpoint + key.

    api_base and the API key are hashed together so that two tenants pointing
    at the same model never share cached vectors (a cross-tenant retrieval
    leak). The raw API key is never part of, or derivable from, the key.
    """
    api_base = (stage_config.api_base if stage_config else settings.embedding_api_base) or ""
    api_key = (stage_config.api_key if stage_config else settings.embedding_api_key) or ""
    return hashlib.sha256(f"{api_base}\n{api_key}".encode("utf-8")).hexdigest()


def _embed_cache_key(text: str, model: str, stage_config: StageConfig | None) -> str:
    """Cache key: tenant identity + model + SHA-256 of the text.

    Never contains the raw text or the raw API key — only irreversible hashes.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{_cache_identity(stage_config)}|{model}|{digest}"


def _cache_get(key: str) -> list[float] | None:
    """Return the cached vector for `key`, or None on miss / TTL expiry."""
    entry = _embed_cache.get(key)
    if entry is None:
        return None
    stored_at, vec = entry
    if time.monotonic() - stored_at > _EMBED_CACHE_TTL_SECONDS:
        _embed_cache.pop(key, None)
        return None
    return vec


def _cache_set(key: str, vec: list[float]) -> None:
    """Store a *copy* of `vec` under `key`, evicting the oldest entry when
    over budget. Copying keeps callers who mutate their returned vector from
    corrupting the shared cache entry."""
    if len(_embed_cache) >= _EMBED_CACHE_MAX_ENTRIES:
        _embed_cache.pop(next(iter(_embed_cache)), None)
    _embed_cache[key] = (time.monotonic(), list(vec))


async def _get_client(stage_config: StageConfig | None):
    """Build an AsyncOpenAI client from stage_config or .env defaults."""
    import openai as openai_lib

    if stage_config is not None:
        _validate_api_base(stage_config.api_base)
        return openai_lib.AsyncOpenAI(
            api_key=stage_config.api_key,
            base_url=stage_config.api_base,
            timeout=60,
        )
    return openai_lib.AsyncOpenAI(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_api_base,
        timeout=60,
    )


def _get_model(stage_config: StageConfig | None) -> str:
    return stage_config.model if stage_config else settings.embedding_model


def _maybe_truncate(vec: list[float]) -> list[float]:
    """Pad or truncate a vector to match settings.embedding_dim.

    If the model returns fewer dimensions than the pgvector column expects,
    we zero-pad. If it returns more, we truncate. This is a lossless
    operation for padding (zeros don't carry information) and a best-effort
    fallback for truncation.
    """
    global _actual_dim
    _actual_dim = len(vec)
    target = settings.embedding_dim

    if len(vec) == target:
        return vec
    if len(vec) > target:
        logger.warning(
            "embedding: truncating vector from %d to %d dims (EMBEDDING_DIM=%d). "
            "Consider setting EMBEDDING_DIM=%d in .env for lossless storage.",
            len(vec), target, target, len(vec),
        )
        return vec[:target]
    # Fewer dims than expected — pad with zeros.
    logger.warning(
        "embedding: padding vector from %d to %d dims (EMBEDDING_DIM=%d). "
        "Consider setting EMBEDDING_DIM=%d in .env for optimal storage.",
        len(vec), target, target, len(vec),
    )
    return vec + [0.0] * (target - len(vec))


async def embed_text(
    text: str,
    *,
    stage_config: StageConfig | None = None,
) -> list[float]:
    """Return the embedding vector for a single text input.

    Auto-detects the actual dimension from the API response. If it
    doesn't match settings.embedding_dim, the vector is zero-padded
    or truncated to fit the pgvector column.
    """
    if not text or not text.strip():
        raise ValueError("embed_text received empty input")

    model = _get_model(stage_config)
    key = _embed_cache_key(text, model, stage_config)
    cached = _cache_get(key)
    if cached is not None:
        return list(cached)  # copy — callers must never mutate the shared vector

    client = await _get_client(stage_config)

    # Don't pass `dimensions` — some providers (e.g. SiliconFlow BAAI/bge-m3)
    # reject it with code 20015. Let the API return its native dimension;
    # _maybe_truncate() adapts the vector to fit the pgvector column.
    resp = await client.embeddings.create(model=model, input=text)
    vec = _maybe_truncate(list(resp.data[0].embedding))
    _cache_set(key, vec)
    return vec


async def embed_batch(
    texts: list[str],
    *,
    stage_config: StageConfig | None = None,
) -> list[list[float]]:
    """Embed multiple texts, reusing cached embeddings per text.

    Order is preserved. Empty strings are rejected with ValueError. Only
    texts that are not already cached are sent to the API (one call for the
    miss set).
    """
    if not texts:
        return []
    if any(not t.strip() for t in texts):
        raise ValueError("embed_batch received empty string in list")

    model = _get_model(stage_config)
    keys = [_embed_cache_key(t, model, stage_config) for t in texts]
    cached = [_cache_get(k) for k in keys]

    miss_indices = [i for i, vec in enumerate(cached) if vec is None]
    if miss_indices:
        client = await _get_client(stage_config)
        resp = await client.embeddings.create(
            model=model, input=[texts[i] for i in miss_indices],
        )
        sorted_data = sorted(resp.data, key=lambda d: d.index)
        miss_vecs = [_maybe_truncate(list(d.embedding)) for d in sorted_data]
        for i, vec in zip(miss_indices, miss_vecs):
            _cache_set(keys[i], vec)
            cached[i] = vec

    return [list(vec) for vec in cached]
