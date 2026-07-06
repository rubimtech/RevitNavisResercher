#!/usr/bin/env python3
"""
MCP Server for Revit & Navisworks research.

Connects to:
  - Qdrant at configurable QDRANT_URL (remote vector DB with docs)
  - RouterAI for embeddings (bge-m3) and LLM (deepseek-v4-flash)
  - rvtdocs.com for Revit API documentation search

Requires env: ROUTERAI_API_KEY
Supports YAML config: mcp_config.yaml (env vars override YAML)
"""

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import aiosqlite
import httpx
import yaml
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field
from qdrant_client import AsyncQdrantClient

# ─── Load .env early ────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

# ─── Defaults ───────────────────────────────────────────────────────────────
DEFAULT_CONFIG_PATH = Path(__file__).parent / "mcp_config.yaml"

# ─── Globals ────────────────────────────────────────────────────────────────
_qdrant_client: Optional[AsyncQdrantClient] = None
_http_client: Optional[httpx.AsyncClient] = None
_config: dict[str, Any] = {}
_logger: logging.Logger = None  # type: ignore[assignment]


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

def _load_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    """Load YAML config, merge with env overrides (env has priority)."""
    cfg: dict[str, Any] = {
        "transport": {"mode": "stdio", "host": "0.0.0.0", "port": 8000},
        "llm": {
            "base_url": "https://routerai.ru/api/v1",
            "embedding_model": "baai/bge-m3",
            "chat_model": "deepseek/deepseek-v4-flash",
            "temperature": 0.3,
            "max_tokens": 4096,
        },
        "qdrant": {
            "url": "http://localhost:6333",
            "include_full_code": False,
            "collections": [
                {"name": "revit_api_knowledge", "description": "Revit API documentation"},
                {"name": "Revit_SDK_Samples", "description": "Revit SDK samples"},
                {"name": "navisworks_api_bge", "description": "Navisworks API documentation"},
            ],
        },
        "http_client": {
            "timeout_seconds": 30,
            "max_retries": 3,
            "retry_delay_seconds": 1.0,
            "retry_backoff_factor": 2.0,
            "verify_ssl": True,
            "max_keepalive": 5,
            "max_connections": 10,
        },
        "output": {
            "character_limit": 25000,
            "truncate_payload": 400,
            "truncate_syntax": 200,
        },
        "revit_versions": ["2021", "2022", "2023", "2024", "2025", "2026", "2027"],
        "logging": {"level": "INFO", "format": "text"},
    }

    # Load YAML
    config_path = config_path or DEFAULT_CONFIG_PATH
    if config_path.exists():
        with open(config_path) as f:
            yaml_cfg = yaml.safe_load(f) or {}
            _deep_merge(cfg, yaml_cfg)

    # Env overrides
    env_overrides: dict[str, tuple[str, Optional[type]]] = {
        "transport.mode": ("MCP_TRANSPORT", None),
        "transport.host": ("MCP_HOST", None),
        "transport.port": ("MCP_PORT", int),
        "llm.base_url": ("ROUTERAI_BASE_URL", None),
        "llm.embedding_model": ("EMBEDDING_MODEL", None),
        "llm.chat_model": ("LLM_MODEL", None),
        "qdrant.url": ("QDRANT_URL", None),
        "http_client.timeout_seconds": ("HTTP_TIMEOUT", int),
        "output.character_limit": ("CHARACTER_LIMIT", int),
    }
    for key, (env_var, cast) in env_overrides.items():
        value = os.environ.get(env_var)
        if value is not None:
            _set_nested(cfg, key.split("."), cast(value) if cast else value)

    return cfg


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        elif value is not None:
            base[key] = value


def _set_nested(d: dict, keys: list[str], value: Any) -> None:
    """Set a nested dict value by key path."""
    current = d
    for k in keys[:-1]:
        current = current.setdefault(k, {})
    current[keys[-1]] = value


def _get_cfg(*keys: str, default: Any = None) -> Any:
    """Get nested config value."""
    current = _config
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    return current if current is not None else default


# ═══════════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════════

class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def _setup_logging(level_str: str = "INFO", fmt: str = "text") -> logging.Logger:
    """Configure root logger for the revitnavis namespace."""
    root = logging.getLogger("revitnavis")
    root.setLevel(getattr(logging, level_str.upper(), logging.INFO))
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(handler)
    return root


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP / Qdrant helpers with retry
# ═══════════════════════════════════════════════════════════════════════════════

async def _retry_async(
    coro_factory,
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
):
    """Retry an async call with exponential backoff."""
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            if attempt < max_retries and _is_retryable(e):
                delay = base_delay * (backoff**attempt)
                _logger.warning("Retry %d/%d after %.1fs: %s", attempt + 1, max_retries, delay, e)
                await asyncio.sleep(delay)
            else:
                raise
    raise last_exc  # type: ignore[union-attr]


def _is_retryable(exc: Exception) -> bool:
    """Check if the exception is worth retrying (network/timeout/server errors)."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


def _get_qdrant() -> AsyncQdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        url = _get_cfg("qdrant", "url", default=os.environ.get("QDRANT_URL", "http://localhost:6333"))
        _qdrant_client = AsyncQdrantClient(url=url)
    return _qdrant_client


def _get_http() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        timeout = _get_cfg("http_client", "timeout_seconds", default=30)
        verify_ssl = _get_cfg("http_client", "verify_ssl", default=True)
        limits = httpx.Limits(
            max_keepalive_connections=_get_cfg("http_client", "max_keepalive", default=5),
            max_connections=_get_cfg("http_client", "max_connections", default=10),
        )
        _http_client = httpx.AsyncClient(timeout=timeout, verify=verify_ssl, limits=limits)
    return _http_client


async def _get_embedding(text: str) -> list[float]:
    """Get embedding vector from RouterAI with retry."""
    client = _get_http()
    url = f"{_get_cfg('llm', 'base_url').rstrip('/')}/embeddings"
    model = _get_cfg("llm", "embedding_model", default="baai/bge-m3")
    max_retries = _get_cfg("http_client", "max_retries", default=3)
    delay = _get_cfg("http_client", "retry_delay_seconds", default=1.0)
    backoff = _get_cfg("http_client", "retry_backoff_factor", default=2.0)
    api_key = os.environ.get("ROUTERAI_API_KEY", "")

    async def _do():
        resp = await client.post(
            url,
            json={"model": model, "input": text},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]

    return await _retry_async(_do, max_retries=max_retries, base_delay=delay, backoff=backoff)


async def _llm_chat(
    messages: list[dict], system: str = "", temperature: Optional[float] = None
) -> str:
    """Call RouterAI LLM with retry."""
    client = _get_http()
    url = f"{_get_cfg('llm', 'base_url').rstrip('/')}/chat/completions"
    model = _get_cfg("llm", "chat_model", default="deepseek/deepseek-v4-flash")
    if temperature is None:
        temperature = _get_cfg("llm", "temperature", default=0.3)
    max_tokens = _get_cfg("llm", "max_tokens", default=4096)
    max_retries = _get_cfg("http_client", "max_retries", default=3)
    delay = _get_cfg("http_client", "retry_delay_seconds", default=1.0)
    backoff = _get_cfg("http_client", "retry_backoff_factor", default=2.0)
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

    return await _retry_async(_do, max_retries=max_retries, base_delay=delay, backoff=backoff)


# ═══════════════════════════════════════════════════════════════════════════════
# Graceful Shutdown
# ═══════════════════════════════════════════════════════════════════════════════

async def _shutdown() -> None:
    """Clean up clients on shutdown."""
    global _qdrant_client, _http_client
    _logger.info("Shutting down gracefully...")
    if _qdrant_client:
        await _qdrant_client.close()
        _qdrant_client = None
    if _http_client:
        await _http_client.aclose()
        _http_client = None
    _logger.info("Shutdown complete.")


# ═══════════════════════════════════════════════════════════════════════════════
# Utility functions
# ═══════════════════════════════════════════════════════════════════════════════

def _truncate(text: str, limit: int = 600) -> str:
    return text[:limit] + "..." if len(text) > limit else text


def _truncate_response(result: str) -> str:
    char_limit = _get_cfg("output", "character_limit", default=25000)
    if len(result) > char_limit:
        return result[:char_limit] + "\n\n[Response truncated; refine query for more detail]"
    return result


def _format_error(msg: str) -> str:
    return json.dumps({"error": msg}, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic schemas
# ═══════════════════════════════════════════════════════════════════════════════

class BaseModelConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class QdrantSearchInput(BaseModelConfig):
    query: str = Field(..., description="Natural language search query", min_length=2, max_length=500)
    collection: str = Field(default="revit_api_knowledge", description="Qdrant collection")
    limit: int = Field(default=10, description="Max results (1-50)", ge=1, le=50)
    score_threshold: Optional[float] = Field(
        default=None, description="Min similarity score 0.0-1.0", ge=0.0, le=1.0
    )
    include_full_code: Optional[bool] = Field(
        default=None, description="Load full_code from local SQLite by db_id"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Server setup
# ═══════════════════════════════════════════════════════════════════════════════

mcp = FastMCP("revit_navis_mcp")


# ─── Qdrant Tools ───────────────────────────────────────────────────────────

@mcp.tool(
    name="qdrant_search",
    annotations={
        "title": "Semantic search in Qdrant",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def qdrant_search(
    query: str,
    collection: str = "revit_api_knowledge",
    limit: int = 10,
    score_threshold: Optional[float] = None,
    include_full_code: Optional[bool] = None,
) -> str:
    """Search a Qdrant collection using semantic search via RouterAI embeddings."""
    try:
        client = _get_qdrant()
        vector = await _get_embedding(query)
        results = await client.query_points(
            collection_name=collection,
            query=vector,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        trunc_payload = _get_cfg("output", "truncate_payload", default=400)
        trunc_syntax = _get_cfg("output", "truncate_syntax", default=200)
        include_full_code = (
            include_full_code
            if include_full_code is not None
            else _get_cfg("qdrant", "include_full_code", default=False)
        )

        _db: Optional[aiosqlite.Connection] = None
        if include_full_code:
            _db_path = Path(__file__).parent / "revit_codebase.db"
            _db = await aiosqlite.connect(str(_db_path))

        formatted = []
        for point in results.points:
            payload = point.payload or {}
            entry = {
                "id": str(point.id),
                "score": round(point.score, 4),
                "payload": {
                    "name": payload.get("name", ""),
                    "summary": _truncate(payload.get("summary", ""), trunc_payload),
                    "syntax": _truncate(payload.get("syntax", ""), trunc_syntax),
                    "params": _truncate(payload.get("params", ""), trunc_syntax),
                    "versions": payload.get("versions", []),
                },
            }
            if include_full_code and _db is not None:
                db_id = payload.get("db_id") or str(point.id)
                cursor = await _db.execute(
                    "SELECT file_name, full_code FROM code_files WHERE id = ?", (db_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                if row:
                    entry["payload"]["file_name"] = row[0]
                    entry["payload"]["full_code"] = row[1]
                else:
                    entry["payload"]["file_name"] = ""
                    entry["payload"]["full_code"] = ""
            formatted.append(entry)

        if _db is not None:
            await _db.close()

        response = {
            "query": query,
            "collection": collection,
            "count": len(formatted),
            "include_full_code": include_full_code,
            "results": formatted,
        }
        return _truncate_response(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("qdrant_search failed: %s", e, exc_info=True)
        return _format_error(f"Search failed: {e}")


@mcp.tool(
    name="qdrant_collection_info",
    annotations={
        "title": "Qdrant collection info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def qdrant_collection_info(collection: str = "revit_api_knowledge") -> str:
    """Get metadata and configuration for a Qdrant collection."""
    try:
        client = _get_qdrant()
        info = await client.get_collection(collection_name=collection)
        vec = info.config.params.vectors

        response = {
            "name": collection,
            "points_count": info.points_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "vector_size": vec.size if hasattr(vec, "size") else None,
            "distance": vec.distance.name if hasattr(vec, "distance") else None,
        }
        return json.dumps(response, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("qdrant_collection_info failed: %s", e)
        return _format_error(f"Failed: {e}")


@mcp.tool(
    name="qdrant_list_collections",
    annotations={
        "title": "List Qdrant collections",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def qdrant_list_collections() -> str:
    """List all available Qdrant collections with point counts."""
    try:
        client = _get_qdrant()
        collections = (await client.get_collections()).collections
        targets = [c for c in collections if not c.name.startswith("ws-")]

        async def _read_info(name: str) -> dict:
            try:
                info = await client.get_collection(collection_name=name)
                vec = info.config.params.vectors
                return {
                    "name": name,
                    "points_count": info.points_count,
                    "indexed_vectors_count": info.indexed_vectors_count,
                    "vector_size": vec.size if hasattr(vec, "size") else None,
                    "distance": vec.distance.name if hasattr(vec, "distance") else None,
                }
            except Exception:
                return {"name": name, "error": "could not read info"}

        results = await asyncio.gather(*[_read_info(c.name) for c in targets])
        results.sort(key=lambda x: x.get("points_count", 0), reverse=True)
        return json.dumps(results, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("qdrant_list_collections failed: %s", e)
        return _format_error(f"Failed: {e}")


@mcp.tool(
    name="qdrant_get_point",
    annotations={
        "title": "Get Qdrant point by ID",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def qdrant_get_point(collection: str, point_id: int) -> str:
    """Retrieve a specific point from a Qdrant collection by its numeric ID."""
    try:
        client = _get_qdrant()
        points = await client.retrieve(
            collection_name=collection,
            ids=[point_id],
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return _format_error(f"Point {point_id} not found")
        pt = points[0]
        return json.dumps({"id": pt.id, "payload": pt.payload}, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("qdrant_get_point failed: %s", e)
        return _format_error(f"Failed: {e}")


# ─── rvtdocs.com Tools ─────────────────────────────────────────────────────

@mcp.tool(
    name="rvtdocs_search",
    annotations={
        "title": "Search Revit API on rvtdocs.com",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def rvtdocs_search(query: str, version: str = "2024", limit: int = 10) -> str:
    """Search Revit API documentation on rvtdocs.com by class/method name."""
    try:
        client = _get_http()
        r = await client.post(
            "https://rvtdocs.com/search/api/search",
            json={"query": query, "current_version": version, "include_description": True},
        )
        r.raise_for_status()
        data = r.json()

        results = data.get("current_version_results", [])[:limit]
        other = data.get("other_version_results", [])

        formatted = []
        for item in results:
            formatted.append({
                "title": item.get("title", ""),
                "type": item.get("type", ""),
                "namespace": item.get("namespace", ""),
                "description": item.get("description", ""),
                "version": item.get("year_version", ""),
                "url": f"https://rvtdocs.com{item.get('url', '')}",
            })

        response = {
            "query": query,
            "version": version,
            "count": len(formatted),
            "other_versions_count": len(other),
            "results": formatted,
        }
        return _truncate_response(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("rvtdocs_search failed: %s", e)
        return _format_error(f"rvtdocs search failed: {e}")


@mcp.tool(
    name="rvtdocs_get_page",
    annotations={
        "title": "Get rvtdocs API page content",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def rvtdocs_get_page(url: str, version: str = "2024") -> str:
    """Fetch full API documentation page from rvtdocs.com with code examples."""
    try:
        client = _get_http()

        # SSRF protection: only allow rvtdocs.com URLs
        base_url = url if url.startswith("http") else f"https://rvtdocs.com{url}"
        parsed = urlparse(base_url)
        if parsed.netloc not in ("rvtdocs.com", "www.rvtdocs.com"):
            return _format_error(f"URL must be on rvtdocs.com, got: {parsed.netloc}")
        base_url = base_url.split("?")[0]

        r = await client.get(f"{base_url}?ajax=1", follow_redirects=True)
        r.raise_for_status()
        html = r.text

        # Extract C# code snippets
        codes = re.findall(r"<code[^>]*>(.*?)</code>", html, re.DOTALL)
        csharp_signatures: list[str] = []
        csharp_examples: list[str] = []

        for c in codes:
            clean = re.sub(r"<[^>]+>", "", c)
            clean = re.sub(r"\s+", " ", clean).strip()
            if not clean or len(clean) < 30:
                continue
            if any(kw in clean for kw in ["class", "struct", "interface", "static", "void", "public"]):
                if "Create" in clean or "Get" in clean or "Set" in clean or "(" in clean:
                    csharp_examples.append(clean[:500])
                else:
                    csharp_signatures.append(clean[:500])

        # Extract description
        desc_match = re.search(
            r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html, re.IGNORECASE
        )
        description = desc_match.group(1) if desc_match else ""

        # Extract remarks
        remarks = ""
        rm = re.search(
            r"<h2[^>]*>Remarks</h2>\s*<div[^>]*>(.*?)(?:<h2|</div>\s*<h2)",
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if rm:
            remarks = re.sub(r"<[^>]+>", "", rm.group(1))
            remarks = re.sub(r"\s+", " ", remarks).strip()[:1000]

        # Find deprecated
        deprecated = ""
        dep_match = re.search(r"\[Obsolete[^\]]*\]|deprecated", html, re.IGNORECASE)
        if dep_match:
            ctx = html[max(0, dep_match.start() - 100) : dep_match.end() + 200]
            deprecated = re.sub(r"<[^>]+>", "", ctx)
            deprecated = re.sub(r"\s+", " ", deprecated).strip()[:500]

        response = {
            "url": base_url,
            "description": description[:500],
            "remarks": remarks[:1500] if remarks else "",
            "signatures": csharp_signatures[:5],
            "code_examples": csharp_examples[:5],
            "deprecation": deprecated,
        }
        return json.dumps(response, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("rvtdocs_get_page failed: %s", e)
        return _format_error(f"Failed to fetch page: {e}")


# ─── Cross-Version rvtdocs Tool ─────────────────────────────────────────────

@mcp.tool(
    name="rvtdocs_cross_version_search",
    annotations={
        "title": "Search Revit API across multiple versions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def rvtdocs_cross_version_search(
    query: str,
    limit: int = 5,
    versions: list[str] = ["2021", "2022", "2023", "2024", "2025", "2026", "2027"],
) -> str:
    """Search Revit API documentation across multiple Revit versions on rvtdocs.com."""
    try:
        client = _get_http()
        max_retries = _get_cfg("http_client", "max_retries", default=3)
        sem = asyncio.Semaphore(3)
        per_version_results: dict[str, list[dict]] = {}

        async def search_version(version: str) -> tuple[str, list[dict]]:
            async with sem:
                try:
                    r = await _retry_async(
                        lambda v=version: client.post(
                            "https://rvtdocs.com/search/api/search",
                            json={"query": query, "current_version": v, "include_description": True},
                        ),
                        max_retries=max_retries,
                    )
                    r.raise_for_status()
                    data = r.json()
                    raw = data.get("current_version_results", [])[:limit]
                    items = []
                    for item in raw:
                        items.append({
                            "title": item.get("title", ""),
                            "type": item.get("type", ""),
                            "namespace": item.get("namespace", ""),
                            "description": item.get("description", ""),
                            "url": f"https://rvtdocs.com{item.get('url', '')}",
                        })
                    return version, items
                except Exception as e:
                    _logger.warning("rvtdocs search failed for version %s: %s", version, e)
                    return version, []

        tasks = [search_version(v) for v in versions]
        for ver, items in await asyncio.gather(*tasks):
            per_version_results[ver] = items

        response = {
            "query": query,
            "versions_searched": versions,
            "results_by_version": per_version_results,
        }
        return _truncate_response(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("rvtdocs_cross_version_search failed: %s", e)
        return _format_error(f"Cross-version search failed: {e}")


# ─── Analyze Tool ───────────────────────────────────────────────────────────

@mcp.tool(
    name="analyze",
    annotations={
        "title": "Analyze search results with LLM",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def analyze_results(query: str, context: str, instructions: str = "") -> str:
    """Use RouterAI LLM to analyze Qdrant/rvtdocs search results."""
    if not os.environ.get("ROUTERAI_API_KEY"):
        return _format_error("ROUTERAI_API_KEY not set")
    try:
        system = (
            "You are a Revit API and Navisworks API research assistant. "
            "Analyze the provided search results and answer the user's question. "
            "Provide specific code examples, API references, and version compatibility notes. "
            f"{instructions}"
        )
        result = await _llm_chat(
            [
                {
                    "role": "user",
                    "content": f"## Research Question\n{query}\n\n## Context\n{context}",
                }
            ],
            system=system,
        )
        return _truncate_response(result)
    except Exception as e:
        _logger.error("analyze failed: %s", e)
        return _format_error(f"LLM analysis failed: {e}")


# ─── Combined Research Tool ─────────────────────────────────────────────────

@mcp.tool(
    name="research",
    annotations={
        "title": "Full research: Qdrant + rvtdocs + LLM analysis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def research(query: str, revit_version: str = "2024") -> str:
    """Complete research pipeline: Qdrant → rvtdocs (current + all past versions) → LLM analysis."""
    if not os.environ.get("ROUTERAI_API_KEY"):
        return _format_error("ROUTERAI_API_KEY not set for LLM analysis. Qdrant search still works.")

    try:
        qdrant_results = json.loads(
            await qdrant_search(query=query, collection="revit_api_knowledge", limit=8)
        )
        rvtdocs_results = json.loads(
            await rvtdocs_search(query=query, version=revit_version, limit=8)
        )
        config_versions = _get_cfg("revit_versions", default=["2021","2022","2023","2024","2025","2026","2027"])
        cross_version = json.loads(
            await rvtdocs_cross_version_search(query=query, limit=3, versions=config_versions)
        )

        context_parts: list[str] = []
        if "results" in qdrant_results:
            context_parts.append("## Qdrant Results (vector search)")
            for r in qdrant_results["results"]:
                context_parts.append(
                    f"- {r['payload']['name']} (score: {r['score']}): {r['payload']['summary'][:300]}"
                )
        if "results" in rvtdocs_results:
            context_parts.append(f"\n## rvtdocs Results (version {revit_version})")
            for r in rvtdocs_results["results"]:
                context_parts.append(f"- {r['title']} ({r['type']}): {r['description'][:300]}")

        if cross_version.get("results_by_version"):
            context_parts.append("\n## Cross-Version API Availability")
            for ver, items in cross_version["results_by_version"].items():
                titles = [i["title"] for i in items]
                if titles:
                    context_parts.append(f"- Revit {ver}: {', '.join(titles)}")
                else:
                    context_parts.append(f"- Revit {ver}: (no direct matches)")

        context = "\n".join(context_parts) if context_parts else "No results found."

        system = (
            f"You are a Revit API expert. Answer the question based on the provided search results. "
            f"Target Revit version: {revit_version}. "
            f"IMPORTANT: Check cross-version availability and note when APIs were introduced/changed/deprecated. "
            f"Provide code examples relevant to the target version. "
            f"If an API is deprecated or not available in {revit_version}, suggest alternatives."
        )
        result = await _llm_chat(
            [{"role": "user", "content": f"## Question\n{query}\n\n## Search Results\n{context}"}],
            system=system,
        )

        response = {
            "query": query,
            "revit_version": revit_version,
            "qdrant_count": qdrant_results.get("count", 0),
            "rvtdocs_count": rvtdocs_results.get("count", 0),
            "cross_version_searched": config_versions,
            "analysis": result,
        }
        return _truncate_response(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("research failed: %s", e, exc_info=True)
        return _format_error(f"Research failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI entrypoint
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="RevitNavisResearcher MCP Server")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to YAML config")
    parser.add_argument("--transport", choices=["stdio", "sse"], help="Transport mode")
    parser.add_argument("--host", type=str, help="SSE host")
    parser.add_argument("--port", type=int, help="SSE port")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    parser.add_argument("--log-format", choices=["text", "json"], help="Log format")
    return parser.parse_args(argv)


async def _amain(argv: Optional[list[str]] = None) -> None:
    """Async main entrypoint."""
    global _config, _logger

    args = _parse_args(argv)

    # Load config
    _config = _load_config(args.config)

    # Setup logging
    log_level = args.log_level or _get_cfg("logging", "level", default="INFO")
    log_format = args.log_format or _get_cfg("logging", "format", default="text")
    _logger = _setup_logging(log_level, log_format)

    # Resolve transport
    transport = args.transport or _get_cfg("transport", "mode", default="stdio")
    host = args.host or _get_cfg("transport", "host", default="0.0.0.0")
    port = args.port or _get_cfg("transport", "port", default=8000)

    # Register signal handlers for graceful shutdown (Unix only)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown_then_exit()))
        except (NotImplementedError, ValueError):
            pass  # Windows doesn't support add_signal_handler

    _logger.info("🚀 Starting RevitNavis MCP server (transport=%s)", transport)
    _logger.info("   Qdrant: %s", _get_cfg("qdrant", "url", default="http://localhost:6333"))
    _logger.info("   RouterAI base: %s", _get_cfg("llm", "base_url"))
    _logger.info("   Models: embed=%s, llm=%s", _get_cfg("llm", "embedding_model"), _get_cfg("llm", "chat_model"))

    api_key = os.environ.get("ROUTERAI_API_KEY", "")
    if not api_key or api_key in ("sk-placeholder", "sk-your-key-here"):
        _logger.warning("ROUTERAI_API_KEY not set or is a placeholder — LLM tools will fail")
    else:
        _logger.info("   RouterAI API key: OK")

    if transport == "sse":
        _logger.info("   SSE mode on http://%s:%d/mcp", host, port)
        mcp.settings.host = host
        mcp.settings.port = port
        try:
            await mcp.run_sse_async()
        finally:
            await _shutdown()
    else:
        _logger.info("   stdio mode — waiting for MCP messages...")
        try:
            await mcp.run_stdio_async()
        finally:
            await _shutdown()


async def _shutdown_then_exit() -> None:
    """Shutdown and exit."""
    await _shutdown()
    sys.exit(0)


def main(argv: Optional[list[str]] = None) -> None:
    """Synchronous entrypoint for console_scripts."""
    asyncio.run(_amain(argv))


if __name__ == "__main__":
    main()
