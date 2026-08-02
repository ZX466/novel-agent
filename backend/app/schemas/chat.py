"""Pydantic schemas for chat / BYOK provider configuration.

Three-stage BYOK design: each stage (draft / refine / evaluate) carries its
own api_base / api_key / model / extra_headers so users can route the three
pipeline stages to different providers (e.g. draft=local Ollama,
refine=DashScope, evaluate=OpenRouter Claude).

Wire format: a single `X-Provider-Config` header carries the JSON-serialized
ProviderConfig. The `api_key` fields are redacted on serialization to prevent
accidental leakage through logs / API responses / error tracebacks.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_serializer


class StageConfig(BaseModel):
    """Single-stage provider configuration (one of draft/refine/evaluate).

    Carried per-request inside the X-Provider-Config JSON header so the
    backend can call litellm with the user's own credentials for that
    specific pipeline stage instead of the .env defaults.
    """

    api_base: str = Field(
        ...,
        min_length=1,
        description="OpenAI-compatible /v1 endpoint URL, e.g. https://api.openai.com/v1",
    )
    api_key: str = Field(
        ...,
        min_length=1,
        description="API key for the chosen provider.",
    )
    model: str = Field(
        ...,
        min_length=1,
        description="Pure model name, e.g. gpt-4o-mini. Do NOT include provider prefix.",
    )
    extra_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Optional extra headers (e.g. OpenRouter HTTP-Referer / X-Title).",
    )

    @field_serializer("api_key")
    def _redact_api_key(self, v: str) -> str:
        """Redact API key on serialization to prevent leakage."""
        if not v:
            return v
        return v[:6] + "***" if len(v) > 6 else "***"


class ProviderConfig(BaseModel):
    """Three-stage BYOK container, with an optional embedding stage.

    Each field is independent — users may point draft/refine/evaluate at the
    same endpoint (one provider, three models) or at three completely
    different providers. When any stage is absent the backend falls back to
    the corresponding .env default for that stage.

    ``embedding`` is optional because most users only need the chat stages
    configured per-request; the embedding layer (RAG memory) can fall back
    to .env EMBEDDING_* credentials. When present, the embedding stage
    overrides the .env embedding settings for the duration of the request.
    """

    draft: StageConfig
    refine: StageConfig
    evaluate: StageConfig
    embedding: StageConfig | None = None
