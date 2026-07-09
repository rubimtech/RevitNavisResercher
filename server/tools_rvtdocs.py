"""
rvtdocs.com search tools — replaced by SQLite queries against revit_api.db.
Tool names and signatures preserved for backward compatibility.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

import aiosqlite

from server.mcp_instance import mcp
from server.utils import format_error, truncate_response

_logger = logging.getLogger("revitnavis")

_DB_PATH = Path(__file__).resolve().parent.parent / "revit_api.db"


async def _get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(_DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


async def _rvtdocs_search_raw(query: str, version: str = "2024", limit: int = 10) -> dict:
    """SQLite-based replacement for rvtdocs.com search."""
    db = await _get_db()
    try:
        like = f"%{query}%"
        sql = """
            SELECT DISTINCT a.href, a.title, a.short_title, a.entry_type, a.namespace, a.description, a.tag
            FROM api_entries a
            JOIN api_entry_versions v ON v.href = a.href
            WHERE (a.title LIKE ? OR a.short_title LIKE ?) AND v.version = ?
            ORDER BY a.entry_type, a.title
            LIMIT ?
        """
        cursor = await db.execute(sql, (like, like, version, limit))
        rows = await cursor.fetchall()
        await cursor.close()

        results = []
        for r in rows:
            results.append({
                "title": r["title"],
                "type": r["entry_type"] or "",
                "namespace": r["namespace"] or "",
                "description": (r["description"] or "")[:300],
                "version": version,
                "url": r["href"],
            })

        return {
            "query": query,
            "version": version,
            "count": len(results),
            "other_versions_count": 0,
            "results": results,
        }
    except Exception as e:
        _logger.error("SQL rvtdocs search failed: %s", e)
        return {"query": query, "version": version, "count": 0, "other_versions_count": 0, "results": []}
    finally:
        await db.close()


async def _rvtdocs_cross_version_raw(
    query: str,
    limit: int = 5,
    versions: Optional[list[str]] = None,
) -> dict:
    """SQLite-based replacement for cross-version rvtdocs search."""
    if versions is None:
        versions = ["2021", "2022", "2023", "2024", "2025", "2026", "2027"]

    db = await _get_db()
    try:
        like = f"%{query}%"
        per_version_results: dict[str, list[dict]] = {}

        for version in versions:
            sql = """
                SELECT DISTINCT a.href, a.title, a.short_title, a.entry_type, a.namespace, a.description
                FROM api_entries a
                JOIN api_entry_versions v ON v.href = a.href
                WHERE (a.title LIKE ? OR a.short_title LIKE ?) AND v.version = ?
                ORDER BY a.entry_type, a.title
                LIMIT ?
            """
            cursor = await db.execute(sql, (like, like, version, limit))
            rows = await cursor.fetchall()
            await cursor.close()

            items = []
            for r in rows:
                items.append({
                    "title": r["title"],
                    "type": r["entry_type"] or "",
                    "namespace": r["namespace"] or "",
                    "description": (r["description"] or "")[:300],
                    "url": r["href"],
                })
            per_version_results[version] = items

        return {
            "query": query,
            "versions_searched": versions,
            "results_by_version": per_version_results,
        }
    except Exception as e:
        _logger.error("SQL cross-version search failed: %s", e)
        return {"query": query, "versions_searched": versions, "results_by_version": {}}
    finally:
        await db.close()


def _extract_href(url_or_href: str) -> str:
    """Extract href from a full rvtdocs URL or return as-is."""
    m = re.search(r"/\d+/([a-f0-9-]+\.htm)", url_or_href)
    if m:
        return m.group(1)
    return url_or_href


@mcp.tool(
    name="rvtdocs_search",
    annotations={
        "title": "Search Revit API on rvtdocs.com (via local DB)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def rvtdocs_search(query: str, version: str = "2024", limit: int = 10) -> str:
    """Search Revit API documentation on rvtdocs.com by class/method name (powered by local SQLite DB)."""
    try:
        result = await _rvtdocs_search_raw(query, version, limit)
        return truncate_response(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("rvtdocs_search failed: %s", e)
        return format_error(f"rvtdocs search failed: {e}")


@mcp.tool(
    name="rvtdocs_get_page",
    annotations={
        "title": "Get API page markdown from local DB (cached rvtdocs content)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def rvtdocs_get_page(url: str) -> str:
    """Fetch API documentation page content from local SQLite cache (previously fetched from rvtdocs.com)."""
    try:
        href = _extract_href(url)
        db = await _get_db()
        try:
            cursor = await db.execute(
                "SELECT title, entry_type, namespace FROM api_entries WHERE href = ?",
                (href,),
            )
            entry = await cursor.fetchone()
            await cursor.close()

            cursor = await db.execute(
                "SELECT content_md, fetched_at FROM api_content WHERE href = ?",
                (href,),
            )
            content = await cursor.fetchone()
            await cursor.close()

            if not content or not content["content_md"]:
                return json.dumps({
                    "url": url,
                    "href": href,
                    "error": f"Content not found in local DB for {href}",
                }, indent=2, ensure_ascii=False)

            result = {
                "url": url,
                "href": href,
            }
            if entry:
                result["title"] = entry["title"]
                result["type"] = entry["entry_type"]
                result["namespace"] = entry["namespace"]
            result["content_md"] = content["content_md"]
            result["fetched_at"] = content["fetched_at"]

            return result["content_md"]
        finally:
            await db.close()
    except Exception as e:
        _logger.error("rvtdocs_get_page failed: %s", e)
        return json.dumps({"error": f"Failed: {e}"}, indent=2)


@mcp.tool(
    name="rvtdocs_cross_version_search",
    annotations={
        "title": "Search Revit API across multiple versions (via local DB)",
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
    """Search Revit API documentation across multiple Revit versions (powered by local SQLite DB)."""
    try:
        result = await _rvtdocs_cross_version_raw(query, limit, versions)
        return truncate_response(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("rvtdocs_cross_version_search failed: %s", e)
        return format_error(f"Cross-version search failed: {e}")
