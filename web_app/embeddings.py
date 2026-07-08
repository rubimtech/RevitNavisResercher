import os
from typing import Optional

from .cache import cache_get, cache_set
from .clients import get_http
from .config import get_cfg, llm_provider


async def get_embedding(text: str, api_key: Optional[str] = None) -> list[float]:
    key = f"emb:{text}"
    cached = cache_get(key)
    if cached:
        return cached

    if llm_provider() == "ollama":
        result = await _ollama_embedding(text)
    else:
        result = await _routerai_embedding(text, api_key=api_key)
    cache_set(key, result)
    return result


async def _routerai_embedding(text: str, api_key: Optional[str] = None) -> list[float]:
    key = f"emb:{text}"
    cached = cache_get(key)
    if cached:
        return cached
    client = get_http()
    url = f"{get_cfg('llm', 'base_url').rstrip('/')}/embeddings"
    model = get_cfg("llm", "embedding_model", default="baai/bge-m3")
    api_key = api_key or os.environ.get("ROUTERAI_API_KEY", "")
    resp = await client.post(
        url, json={"model": model, "input": text},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    resp.raise_for_status()
    result = resp.json()["data"][0]["embedding"]
    cache_set(key, result)
    return result


async def _ollama_embedding(text: str) -> list[float]:
    client = get_http()
    base = get_cfg("ollama", "base_url", default="http://localhost:11434")
    model = get_cfg("ollama", "embedding_model", default="nomic-embed-text")
    resp = await client.post(
        f"{base.rstrip('/')}/api/embed",
        json={"model": model, "input": text},
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]
