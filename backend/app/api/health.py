"""Health check endpoint."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/v1/health")
async def health() -> dict:
    """Liveness probe. Returns 200 if the process is up."""
    return {"status": "ok"}
