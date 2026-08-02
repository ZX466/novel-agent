"""Embedding service — wraps OpenAI-compatible embedding API for the memory layer.

Uses openai.AsyncOpenAI directly (not litellm) to ensure the /embeddings
endpoint is called correctly. Auto-detects the actual embedding dimension
from the first API response, so any model works without manual config.

BYOK: if a StageConfig is supplied (api_base + api_key + model), it
overrides .env defaults.
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.llm.clients import _validate_api_base
from app.schemas.chat import StageConfig

logger = logging.getLogger(__name__)

# Auto-detected embedding dimension. None until the first successful call.
_actual_dim: int | None = None


def get_embedding_dim() -> int:
    """Return the actual embedding dimension (auto-detected or from config)."""
    return _actual_dim or settings.embedding_dim


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

    client = await _get_client(stage_config)
    model = _get_model(stage_config)

    # Don't pass `dimensions` — some providers (e.g. SiliconFlow BAAI/bge-m3)
    # reject it with code 20015. Let the API return its native dimension;
    # _maybe_truncate() adapts the vector to fit the pgvector column.
    resp = await client.embeddings.create(model=model, input=text)
    vec = list(resp.data[0].embedding)
    return _maybe_truncate(vec)


async def embed_batch(
    texts: list[str],
    *,
    stage_config: StageConfig | None = None,
) -> list[list[float]]:
    """Embed multiple texts in a single API call.

    Order is preserved. Empty strings are rejected with ValueError.
    """
    if not texts:
        return []
    if any(not t.strip() for t in texts):
        raise ValueError("embed_batch received empty string in list")

    client = await _get_client(stage_config)
    model = _get_model(stage_config)

    resp = await client.embeddings.create(model=model, input=texts)
    sorted_data = sorted(resp.data, key=lambda d: d.index)
    return [_maybe_truncate(list(d.embedding)) for d in sorted_data]
