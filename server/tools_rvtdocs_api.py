"""
Remote HTTP API tools — replaces direct SQLite queries with calls to the
RevitNavis FastAPI backend (RVTDOC_API_URL environment variable).
"""

import json
import logging
import os
from typing import Optional

import httpx

from server.mcp_instance import mcp
from server.utils import format_error, truncate_response

_logger = logging.getLogger("revitnavis-api")

API_BASE = os.environ.get("RVTDOC_API_URL", "").rstrip("/")
_API_TIMEOUT = 60.0


async def _api_get(path: str, params: Optional[dict] = None) -> dict:
    if not API_BASE:
        return {"error": "RVTDOC_API_URL not set"}
    url = f"{API_BASE}/api/tree{path}"
    try:
        async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        _logger.error("API %s %s -> %s", path, params, e.response.status_code)
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        _logger.error("API %s %s failed: %s", path, params, e)
        return {"error": str(e)}


async def _api_get_text(path: str, params: Optional[dict] = None) -> str:
    if not API_BASE:
        return json.dumps({"error": "RVTDOC_API_URL not set"})
    url = f"{API_BASE}/api/tree{path}"
    try:
        async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        _logger.error("API %s failed: %s", path, e)
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="rvtdocs_search",
    annotations={
        "title": "Search Revit API on remote server (via HTTP API)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def rvtdocs_search(query: str, version: str = "2024", limit: int = 10) -> str:
    """Search Revit API documentation via remote HTTP API by class/method name."""
    try:
        data = await _api_get("/search", {"q": query, "version": version, "limit": str(limit)})
        items = data.get("items", data)
        if isinstance(items, list):
            result = {
                "query": query,
                "version": version,
                "count": len(items),
                "results": [
                    {"title": i.get("title", ""), "type": i.get("entry_type", ""),
                     "path": i.get("path", ""), "has_content": i.get("has_content", False)}
                    for i in items
                ],
            }
        else:
            result = data
        return truncate_response(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("rvtdocs_search via API failed: %s", e)
        return format_error(f"Search failed: {e}")


@mcp.tool(
    name="rvtdocs_get_page",
    annotations={
        "title": "Get API page content from remote server (via HTTP API)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def rvtdocs_get_page(url: str) -> str:
    """Fetch API documentation page content from remote HTTP API."""
    try:
        data = await _api_get("/content", {"href": url})
        md = data.get("content_md", "")
        if md:
            return md
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("rvtdocs_get_page via API failed: %s", e)
        return format_error(f"Failed: {e}")


@mcp.tool(
    name="rvtdocs_cross_version_search",
    annotations={
        "title": "Search Revit API across multiple versions (via HTTP API)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def rvtdocs_cross_version_search(
    query: str,
    limit: int = 5,
    versions: Optional[list[str]] = None,
) -> str:
    """Search Revit API documentation across multiple Revit versions via remote HTTP API."""
    try:
        if not versions:
            versions = ["2022", "2023", "2024", "2025", "2026", "2027"]
        per_version: dict[str, list] = {}
        for ver in versions:
            data = await _api_get("/search", {"q": query, "version": ver, "limit": str(limit)})
            items = data.get("items", data)
            if isinstance(items, list):
                per_version[ver] = [
                    {"title": i.get("title", ""), "type": i.get("entry_type", ""),
                     "path": i.get("path", "")}
                    for i in items
                ]
            else:
                per_version[ver] = []
        result = {
            "query": query,
            "versions_searched": versions,
            "results_by_version": per_version,
        }
        return truncate_response(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("cross_version_search via API failed: %s", e)
        return format_error(f"Cross-version search failed: {e}")


@mcp.tool(
    name="sql_search_api",
    annotations={
        "title": "Search API entries (via remote HTTP API)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sql_search_api(
    query: str,
    limit: int = 10,
    entry_type: Optional[str] = None,
) -> str:
    """Search API entries by name across all versions via remote HTTP API."""
    try:
        params = {"q": query, "limit": str(limit)}
        data = await _api_get("/search", params)
        items = data.get("items", data)
        if isinstance(items, list):
            filtered = [i for i in items if not entry_type or i.get("entry_type") == entry_type] if entry_type else items
            result = {
                "query": query,
                "entry_type_filter": entry_type,
                "count": len(filtered),
                "results": [
                    {"title": i.get("title", ""), "href": i.get("href", ""),
                     "type": i.get("entry_type", ""), "path": i.get("path", "")}
                    for i in filtered
                ],
            }
        else:
            result = {"query": query, "error": "Unexpected response format", "raw": data}
        return truncate_response(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("sql_search_api via API failed: %s", e)
        return format_error(f"Search failed: {e}")


@mcp.tool(
    name="sql_get_api_content",
    annotations={
        "title": "Get API entry content (via remote HTTP API)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sql_get_api_content(href: str) -> str:
    """Get markdown content for an API entry from remote server."""
    try:
        data = await _api_get("/content", {"href": href})
        md = data.get("content_md", "")
        return md if md else json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("sql_get_api_content via API failed: %s", e)
        return format_error(f"Failed: {e}")


@mcp.tool(
    name="sql_get_api_hierarchy",
    annotations={
        "title": "Get API hierarchy tree (via remote HTTP API)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sql_get_api_hierarchy(href: str, version: str = "2024") -> str:
    """Get the hierarchy tree for an API entry from remote server."""
    try:
        namespaces = await _api_get("/namespaces", {"version": version})
        items = namespaces.get("items", namespaces)
        result = {
            "version": version,
            "hierarchy": items,
            "note": "Tree data available via /api/tree/children endpoint",
        }
        return truncate_response(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("sql_get_api_hierarchy via API failed: %s", e)
        return format_error(f"Failed: {e}")


@mcp.tool(
    name="sql_search_api_content",
    annotations={
        "title": "Search API entries with content (via remote HTTP API)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sql_search_api_content(
    query: str,
    limit: int = 10,
    entry_type: Optional[str] = None,
    version: str = "",
) -> str:
    """Search API entries and return their cached content from remote server."""
    try:
        params = {"q": query, "limit": str(limit), "version": version or "2024"}
        data = await _api_get("/search", params)
        items = data.get("items", data)
        if isinstance(items, list):
            filtered = [i for i in items if not entry_type or i.get("entry_type") == entry_type] if entry_type else items
            results = []
            for item in filtered[:5]:
                content_data = await _api_get("/content", {"href": item.get("href", "")})
                results.append({
                    "title": item.get("title", ""),
                    "type": item.get("entry_type", ""),
                    "content_md": content_data.get("content_md", "")[:2000] if content_data.get("content_md") else None,
                })
            result = {
                "query": query,
                "count": len(results),
                "results": results,
            }
        else:
            result = {"query": query, "error": "Unexpected response format"}
        return truncate_response(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("sql_search_api_content via API failed: %s", e)
        return format_error(f"Search failed: {e}")
