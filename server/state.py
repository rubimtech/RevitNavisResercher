"""
Shared singleton state: Qdrant + HTTP clients.
"""

from typing import Optional

import httpx
from qdrant_client import AsyncQdrantClient

from server.config import get_cfg

_qdrant_client: Optional[AsyncQdrantClient] = None
_http_client: Optional[httpx.AsyncClient] = None


def get_qdrant() -> AsyncQdrantClient:
    """Get or create the shared Qdrant client singleton."""
    global _qdrant_client
    if _qdrant_client is None:
        url = get_cfg("qdrant", "url", default="https://d9e0f9d73f7a.vps.myjino.ru:6333")
        _qdrant_client = AsyncQdrantClient(url=url)
    return _qdrant_client


def get_http() -> httpx.AsyncClient:
    """Get or create the shared HTTP client singleton."""
    global _http_client
    if _http_client is None:
        timeout = get_cfg("http_client", "timeout_seconds", default=30)
        verify_ssl = get_cfg("http_client", "verify_ssl", default=True)
        limits = httpx.Limits(
            max_keepalive_connections=get_cfg("http_client", "max_keepalive", default=5),
            max_connections=get_cfg("http_client", "max_connections", default=10),
        )
        _http_client = httpx.AsyncClient(timeout=timeout, verify=verify_ssl, limits=limits)
    return _http_client


async def shutdown() -> None:
    """Clean up clients on shutdown."""
    global _qdrant_client, _http_client
    logger = __import__("logging").getLogger("revitnavis")
    logger.info("Shutting down gracefully...")
    if _qdrant_client:
        await _qdrant_client.close()
        _qdrant_client = None
    if _http_client:
        await _http_client.aclose()
        _http_client = None
    logger.info("Shutdown complete.")
