"""
rvtdocs.com search tools for the MCP server.
"""

import asyncio
import json
import logging

from server.config import get_cfg
from server.mcp_instance import mcp
from server.state import get_http
from server.utils import format_error, truncate_response, retry_async
from server.rvtdocs_parser import fetch_and_parse_rvtdocs_page

_logger = logging.getLogger("revitnavis")


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
        client = get_http()
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
        return truncate_response(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("rvtdocs_search failed: %s", e)
        return format_error(f"rvtdocs search failed: {e}")


@mcp.tool(
    name="rvtdocs_get_page",
    annotations={
        "title": "Get rvtdocs API page content (markdown)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def rvtdocs_get_page(url: str) -> str:
    """Fetch a Revit API documentation page from rvtdocs.com as structured markdown."""
    try:
        result = await fetch_and_parse_rvtdocs_page(url)
        if "error" in result:
            return json.dumps(result, indent=2, ensure_ascii=False)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("rvtdocs_get_page failed: %s", e)
        return json.dumps({"error": f"Failed: {e}"}, indent=2)


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
        client = get_http()
        sem = asyncio.Semaphore(3)
        per_version_results: dict[str, list[dict]] = {}

        async def search_version(version: str) -> tuple[str, list[dict]]:
            async with sem:
                try:
                    r = await retry_async(
                        lambda v=version: client.post(
                            "https://rvtdocs.com/search/api/search",
                            json={"query": query, "current_version": v, "include_description": True},
                        ),
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
        return truncate_response(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("rvtdocs_cross_version_search failed: %s", e)
        return format_error(f"Cross-version search failed: {e}")
