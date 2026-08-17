"""Unified error response schemas for the API layer."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standardized error payload returned by REST and SSE error events."""

    detail: str = Field(..., description="Human-readable error message in Chinese.")
    code: str | None = Field(default=None, description="Machine-readable error code.")
