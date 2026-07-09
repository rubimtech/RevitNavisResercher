"""
LLM provider abstraction: RouterAI / Ollama embedding and chat dispatchers.
"""

import os
from typing import Optional

from server.config import get_cfg
from server.state import get_http
from server.utils import retry_async


def llm_provider() -> str:
    """Get configured LLM provider (routerai | ollama)."""
    return get_cfg("llm", "provider", default="routerai")


# ─── RouterAI ───────────────────────────────────────────────────────────────

async def _routerai_embedding(text: str) -> list[float]:
    client = await get_http()
    url = f"{get_cfg('llm', 'base_url').rstrip('/')}/embeddings"
    model = get_cfg("llm", "embedding_model", default="baai/bge-m3")
    api_key = os.environ.get("ROUTERAI_API_KEY", "")

    async def _do():
        resp = await client.post(
            url,
            json={"model": model, "input": text},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]

    return await retry_async(_do)


async def _routerai_chat(
    messages: list[dict], system: str = "", temperature: Optional[float] = None
) -> str:
    client = await get_http()
    url = f"{get_cfg('llm', 'base_url').rstrip('/')}/chat/completions"
    model = get_cfg("llm", "chat_model", default="deepseek/deepseek-v4-flash")
    if temperature is None:
        temperature = get_cfg("llm", "temperature", default=0.3)
    max_tokens = get_cfg("llm", "max_tokens", default=4096)
    api_key = os.environ.get("ROUTERAI_API_KEY", "")

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    async def _do():
        resp = await client.post(
            url,
            json={"model": model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    return await retry_async(_do)


# ─── Ollama ─────────────────────────────────────────────────────────────────

async def _ollama_embedding(text: str) -> list[float]:
    client = await get_http()
    base = get_cfg("ollama", "base_url", default="http://localhost:11434")
    model = get_cfg("ollama", "embedding_model", default="nomic-embed-text")
    resp = await client.post(
        f"{base.rstrip('/')}/api/embed",
        json={"model": model, "input": text},
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


async def _ollama_chat(
    messages: list[dict], system: str = "", temperature: Optional[float] = None
) -> str:
    client = await get_http()
    base = get_cfg("ollama", "base_url", default="http://localhost:11434")
    model = get_cfg("ollama", "chat_model", default="qwen2.5-coder:7b")
    temp = temperature if temperature is not None else get_cfg("llm", "temperature", default=0.3)

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    resp = await client.post(
        f"{base.rstrip('/')}/api/chat",
        json={"model": model, "messages": msgs, "stream": False, "options": {"temperature": temp}},
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


# ─── Dispatchers ────────────────────────────────────────────────────────────

async def get_embedding(text: str) -> list[float]:
    """Get embedding vector — dispatches to RouterAI or Ollama based on provider config."""
    if llm_provider() == "ollama":
        return await _ollama_embedding(text)
    return await _routerai_embedding(text)


async def llm_chat(
    messages: list[dict], system: str = "", temperature: Optional[float] = None
) -> str:
    """Call LLM — dispatches to RouterAI or Ollama based on provider config."""
    if llm_provider() == "ollama":
        return await _ollama_chat(messages, system=system, temperature=temperature)
    return await _routerai_chat(messages, system=system, temperature=temperature)
