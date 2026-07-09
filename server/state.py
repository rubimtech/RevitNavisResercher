"""
Shared singleton state: Qdrant (embedded) + HTTP clients.
"""

import asyncio
import logging
from typing import Optional

import httpx
from qdrant_client import AsyncQdrantClient

from portable.paths import get_qdrant_dir
from server.config import get_cfg

_qdrant_client: Optional[AsyncQdrantClient] = None
_http_client: Optional[httpx.AsyncClient] = None
_qdrant_lock = asyncio.Lock()
_http_lock = asyncio.Lock()


async def get_qdrant() -> AsyncQdrantClient:
    """Get or create the shared Qdrant client singleton (async-safe).

    Uses embedded mode (local on-disk storage) — no external server needed.
    """
    global _qdrant_client
    async with _qdrant_lock:
        if _qdrant_client is None:
            location = str(get_qdrant_dir())
            _qdrant_client = AsyncQdrantClient(location=location)
    return _qdrant_client


async def get_http() -> httpx.AsyncClient:
    """Get or create the shared HTTP client singleton (async-safe)."""
    global _http_client
    async with _http_lock:
        if _http_client is None:
            timeout = get_cfg("http_client", "timeout_seconds", default=30)
            verify_ssl = get_cfg("http_client", "verify_ssl", default=True)
            limits = httpx.Limits(
                max_keepalive_connections=get_cfg("http_client", "max_keepalive", default=5),
                max_connections=get_cfg("http_client", "max_connections", default=20),
            )
            _http_client = httpx.AsyncClient(timeout=timeout, verify=verify_ssl, limits=limits)
    return _http_client


async def shutdown() -> None:
    """Clean up clients on shutdown."""
    global _qdrant_client, _http_client
    logger = logging.getLogger("revitnavis")
    logger.info("Shutting down gracefully...")
    if _qdrant_client:
        await _qdrant_client.close()
        _qdrant_client = None
    if _http_client:
        await _http_client.aclose()
        _http_client = None
    logger.info("Shutdown complete.")
