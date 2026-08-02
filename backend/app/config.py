"""Application configuration loaded from environment variables.

LLM credentials MAY be supplied via env vars (loaded from .env at process
start) as a fallback for the BYOK (Bring Your Own Key) flow. The preferred
path is per-request credentials via X-Provider-* headers, which override
.env defaults. Do NOT call os.environ[...] = ... at runtime — litellm reads
certain keys at import time and runtime mutation is unreliable.
"""
from __future__ import annotations

from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed app configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- BYOK (Bring Your Own Key) controls ---
    byok_fallback_to_env: bool = Field(
        default=True,
        description=(
            "If true, fall back to .env LLM credentials when the request "
            "carries no X-Provider-* headers. Set to false to require BYOK "
            "credentials on every request."
        ),
    )
    byok_allow_local_api_base: bool = Field(
        default=False,
        description=(
            "Allow api_base pointing to localhost / 127.0.0.1 / ::1. "
            "Disabled by default to prevent SSRF. Set to true for local "
            "development only."
        ),
    )

    # --- DeepSeek (draft) — optional, used as .env fallback only ---
    deepseek_api_key: str = Field(default="", description="DeepSeek API key (BYOK fallback)")
    deepseek_model: str = Field(
        default="deepseek-v4-flash",
        description="DeepSeek model name. deepseek-chat was retired 2026-07-24.",
    )

    # --- Qwen / DashScope (refine) — optional, used as .env fallback only ---
    dashscope_api_key: str = Field(default="", description="DashScope (Qwen) API key (BYOK fallback)")
    dashscope_api_base: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="DashScope OpenAI-compatible endpoint.",
    )
    dashscope_model: str = Field(default="qwen-max")

    # --- Claude via relay (evaluate) — optional, used as .env fallback only ---
    relay_api_key: str = Field(default="", description="Relay (中转) API key for Claude (BYOK fallback)")
    relay_api_base: str = Field(default="", description="Relay /v1 endpoint URL (BYOK fallback)")
    relay_claude_model: str = Field(
        default="claude-sonnet-4-5-20250929",
        description="Claude Sonnet model name as supported by the relay.",
    )

    # --- Embedding (memory layer) — used for RAG over chapters/characters/lore ---
    embedding_api_key: str = Field(
        default="",
        description="API key for the embedding provider (OpenAI-compatible).",
    )
    embedding_api_base: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI-compatible /v1 endpoint for embeddings.",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="LiteLLM model name. Use 'openai/text-embedding-3-small' format.",
    )
    embedding_dim: int = Field(
        default=1536,
        ge=1,
        description="Embedding dimension. MUST match the vector(N) column in migrations.",
    )

    # --- Database ---
    database_url: str = Field(..., description="postgresql+asyncpg://...")

    # --- Redis ---
    redis_url: str = Field(default="redis://:project11-redis@localhost:16379/0")

    # --- CORS ---
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:7421"],
        description="JSON array of allowed frontend origins.",
    )

    # --- Pipeline tuning ---
    pipeline_score_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    pipeline_max_iters: int = Field(default=3, ge=1, le=10)
    pipeline_multi_dim_eval: bool = Field(
        default=True,
        description=(
            "When true, the /v1/chat endpoint constructs a ReviewMatrixRunner "
            "and the evaluate node runs multi-dimensional parallel evaluation "
            "instead of the single llm_evaluate path."
        ),
    )
    pipeline_eval_concurrency: int = Field(
        default=1,
        ge=1,
        le=8,
        description=(
            "Max concurrent LLM calls during multi-dimensional evaluation. "
            "Low-rate-limit providers (e.g. mimo-v2.5) must stay at 1 to "
            "avoid 429s; raise for high-throughput relays. Each evaluate "
            "step fires this many parallel calls per refine iteration."
        ),
    )

    # --- BYOK quick setup templates ---
    byok_presets: dict[str, dict[str, dict[str, str]]] = Field(
        default_factory=lambda: {
            "deepseek_qwen_claude": {
                "draft": {"api_base": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash"},
                "refine": {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-max"},
                "evaluate": {"api_base": "https://api.openai.com/v1", "model": "claude-sonnet-4-5-20250929"},
            },
            "all_openai": {
                "draft": {"api_base": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
                "refine": {"api_base": "https://api.openai.com/v1", "model": "gpt-4o"},
                "evaluate": {"api_base": "https://api.openai.com/v1", "model": "gpt-4o"},
            },
            "all_dashscope": {
                "draft": {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
                "refine": {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-max"},
                "evaluate": {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-max"},
            },
        },
    )

    # Recommended models per stage for the frontend dropdown
    recommended_models: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "draft": ["deepseek-v4-flash", "gpt-4o-mini", "qwen-plus", "claude-haiku-4-5-20251001"],
            "refine": ["qwen-max", "gpt-4o", "deepseek-v4-flash", "claude-sonnet-5-20250514"],
            "evaluate": ["claude-sonnet-4-5-20250929", "gpt-4o", "qwen-max", "deepseek-v4-flash"],
            "embedding": ["text-embedding-3-small", "text-embedding-v4", "text-embedding-3-large"],
        },
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v):
        """Accept JSON-encoded list or comma-separated string."""
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json
                return json.loads(v)
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


settings = Settings()
