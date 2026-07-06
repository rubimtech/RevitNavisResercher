#!/usr/bin/env python3
"""
RevitNavisResearcher Web App — REST API + static frontend.
"""

import argparse
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient

load_dotenv(Path(__file__).parent / ".env")

STATIC_DIR = Path(__file__).parent / "static"

_qdrant: Optional[AsyncQdrantClient] = None
_http: Optional[httpx.AsyncClient] = None
_logger: logging.Logger = None
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300


def _cache_get(key: str) -> Any:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < _CACHE_TTL:
        return entry[1]
    if entry:
        del _cache[key]
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)
    if len(_cache) > 200:
        stale = [k for k, v in _cache.items() if time.monotonic() - v[0] >= _CACHE_TTL]
        for k in stale:
            del _cache[k]


def _cache_key(req: BaseModel) -> str:
    return f"{type(req).__name__}:{json.dumps(req.model_dump(), sort_keys=True)}"


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        elif value is not None:
            base[key] = value


def _set_nested(d: dict, keys: list[str], value: Any) -> None:
    current = d
    for k in keys[:-1]:
        current = current.setdefault(k, {})
    current[keys[-1]] = value


def _load_config() -> dict[str, Any]:
    cfg_path = Path(__file__).parent / "mcp_config.yaml"
    cfg: dict[str, Any] = {
        "llm": {
            "provider": "routerai",
            "base_url": "https://routerai.ru/api/v1",
            "embedding_model": "baai/bge-m3",
            "chat_model": "deepseek/deepseek-v4-flash",
            "temperature": 0.3,
            "max_tokens": 4096,
        },
        "ollama": {
            "base_url": "http://localhost:11434",
            "embedding_model": "nomic-embed-text",
            "chat_model": "qwen2.5-coder:7b",
        },
        "qdrant": {"url": "http://localhost:6333"},
        "http_client": {"timeout_seconds": 60, "max_retries": 3, "retry_delay_seconds": 1.0, "retry_backoff_factor": 2.0},
        "output": {"character_limit": 25000, "truncate_payload": 400, "truncate_syntax": 200},
    }
    if cfg_path.exists():
        import yaml
        with open(cfg_path) as f:
            yaml_cfg = yaml.safe_load(f) or {}
            _deep_merge(cfg, yaml_cfg)

    env_overrides: dict[str, tuple[str, Optional[type]]] = {
        "llm.provider": ("LLM_PROVIDER", None),
        "llm.base_url": ("ROUTERAI_BASE_URL", None),
        "llm.embedding_model": ("EMBEDDING_MODEL", None),
        "llm.chat_model": ("LLM_MODEL", None),
        "ollama.base_url": ("OLLAMA_BASE_URL", None),
        "ollama.embedding_model": ("OLLAMA_EMBEDDING_MODEL", None),
        "ollama.chat_model": ("OLLAMA_CHAT_MODEL", None),
        "qdrant.url": ("QDRANT_URL", None),
        "http_client.timeout_seconds": ("HTTP_TIMEOUT", int),
        "output.character_limit": ("CHARACTER_LIMIT", int),
    }
    for key, (env_var, cast) in env_overrides.items():
        value = os.environ.get(env_var)
        if value is not None:
            _set_nested(cfg, key.split("."), cast(value) if cast else value)
    return cfg


config: dict[str, Any] = {}


def _get_cfg(*keys: str, default: Any = None) -> Any:
    current = config
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    return current if current is not None else default


def _llm_provider() -> str:
    """Get configured LLM provider."""
    return _get_cfg("llm", "provider", default="routerai")


def _get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        url = _get_cfg("qdrant", "url", default=os.environ.get("QDRANT_URL", "http://localhost:6333"))
        _qdrant = AsyncQdrantClient(url=url)
    return _qdrant


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        timeout = _get_cfg("http_client", "timeout_seconds", default=60)
        _http = httpx.AsyncClient(timeout=timeout, verify=False)
    return _http


async def _get_embedding(text: str) -> list[float]:
    key = f"emb:{text}"
    cached = _cache_get(key)
    if cached:
        return cached

    if _llm_provider() == "ollama":
        result = await _ollama_embedding(text)
        _cache_set(key, result)
        return result

    result = await _routerai_embedding(text)
    _cache_set(key, result)
    return result


async def _routerai_embedding(text: str) -> list[float]:
    key = f"emb:{text}"
    cached = _cache_get(key)
    if cached:
        return cached
    client = _get_http()
    url = f"{_get_cfg('llm', 'base_url').rstrip('/')}/embeddings"
    model = _get_cfg("llm", "embedding_model", default="baai/bge-m3")
    api_key = os.environ.get("ROUTERAI_API_KEY", "")
    resp = await client.post(
        url, json={"model": model, "input": text},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    resp.raise_for_status()
    result = resp.json()["data"][0]["embedding"]
    _cache_set(key, result)
    return result


async def _ollama_embedding(text: str) -> list[float]:
    """Get embedding from local Ollama."""
    client = _get_http()
    base = _get_cfg("ollama", "base_url", default="http://localhost:11434")
    model = _get_cfg("ollama", "embedding_model", default="nomic-embed-text")
    resp = await client.post(
        f"{base.rstrip('/')}/api/embed",
        json={"model": model, "input": text},
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


async def _llm_chat_full(messages: list[dict], system: str = "") -> str:
    full = ""
    async for chunk in _llm_chat_stream(messages, system):
        full += chunk
    return full


async def _llm_chat_stream(messages: list[dict], system: str = ""):
    if _llm_provider() == "ollama":
        async for chunk in _ollama_chat_stream(messages, system):
            yield chunk
        return
    async for chunk in _routerai_chat_stream(messages, system):
        yield chunk


async def _routerai_chat_stream(messages: list[dict], system: str = ""):
    client = _get_http()
    url = f"{_get_cfg('llm', 'base_url').rstrip('/')}/chat/completions"
    model = _get_cfg("llm", "chat_model", default="deepseek/deepseek-v4-flash")
    temperature = _get_cfg("llm", "temperature", default=0.3)
    api_key = os.environ.get("ROUTERAI_API_KEY", "")
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    key = f"llm:{model}:{system}:{messages}"
    cached = _cache_get(key)
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
        _cache_set(key, full_text)


async def _ollama_chat_stream(messages: list[dict], system: str = ""):
    """Stream from local Ollama."""
    client = _get_http()
    base = _get_cfg("ollama", "base_url", default="http://localhost:11434")
    model = _get_cfg("ollama", "chat_model", default="qwen2.5-coder:7b")
    temperature = _get_cfg("llm", "temperature", default=0.3)
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    key = f"ollama:{model}:{system}:{messages}"
    cached = _cache_get(key)
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
    _cache_set(key, full_text)


def _truncate(text: str, limit: int = 600) -> str:
    return text[:limit] + "..." if len(text) > limit else text


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="Ваш вопрос по Revit API / Navisworks API")
    collections: list[str] = Field(default=["revit_api_knowledge"], description="Коллекции Qdrant для поиска")
    limit: int = Field(default=8, ge=1, le=30)
    revit_version: str = Field(default="2024", description="Версия Revit (2021-2027)")


class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=2)
    context: str = Field(..., description="Результаты поиска для анализа")
    instructions: str = Field(default="")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, _logger
    config = _load_config()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
    _logger = logging.getLogger("revitnavis-web")
    provider = _llm_provider()
    _logger.info("Web App config loaded. Qdrant: %s", _get_cfg("qdrant", "url"))
    _logger.info("LLM provider: %s", provider)
    if provider == "ollama":
        _logger.info("Ollama: %s | embed=%s, chat=%s",
            _get_cfg("ollama", "base_url"),
            _get_cfg("ollama", "embedding_model"),
            _get_cfg("ollama", "chat_model"),
        )
    else:
        _logger.info("Models: embed=%s, llm=%s", _get_cfg("llm", "embedding_model"), _get_cfg("llm", "chat_model"))
        if not os.environ.get("ROUTERAI_API_KEY"):
            _logger.warning("ROUTERAI_API_KEY not set — LLM endpoints will fail")
    yield
    global _qdrant, _http
    if _qdrant:
        await _qdrant.close()
    if _http:
        await _http.aclose()


app = FastAPI(
    title="RevitNavis Researcher",
    description="Поиск по документации Revit API и Navisworks API",
    version="1.0.0",
    lifespan=lifespan,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>RevitNavis Researcher</h1><p>Frontend not found. Run with static/index.html</p>")


@app.get("/api/config")
async def api_config():
    provider = _llm_provider()
    return {
        "collections": [
            {"name": "revit_api_knowledge", "label": "Revit API"},
            {"name": "Revit_SDK_Samples", "label": "Revit SDK Samples"},
            {"name": "navisworks_api_bge", "label": "Navisworks API"},
        ],
        "revit_versions": ["2021", "2022", "2023", "2024", "2025", "2026", "2027"],
        "llm_provider": provider,
        "llm_model": _get_cfg("ollama" if provider == "ollama" else "llm", "chat_model"),
        "embedding_model": _get_cfg("ollama" if provider == "ollama" else "llm", "embedding_model"),
        "has_api_key": bool(os.environ.get("ROUTERAI_API_KEY")),
    }


@app.post("/api/search/qdrant")
async def search_qdrant(req: SearchRequest):
    ck = _cache_key(req)
    cached = _cache_get(ck)
    if cached:
        return cached
    try:
        client = _get_qdrant()
        vector = await _get_embedding(req.query)
        trunc_payload = _get_cfg("output", "truncate_payload", default=400)
        trunc_syntax = _get_cfg("output", "truncate_syntax", default=200)
        seen_ids: set[str] = set()
        all_results: list[dict] = []

        for coll in req.collections:
            results = await client.query_points(
                collection_name=coll, query=vector, limit=req.limit,
                with_payload=True, with_vectors=False,
            )
            for point in results.points:
                pid = str(point.id)
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                payload = point.payload or {}
                all_results.append({
                    "id": pid, "score": round(point.score, 4), "collection": coll,
                    "name": payload.get("name", ""),
                    "summary": _truncate(payload.get("summary", ""), trunc_payload),
                    "syntax": _truncate(payload.get("syntax", ""), trunc_syntax),
                    "params": _truncate(payload.get("params", ""), trunc_syntax),
                    "versions": payload.get("versions", []),
                })

        all_results.sort(key=lambda r: r["score"], reverse=True)
        all_results = all_results[: req.limit]
        result = {"query": req.query, "collections": req.collections, "count": len(all_results), "results": all_results}
        _cache_set(ck, result)
        return result
    except Exception as e:
        _logger.error("qdrant search failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


async def _search_rvtdocs(query: str, version: str, limit: int) -> list[dict]:
    """Search rvtdocs with optional fallback to other versions if empty."""
    client = _get_http()
    try:
        r = await client.post(
            "https://rvtdocs.com/search/api/search",
            json={"query": query, "current_version": version, "include_description": True},
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("current_version_results", [])
    except Exception:
        results = []

    # Fallback: try other versions if empty
    if not results:
        fallback_versions = ["2025", "2023", "2022"]
        for v in fallback_versions:
            if v == version:
                continue
            try:
                r = await client.post(
                    "https://rvtdocs.com/search/api/search",
                    json={"query": query, "current_version": v, "include_description": True},
                )
                r.raise_for_status()
                data = r.json()
                results = data.get("current_version_results", [])
                if results:
                    version = v
                    break
            except Exception:
                continue

    formatted = []
    for item in results[:limit]:
        formatted.append({
            "title": item.get("title", ""),
            "type": item.get("type", ""),
            "namespace": item.get("namespace", ""),
            "description": item.get("description", ""),
            "version": item.get("year_version", ""),
            "url": f"https://rvtdocs.com{item.get('url', '')}",
        })
    return formatted


@app.post("/api/search/rvtdocs")
async def search_rvtdocs(req: SearchRequest):
    ck = _cache_key(req)
    cached = _cache_get(ck)
    if cached:
        return cached
    try:
        formatted = await _search_rvtdocs(req.query, req.revit_version, req.limit)
        result = {"query": req.query, "version": req.revit_version, "count": len(formatted), "results": formatted}
        _cache_set(ck, result)
        return result
    except Exception as e:
        _logger.error("rvtdocs search failed: %s", e)
        raise HTTPException(500, str(e))


async def _build_context(req: SearchRequest) -> tuple[dict, dict, str]:
    qdrant_data = await search_qdrant(req)
    qdrant_results = json.loads(qdrant_data.body.decode()) if hasattr(qdrant_data, 'body') else qdrant_data

    rvtdocs_results_list = await _search_rvtdocs(req.query, req.revit_version, req.limit)
    rvtdocs_results = {"results": rvtdocs_results_list, "count": len(rvtdocs_results_list)}

    context_parts: list[str] = []
    if qdrant_results.get("results"):
        context_parts.append("## Qdrant Results")
        for r in qdrant_results["results"]:
            coll = r.get("collection", "")
            context_parts.append(f"- [{coll}] {r.get('name', '')} (score: {r.get('score', '')}): {r.get('summary', '')[:300]}")
    if rvtdocs_results.get("results"):
        context_parts.append("\n## rvtdocs Results")
        for r in rvtdocs_results["results"]:
            context_parts.append(f"- {r.get('title', '')} ({r.get('type', '')}): {r.get('description', '')[:300]}")

    context = "\n".join(context_parts) if context_parts else "No results found."
    return qdrant_results, rvtdocs_results, context


@app.post("/api/research")
async def research(req: SearchRequest):
    if _llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        raise HTTPException(400, "ROUTERAI_API_KEY not set (or set LLM_PROVIDER=ollama)")
    try:
        qdrant_results, rvtdocs_results, context = await _build_context(req)

        system = (
            "You are a Revit API, Revit SDK, and Navisworks API expert. "
            f"Answer the question based on the search results. Target Revit version: {req.revit_version}. "
            "Provide code examples where relevant."
        )
        analysis = await _llm_chat_full(
            [{"role": "user", "content": f"## Question\n{req.query}\n\n## Search Results\n{context}"}],
            system=system,
        )
        return {
            "query": req.query, "revit_version": req.revit_version, "collections": req.collections,
            "qdrant_count": qdrant_results.get("count", 0),
            "rvtdocs_count": rvtdocs_results.get("count", 0),
            "qdrant_results": qdrant_results.get("results", [])[:8],
            "rvtdocs_results": rvtdocs_results.get("results", [])[:5],
            "analysis": analysis,
        }
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("research failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/api/research/stream")
async def research_stream(req: SearchRequest):
    """SSE endpoint: Qdrant → rvtdocs → streaming LLM ответ."""
    if _llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        raise HTTPException(400, "ROUTERAI_API_KEY not set (or set LLM_PROVIDER=ollama)")

    async def _event_stream():
        try:
            yield "event: status\ndata: {\"msg\":\"Поиск в Qdrant...\"}\n\n"
            qdrant_results, rvtdocs_results, context = await _build_context(req)
            qdrant_json = {
                "qdrant_count": qdrant_results.get("count", 0),
                "qdrant_results": qdrant_results.get("results", [])[:8],
            }
            yield f"event: qdrant\ndata: {json.dumps(qdrant_json, ensure_ascii=False)}\n\n"

            yield "event: status\ndata: {\"msg\":\"Поиск на rvtdocs.com...\"}\n\n"
            rvtdocs_json = {
                "rvtdocs_count": rvtdocs_results.get("count", 0),
                "rvtdocs_results": rvtdocs_results.get("results", [])[:5],
            }
            yield f"event: rvtdocs\ndata: {json.dumps(rvtdocs_json, ensure_ascii=False)}\n\n"

            yield "event: status\ndata: {\"msg\":\"Генерация ответа...\"}\n\n"

            system = (
                "You are a Revit API, Revit SDK, and Navisworks API expert. "
                f"Answer the question based on the search results. Target Revit version: {req.revit_version}. "
                "Provide code examples where relevant."
            )
            async for chunk in _llm_chat_stream(
                [{"role": "user", "content": f"## Question\n{req.query}\n\n## Search Results\n{context}"}],
                system=system,
            ):
                yield f"event: token\ndata: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"

            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            _logger.error("research stream failed: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main():
    parser = argparse.ArgumentParser(description="RevitNavis Researcher Web App")
    parser.add_argument("--host", default="0.0.0.0", help="Хост (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Порт (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Автоперезагрузка при изменении кода")
    args = parser.parse_args()
    uvicorn.run("web_app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
