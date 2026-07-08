"""
revitapidocs.com search and combined Revit API search tools.
"""

import json
import logging
import re
import time

from server.mcp_instance import mcp
from server.state import get_http
from server.utils import format_error, truncate_response

_logger = logging.getLogger("revitnavis")

_SEARCH_RESULT_TYPES = [
    "Class", "Constructor", "Method", "Methods",
    "Property", "Properties", "Interface", "Enumeration",
]


async def _search_revitapidocs_com(query: str, max_results: int = 10) -> list[dict]:
    """Search Revit API on revitapidocs.com via Construct.io autocomplete."""
    try:
        client = get_http()
        timestamp = int(time.time() * 1000)
        encoded_query = re.sub(r"[^a-zA-Z0-9_ .]", "", query).strip().replace(" ", "+")
        url = (
            f"https://ac.cnstrc.com/autocomplete/{encoded_query}"
            f"?query={encoded_query}"
            f"&autocomplete_key=key_yyAC1mb0cTgZTwSo"
            f"&c=ciojs-2.1233.4&num_results={max_results}"
            f"&i=d705c917-8e5a-491f-8bc4-9b43e78de48c&s=10&_dt={timestamp}"
        )
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

        results: list[dict] = []
        for item in (data.get("sections") or {}).get("Products") or []:
            title: str = item.get("value", "")
            raw_url: str = (item.get("data") or {}).get("url", "")
            result_type = _parse_revitapidocs_type(title)
            if result_type == "Members":
                continue
            slug = raw_url.split(".")[0] if "." in raw_url else raw_url
            results.append({
                "title": title,
                "type": result_type,
                "url": slug,
                "source": "revitapidocs.com",
            })
        return results
    except Exception as e:
        _logger.warning("revitapidocs.com search failed: %s", e)
        return []


def _parse_revitapidocs_type(title: str) -> str:
    parts = title.strip().split()
    last = parts[-1] if parts else ""
    for t in (*_SEARCH_RESULT_TYPES, "Members"):
        if last == t:
            return t
    return "Unknown"


async def _search_both_sources(
    query: str, version: str = "2024", limit: int = 10
) -> list[dict]:
    """Search both rvtdocs.com and revitapidocs.com, deduplicate by URL."""
    rvtdocs_results: list[dict] = []
    try:
        client = get_http()
        r = await client.post(
            "https://rvtdocs.com/search/api/search",
            json={"query": query, "current_version": version, "include_description": True},
        )
        r.raise_for_status()
        data = r.json()
        for item in data.get("current_version_results", [])[:limit]:
            rvtdocs_results.append({
                "title": item.get("title", ""),
                "type": item.get("type", ""),
                "namespace": item.get("namespace", ""),
                "description": item.get("description", ""),
                "url": item.get("url", ""),
                "source": "rvtdocs.com",
            })
    except Exception as e:
        _logger.warning("rvtdocs.com search failed: %s", e)

    rap_results = await _search_revitapidocs_com(query, limit * 2)

    seen_urls: set[str] = set()
    combined: list[dict] = []
    for r in rvtdocs_results:
        key = r["url"]
        if key not in seen_urls:
            seen_urls.add(key)
            combined.append(r)
    for r in rap_results:
        key = r["url"]
        if key not in seen_urls:
            seen_urls.add(key)
            combined.append(r)

    type_order = {t: i for i, t in enumerate(_SEARCH_RESULT_TYPES)}
    combined.sort(key=lambda x: type_order.get(x.get("type", ""), 99))
    return combined[:limit]


@mcp.tool(
    name="revitapidocs_search",
    annotations={
        "title": "Search Revit API on revitapidocs.com",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def revitapidocs_search(query: str, limit: int = 10) -> str:
    """Search Revit API documentation on revitapidocs.com using Construct.io autocomplete."""
    try:
        results = await _search_revitapidocs_com(query, limit)
        response = {
            "query": query,
            "count": len(results),
            "results": results,
        }
        return json.dumps(response, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("revitapidocs_search failed: %s", e)
        return json.dumps({"error": f"Search failed: {e}"}, indent=2)


@mcp.tool(
    name="revit_api_search",
    annotations={
        "title": "Search Revit API (rvtdocs + revitapidocs combined)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def revit_api_search(
    query: str,
    version: str = "2024",
    limit: int = 10,
) -> str:
    """Search Revit API across both rvtdocs.com and revitapidocs.com with deduplication."""
    try:
        results = await _search_both_sources(query, version, limit)
        response = {
            "query": query,
            "version": version,
            "count": len(results),
            "results": results,
        }
        return json.dumps(response, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("revit_api_search failed: %s", e)
        return json.dumps({"error": f"Search failed: {e}"}, indent=2)
