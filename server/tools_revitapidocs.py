"""
revitapidocs.com search tools — replaced by SQLite queries against revit_api.db.
Tool names and signatures preserved for backward compatibility.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import aiosqlite

from server.mcp_instance import mcp
from server.utils import format_error, truncate_response

_logger = logging.getLogger("revitnavis")

_DB_PATH = Path(__file__).resolve().parent.parent / "revit_api.db"

_SEARCH_RESULT_TYPES = [
    "Class", "Constructor", "Method", "Methods",
    "Property", "Properties", "Interface", "Enumeration",
]


async def _get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(_DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


async def _search_revitapidocs_com(query: str, max_results: int = 10) -> list[dict]:
    """SQLite-based replacement for revitapidocs.com autocomplete search."""
    db = await _get_db()
    try:
        like = f"%{query}%"
        sql = """
            SELECT DISTINCT a.href, a.title, a.short_title, a.entry_type, a.namespace
            FROM api_entries a
            WHERE a.title LIKE ? OR a.short_title LIKE ?
            ORDER BY a.entry_type, a.title
            LIMIT ?
        """
        cursor = await db.execute(sql, (like, like, max_results))
        rows = await cursor.fetchall()
        await cursor.close()

        results = []
        for r in rows:
            entry_type = r["entry_type"] or "Unknown"
            if entry_type == "Members":
                continue
            results.append({
                "title": r["title"],
                "type": entry_type,
                "url": r["href"],
                "source": "revit_api.db",
            })
        return results
    except Exception as e:
        _logger.warning("SQL revitapidocs search failed: %s", e)
        return []
    finally:
        await db.close()


async def _search_both_sources(
    query: str, version: str = "2024", limit: int = 10
) -> list[dict]:
    """Search both api_entries (all) and version-filtered entries, deduplicate by href."""
    db = await _get_db()
    try:
        like = f"%{query}%"

        sql_all = """
            SELECT DISTINCT a.href, a.title, a.short_title, a.entry_type, a.namespace, a.description
            FROM api_entries a
            WHERE a.title LIKE ? OR a.short_title LIKE ?
            ORDER BY a.entry_type, a.title
            LIMIT ?
        """
        cursor = await db.execute(sql_all, (like, like, limit))
        all_rows = await cursor.fetchall()
        await cursor.close()

        sql_versioned = """
            SELECT DISTINCT a.href, a.title, a.short_title, a.entry_type, a.namespace, a.description
            FROM api_entries a
            JOIN api_entry_versions v ON v.href = a.href
            WHERE (a.title LIKE ? OR a.short_title LIKE ?) AND v.version = ?
            ORDER BY a.entry_type, a.title
            LIMIT ?
        """
        cursor = await db.execute(sql_versioned, (like, like, version, limit))
        versioned_rows = await cursor.fetchall()
        await cursor.close()

        seen_hrefs: set[str] = set()
        combined: list[dict] = []

        for r in versioned_rows:
            seen_hrefs.add(r["href"])
            combined.append({
                "title": r["title"],
                "type": r["entry_type"] or "",
                "namespace": r["namespace"] or "",
                "description": (r["description"] or "")[:300],
                "url": r["href"],
                "source": f"revit_api.db (v{version})",
            })

        for r in all_rows:
            if r["href"] not in seen_hrefs:
                seen_hrefs.add(r["href"])
                combined.append({
                    "title": r["title"],
                    "type": r["entry_type"] or "",
                    "namespace": r["namespace"] or "",
                    "description": (r["description"] or "")[:300],
                    "url": r["href"],
                    "source": "revit_api.db",
                })

        type_order = {t: i for i, t in enumerate(_SEARCH_RESULT_TYPES)}
        combined.sort(key=lambda x: type_order.get(x.get("type", ""), 99))
        return combined[:limit]
    except Exception as e:
        _logger.warning("SQL combined search failed: %s", e)
        return []
    finally:
        await db.close()


@mcp.tool(
    name="revitapidocs_search",
    annotations={
        "title": "Search Revit API on revitapidocs.com (via local DB)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def revitapidocs_search(query: str, limit: int = 10) -> str:
    """Search Revit API documentation on revitapidocs.com (powered by local SQLite DB)."""
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
        "title": "Search Revit API (local DB combined search)",
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
    """Search Revit API across all sources (powered by local SQLite DB)."""
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
