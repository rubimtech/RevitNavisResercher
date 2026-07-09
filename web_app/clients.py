import os
from typing import Optional

import httpx
from qdrant_client import AsyncQdrantClient

from portable.paths import get_qdrant_dir
from .config import get_cfg

_qdrant: Optional[AsyncQdrantClient] = None
_http: Optional[httpx.AsyncClient] = None


def get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(location=str(get_qdrant_dir()))
    return _qdrant


def get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        timeout = get_cfg("http_client", "timeout_seconds", default=60)
        _http = httpx.AsyncClient(timeout=timeout, verify=False)
    return _http


async def close_clients() -> None:
    global _qdrant, _http
    if _qdrant:
        await _qdrant.close()
        _qdrant = None
    if _http:
        await _http.aclose()
        _http = None
