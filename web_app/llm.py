import json
import os
from typing import AsyncGenerator, Optional

from .cache import cache_get, cache_set
from .clients import get_http
from .config import get_cfg, llm_provider


async def llm_chat_full(messages: list[dict], system: str = "", api_key: Optional[str] = None) -> str:
    full = ""
    async for chunk in llm_chat_stream(messages, system, api_key=api_key):
        full += chunk
    return full


async def llm_chat_stream(messages: list[dict], system: str = "", api_key: Optional[str] = None) -> AsyncGenerator[str, None]:
    if llm_provider() == "ollama":
        async for chunk in _ollama_chat_stream(messages, system):
            yield chunk
        return
    async for chunk in _routerai_chat_stream(messages, system, api_key=api_key):
        yield chunk


async def _routerai_chat_stream(messages: list[dict], system: str = "", api_key: Optional[str] = None) -> AsyncGenerator[str, None]:
    client = get_http()
    url = f"{get_cfg('llm', 'base_url').rstrip('/')}/chat/completions"
    model = get_cfg("llm", "chat_model", default="deepseek/deepseek-v4-flash")
    temperature = get_cfg("llm", "temperature", default=0.3)
    api_key = api_key or os.environ.get("ROUTERAI_API_KEY", "")
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    key = f"llm:{model}:{system}:{messages}"
    cached = cache_get(key)
    if cached:
        yield cached
        return

    async with client.stream(
        "POST", url,
        json={"model": model, "messages": msgs, "temperature": temperature, "stream": True},
        headers={"Authorization": f"Bearer {api_key}"},
    ) as resp:
        resp.raise_for_status()
        full_text = ""
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        full_text += delta
                        yield delta
                except json.JSONDecodeError:
                    continue
        cache_set(key, full_text)


async def _ollama_chat_stream(messages: list[dict], system: str = "") -> AsyncGenerator[str, None]:
    client = get_http()
    base = get_cfg("ollama", "base_url", default="http://localhost:11434")
    model = get_cfg("ollama", "chat_model", default="qwen2.5-coder:7b")
    temperature = get_cfg("llm", "temperature", default=0.3)
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    key = f"ollama:{model}:{system}:{messages}"
    cached = cache_get(key)
    if cached:
        yield cached
        return

    full_text = ""
    async with client.stream(
        "POST", f"{base.rstrip('/')}/api/chat",
        json={"model": model, "messages": msgs, "options": {"temperature": temperature}, "stream": True},
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                content = data.get("message", {}).get("content", "")
                if content:
                    full_text += content
                    yield content
                if data.get("done"):
                    break
            except json.JSONDecodeError:
                continue
    cache_set(key, full_text)
