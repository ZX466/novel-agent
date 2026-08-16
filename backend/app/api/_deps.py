"""Reusable FastAPI dependency helpers shared across API routers."""
from __future__ import annotations

import json
import logging
import hashlib
import secrets
import time

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.redis import get_redis
from app.schemas.chat import StageConfig
from app.services.document import DocumentNotFound, get_document

logger = logging.getLogger(__name__)


async def require_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    """Validate the X-API-Key header is present and non-empty after stripping."""
    key = x_api_key.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or empty X-API-Key header",
        )
    if not settings.api_keys:
        logger.error("X-API-Key authentication is not configured")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API authentication is not configured")
    if not any(secrets.compare_digest(key, allowed) for allowed in settings.api_keys):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return key


def owner_key_hash(api_key: str) -> str:
    """Return a non-reversible tenant identifier for resource ownership."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def enforce_chat_rate_limit(api_key: str = Depends(require_api_key)) -> str:
    """Apply a Redis-backed per-key fixed-window limit to costly chat calls."""
    window_seconds = 60
    window = int(time.time() // window_seconds)
    key = f"rate-limit:chat:{owner_key_hash(api_key)}:{window}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
    except Exception as exc:
        logger.error("Chat rate limiter unavailable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Request protection is temporarily unavailable",
        )
    if count > settings.chat_rate_limit_per_minute:
        retry_after = window_seconds - (int(time.time()) % window_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many chat requests",
            headers={"Retry-After": str(retry_after)},
        )
    return api_key


async def enforce_chat_test_rate_limit(api_key: str = Depends(require_api_key)) -> str:
    """Apply the stricter connection-test quota without duplicating limiter code."""
    window_seconds = 60
    window = int(time.time() // window_seconds)
    key = f"rate-limit:chat-test:{owner_key_hash(api_key)}:{window}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
    except Exception as exc:
        logger.error("Connection-test rate limiter unavailable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Request protection is temporarily unavailable",
        )
    if count > settings.chat_test_rate_limit_per_minute:
        retry_after = window_seconds - (int(time.time()) % window_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many connection-test requests",
            headers={"Retry-After": str(retry_after)},
        )
    return api_key


async def load_parent(session: AsyncSession, doc_id: int, *, owner_hash: str | None = None) -> None:
    """Ensure the parent document exists; raises 404 if not found."""
    try:
        await get_document(session, doc_id, owner_key_hash=owner_hash)
    except DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")


async def extract_embedding_stage(
    x_provider_config: str | None = Header(None, alias="X-Provider-Config"),
) -> StageConfig | None:
    """Extract the embedding BYOK stage from X-Provider-Config header, if any.

    Returns None when the header is absent, malformed, or has no embedding
    stage configured -- callers then fall back to .env EMBEDDING_* creds.
    """
    if not x_provider_config:
        return None
    try:
        data = json.loads(x_provider_config)
        emb = data.get("embedding")
        if (
            emb
            and isinstance(emb, dict)
            and emb.get("api_base")
            and emb.get("api_key")
            and emb.get("model")
        ):
            return StageConfig(**emb)
    except (json.JSONDecodeError, Exception):
        logger.debug("deps: malformed X-Provider-Config header, ignoring")
    return None
