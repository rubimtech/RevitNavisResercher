"""
Utility functions: truncation, formatting, retry helpers.
"""

import asyncio
import json
import logging
from typing import Any, Optional

import httpx

from server.config import get_cfg

_logger = logging.getLogger("revitnavis")


def truncate(text: str, limit: int = 600) -> str:
    """Truncate text with ellipsis if over limit."""
    return text[:limit] + "..." if len(text) > limit else text


def truncate_response(result: str) -> str:
    """Truncate a full response string if over the character limit."""
    char_limit = get_cfg("output", "character_limit", default=25000)
    if len(result) > char_limit:
        return result[:char_limit] + "\n\n[Response truncated; refine query for more detail]"
    return result


def format_error(msg: str) -> str:
    """Format an error as a JSON string."""
    return json.dumps({"error": msg}, indent=2, ensure_ascii=False)


def is_retryable(exc: Exception) -> bool:
    """Check if the exception is worth retrying (network/timeout/server errors)."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


async def retry_async(
    coro_factory,
    max_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
    backoff: Optional[float] = None,
):
    """Retry an async call with exponential backoff."""
    if max_retries is None:
        max_retries = get_cfg("http_client", "max_retries", default=3)
    if base_delay is None:
        base_delay = get_cfg("http_client", "retry_delay_seconds", default=1.0)
    if backoff is None:
        backoff = get_cfg("http_client", "retry_backoff_factor", default=2.0)

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            if attempt < max_retries and is_retryable(e):
                delay = base_delay * (backoff**attempt)
                _logger.warning("Retry %d/%d after %.1fs: %s", attempt + 1, max_retries, delay, e)
                await asyncio.sleep(delay)
            else:
                raise
    raise last_exc  # type: ignore[union-attr]


_MODEL_CONFIG = {"str_strip_whitespace": True}

# Re-export pydantic helpers for tools
from pydantic import BaseModel, ConfigDict, Field  # noqa: F401, E402


class BaseModelConfig(BaseModel):
    """Base pydantic model with whitespace stripping."""
    model_config = ConfigDict(str_strip_whitespace=True)
