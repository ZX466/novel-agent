"""Reusable FastAPI dependency helpers shared across API routers."""
from __future__ import annotations

import json
import logging

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import StageConfig
from app.services.document import DocumentNotFound, get_document

logger = logging.getLogger(__name__)


async def require_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    """Validate the X-API-Key header is present and non-empty after stripping."""
    if not x_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or empty X-API-Key header",
        )
    return x_api_key.strip()


async def load_parent(session: AsyncSession, doc_id: int) -> None:
    """Ensure the parent document exists; raises 404 if not found."""
    try:
        await get_document(session, doc_id)
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
