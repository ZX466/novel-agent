"""Async Redis client.

Initialized lazily on first use; lifespan in main.py calls close() on shutdown.
"""
from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    """Returns the singleton async Redis client. Connects lazily."""
    global _redis
    if _redis is None:
        _redis = from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """Closes the Redis connection pool. Called on app shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
