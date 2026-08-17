"""FastAPI application entrypoint.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat as chat_router_module
from app.api import chapters as chapters_router_module
from app.api import characters as characters_router_module
from app.api import documents as documents_router_module
from app.api import health as health_router_module
from app.api import plot_events as plot_events_router_module
from app.api import retrieval as retrieval_router_module
from app.api import export as export_router_module
from app.api import stats as stats_router_module
from app.api import world_settings as world_settings_router_module
from app.config import settings
from app.core.redis import close_redis, get_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _redact_url(url: str) -> str:
    """Redact password from database/Redis URLs for safe logging.

    postgresql+asyncpg://user:***@host:5432/db
    redis://:***@host:16379/0
    """
    return re.sub(r"://([^:]*):([^@]+)@", r"://\1:***@", url)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes and tears down shared resources."""
    # Force litellm log level to INFO. litellm defaults to DEBUG which dumps
    # full request bodies (including user API keys) into logs. This must run
    # before any litellm.acompletion call. Override unconditionally so a user
    # setting LITELLM_LOG=DEBUG in .env cannot leak credentials via logs.
    os.environ["LITELLM_LOG"] = "INFO"
    logger.info("Starting Project11 backend...")
    logger.info("CORS origins: %s", settings.cors_origins)
    logger.info(
        "Pipeline: threshold=%.2f max_iters=%d",
        settings.pipeline_score_threshold,
        settings.pipeline_max_iters,
    )
    # Touch Redis so connection errors surface at startup, not first request.
    try:
        redis = get_redis()
        await redis.ping()
        logger.info("Redis connected: %s", _redact_url(settings.redis_url))
    except Exception:
        logger.exception("Redis ping failed at startup — continuing anyway")

    # Embedding config sanity check. Embeddings (RAG memory layer) use their
    # OWN credentials (EMBEDDING_*), separate from the BYOK chat stages. When
    # the key is empty, every ingestion silently no-ops and retrieval 404s —
    # surface it loudly at boot so it isn't buried in per-write warnings.
    if not settings.embedding_api_key or settings.embedding_api_key.startswith(
        "sk-your-"
    ):
        logger.error(
            "EMBEDDING_API_KEY is not configured (backend/.env). "
            "Memory ingestion and semantic retrieval will be DISABLED — "
            "set EMBEDDING_API_KEY / EMBEDDING_API_BASE / EMBEDDING_MODEL."
        )
    else:
        logger.info(
            "Embeddings: model=%s base=%s dim=%d",
            settings.embedding_model,
            settings.embedding_api_base,
            settings.embedding_dim,
        )

    yield

    logger.info("Shutting down Project11 backend...")
    await close_redis()


# Determine if we're in production (no docs exposure).
_is_production = os.environ.get("ENVIRONMENT", "").lower() == "production"

app = FastAPI(
    title="Project11 Backend",
    version="0.1.0",
    description="Three-stage LLM pipeline: DeepSeek draft -> Qwen refine -> Claude evaluate.",
    lifespan=lifespan,
    # Disable Swagger/OpenAPI docs in production to reduce attack surface.
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# CORS security: reject wildcard + credentials combination.
_cors_origins = settings.cors_origins
if "*" in _cors_origins:
    logger.warning(
        "CORS: wildcard '*' detected — disabling allow_credentials for safety. "
        "Set explicit origins in CORS_ORIGINS for production."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router_module.router)
app.include_router(chat_router_module.router)
app.include_router(documents_router_module.router)
app.include_router(chapters_router_module.router)
app.include_router(characters_router_module.router)
app.include_router(world_settings_router_module.router)
app.include_router(plot_events_router_module.router)
app.include_router(retrieval_router_module.router)
app.include_router(export_router_module.router)
app.include_router(stats_router_module.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all exception handler — returns a safe JSON error without
    leaking internal details (stack traces, file paths, SQL queries)."""
    logger.error("Unhandled exception on %s %s: %s: %s",
                 request.method, request.url.path, type(exc).__name__, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
