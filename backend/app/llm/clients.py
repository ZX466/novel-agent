"""LLM client wrappers. All providers go through litellm.acompletion so the
rest of the app stays provider-agnostic.

Two credential sources, in priority order:
  1. `stage_config` argument — user-supplied BYOK credentials for the
     specific pipeline stage. Carried per-request via the X-Provider-Config
     JSON header and split into three StageConfig objects by the API layer.
     Uses `openai/<model>` prefix with the user's api_base so any
     OpenAI-compatible endpoint works.
  2. `.env` settings — server-side fallback, used when `stage_config`
     is None and `BYOK_FALLBACK_TO_ENV=true`.

Env vars (DEEPSEEK_API_KEY, DASHSCOPE_API_KEY, RELAY_API_KEY) MAY be set
in the environment for fallback, but are no longer required at startup.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import random
import re
import socket
from typing import Any, Dict, List
from urllib.parse import urlparse

from litellm import acompletion

from app.config import settings
from app.schemas.chat import StageConfig

logger = logging.getLogger(__name__)

Message = Dict[str, str]

# LLM call timeout (seconds). Prevents indefinite hangs when a provider
# is unresponsive. 120s is generous for a single LLM call; most complete
# in 5-30s.
_LLM_TIMEOUT_SECONDS = 120

# Retry configuration for transient failures (connection resets, timeouts,
# 429 rate limits, 5xx server errors). Does NOT retry auth errors (401/403)
# or bad requests (400) since those won't self-resolve.
_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 2.0  # seconds; exponential backoff: 2s, 4s, 8s, 16s


# --- SSRF protection ---------------------------------------------------------

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

class APIBaseNotAllowed(ValueError):
    """Raised by _validate_api_base when the API base URL is rejected (SSRF defense).

    A dedicated type lets callers distinguish SSRF-style rejections from
    unrelated ValueErrors raised deeper in the LLM pipeline, so the frontend
    error message stays accurate (R8 audit L3).
    """



def _validate_api_base(url: str) -> None:
    """Raise ValueError if api_base points to a blocked internal address.

    Defends against SSRF: a malicious user could otherwise point api_base
    at cloud metadata endpoints (169.254.169.254) or internal services
    to exfiltrate credentials or scan the network.
    
    TOCTOU 说明 (R8 审计): 此处校验自行解析 DNS，随后 litellm/httpx 发起请求时会
    再次独立解析域名，校验与请求之间存在 DNS rebinding 竞态窗口，理论可绕过 IP 校验
    （校验时解析为公网 IP，请求时重绑到内网）。因调用链经 litellm.acompletion（内部
    transport 不对外暴露），transport 层 pin 主机名需侵入 litellm 内部，脆弱且收益低；
    攻击者还需自控域名并精确把握微秒级窗口。结论：仅文档化，残余风险可接受。
    推荐未来加固：在反代/网关层做 egress 域名/IP 白名单（本部署经 nginx，可落地）。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise APIBaseNotAllowed(f"Unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host:
        raise APIBaseNotAllowed("api_base has no host component")
    if host in _LOCAL_HOSTS:
        if not settings.byok_allow_local_api_base:
            raise APIBaseNotAllowed("Local API base is disabled by BYOK_ALLOW_LOCAL_API_BASE")
        return
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            }
        except OSError:
            return
    if any(not ip.is_global for ip in addresses):
        raise APIBaseNotAllowed(f"Blocked internal address: {host}")

# --- API key redaction for logs ---------------------------------------------

_API_KEY_PATTERN = re.compile(r"(?:sk-[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9._~+/=-]+|https?://[^\s:@]+:[^\s@]+@[^\s]+)", re.IGNORECASE)


def _redact_key(text: str) -> str:
    """Replace credential tokens with a fixed marker in log/error messages."""
    if not text:
        return text
    return _API_KEY_PATTERN.sub("[REDACTED]", text)


# --- LLM call helpers --------------------------------------------------------

def _byok_kwargs(cfg: StageConfig) -> Dict[str, Any]:
    """Build litellm.acompletion kwargs for a BYOK StageConfig.

    Always uses the `openai/` model prefix because litellm routes any
    OpenAI-compatible endpoint through the openai provider when api_base
    is supplied. Any other provider prefix (openrouter/, anthropic/, ...)
    would be silently ignored in this mode.
    """
    _validate_api_base(cfg.api_base)
    kwargs: Dict[str, Any] = {
        "model": f"openai/{cfg.model}",
        "api_key": cfg.api_key,
        "api_base": cfg.api_base,
    }
    if cfg.extra_headers:
        kwargs["extra_headers"] = dict(cfg.extra_headers)
    return kwargs


async def _call_with_retry(call_fn, *args, **kwargs) -> Any:
    """Call an async function with timeout and retry on transient errors.

    Retries on: Timeout, APIConnectionError, RateLimitError, and 5xx
    InternalServerError. Does NOT retry on auth errors (401/403) or
    bad requests (400) since those indicate a caller bug.
    """
    import litellm

    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await asyncio.wait_for(
                call_fn(*args, **kwargs),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            last_exc = TimeoutError(
                f"LLM call timed out after {_LLM_TIMEOUT_SECONDS}s"
            )
            logger.warning(
                "LLM timeout (attempt %d/%d)",
                attempt + 1, _MAX_RETRIES + 1,
            )
        except (
            litellm.APIConnectionError,
            litellm.RateLimitError,
            litellm.InternalServerError,
        ) as e:
            last_exc = e
            logger.warning(
                "LLM transient error (attempt %d/%d): %s",
                attempt + 1, _MAX_RETRIES + 1, _redact_key(str(e)),
            )
        # Non-retryable errors propagate immediately:
        # AuthenticationError, BadRequestError, NotFoundError, etc.

        if attempt < _MAX_RETRIES:
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            # Add ±30% jitter to de-synchronize concurrent callers.
            delay *= 1.0 + random.uniform(-0.3, 0.3)
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


async def _stream_with_retry(call_fn, *args, **kwargs) -> Any:
    """Like _call_with_retry but for streaming calls.

    Returns the async iterator from the first successful connection.
    Retries only on connection-level failures (before streaming starts).
    Stream consumption errors are not retried — the caller handles them.
    """
    import litellm

    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            # acompletion(stream=True) returns an async iterator quickly.
            # The timeout here only covers the connection handshake.
            return await asyncio.wait_for(
                call_fn(*args, **kwargs),
                timeout=30,  # connection timeout only
            )
        except asyncio.TimeoutError:
            last_exc = TimeoutError("LLM stream connection timed out after 30s")
            logger.warning(
                "LLM stream timeout (attempt %d/%d)",
                attempt + 1, _MAX_RETRIES + 1,
            )
        except (
            litellm.APIConnectionError,
            litellm.RateLimitError,
            litellm.InternalServerError,
        ) as e:
            last_exc = e
            logger.warning(
                "LLM stream transient error (attempt %d/%d): %s",
                attempt + 1, _MAX_RETRIES + 1, _redact_key(str(e)),
            )

        if attempt < _MAX_RETRIES:
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            delay *= 1.0 + random.uniform(-0.3, 0.3)
            await asyncio.sleep(delay)

    raise last_exc


async def draft(
    messages: List[Message],
    *,
    stream: bool = False,
    stage_config: StageConfig | None = None,
    temperature: float | None = None,
    response_format: dict | None = None,
) -> Any:
    """Draft generation stage.

    Uses DeepSeek-V4-Flash by default (via .env), or the user's BYOK
    provider for the draft stage when `stage_config` is supplied.
    When stream=True, returns an async iterator of chunks for real-time
    token streaming.

    Args:
        temperature: Override the default 0.7 temperature (e.g. 0.1 for
            deterministic JSON extraction).
        response_format: OpenAI-compatible response_format dict, e.g.
            {"type": "json_object"} to force JSON output.
    """
    retry_fn = _stream_with_retry if stream else _call_with_retry
    temp = temperature if temperature is not None else 0.7
    extra: Dict[str, Any] = {}
    if response_format is not None:
        extra["response_format"] = response_format
    if stage_config is not None:
        return await retry_fn(
            acompletion,
            messages=messages,
            stream=stream,
            temperature=temp,
            max_tokens=4096,
            **extra,
            **_byok_kwargs(stage_config),
        )
    return await retry_fn(
        acompletion,
        model=f"deepseek/{settings.deepseek_model}",
        messages=messages,
        api_key=settings.deepseek_api_key,
        temperature=temp,
        max_tokens=4096,
        stream=stream,
        **extra,
    )


async def refine(
    messages: List[Message],
    *,
    stream: bool = False,
    stage_config: StageConfig | None = None,
) -> Any:
    """Refinement stage.

    Uses Qwen-Max by default (via .env), or the user's BYOK provider
    for the refine stage when `stage_config` is supplied.
    When stream=True, returns an async iterator of chunks for real-time
    token streaming.
    """
    retry_fn = _stream_with_retry if stream else _call_with_retry
    if stage_config is not None:
        return await retry_fn(
            acompletion,
            messages=messages,
            stream=stream,
            temperature=0.4,
            max_tokens=2048,
            **_byok_kwargs(stage_config),
        )
    return await retry_fn(
        acompletion,
        model=f"dashscope/{settings.dashscope_model}",
        messages=messages,
        api_key=settings.dashscope_api_key,
        api_base=settings.dashscope_api_base,
        temperature=0.4,
        max_tokens=2048,
        stream=stream,
    )


async def evaluate(
    messages: List[Message],
    *,
    stage_config: StageConfig | None = None,
) -> Any:
    """Evaluation stage.

    Uses Claude Sonnet via relay by default (via .env), or the user's
    BYOK provider for the evaluate stage when `stage_config` is supplied.

    Default assumes the relay speaks OpenAI-compatible protocol (oneapi/new-api
    family). If your relay speaks native Anthropic Messages API instead, change
    the model prefix from "openai/" to "anthropic/" and drop the /v1 suffix
    from RELAY_API_BASE.
    """
    if stage_config is not None:
        return await _call_with_retry(
            acompletion,
            messages=messages,
            stream=False,
            temperature=0.0,
            max_tokens=512,
            **_byok_kwargs(stage_config),
        )
    return await _call_with_retry(
        acompletion,
        model=f"openai/{settings.relay_claude_model}",
        messages=messages,
        api_key=settings.relay_api_key,
        api_base=settings.relay_api_base,
        temperature=0.0,
        max_tokens=512,
        stream=False,
    )
