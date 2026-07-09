"""
SQLite tools for revit_api.db — API entries, version availability, diffs, hierarchy.
"""

import json
import logging
from typing import Optional

import aiosqlite

from server.mcp_instance import mcp
from server.utils import format_error, truncate_response

from portable.paths import get_revit_api_db

_logger = logging.getLogger("revitnavis")

_DB_PATH = get_revit_api_db()


async def _get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(_DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


@mcp.tool(
    name="sql_search_api",
    annotations={
        "title": "Search API entries in SQLite database",
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
    """Search API entries by name across all versions (revit_api.db → api_entries)."""
    db = await _get_db()
    try:
        like = f"%{query}%"
        sql = """
            SELECT href, title, short_title, namespace, entry_type, member_of, tag
            FROM api_entries
            WHERE (title LIKE ? OR short_title LIKE ?)
        """
        params: list = [like, like]
        if entry_type:
            sql += " AND entry_type = ?"
            params.append(entry_type)
        sql += " ORDER BY entry_type, title LIMIT ?"
        params.append(limit)

        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()

        results = []
        for r in rows:
            results.append({
                "href": r["href"],
                "title": r["title"],
                "short_title": r["short_title"],
                "namespace": r["namespace"],
                "entry_type": r["entry_type"],
                "member_of": r["member_of"],
                "tag": r["tag"],
            })

        return json.dumps({
            "query": query,
            "entry_type": entry_type,
            "count": len(results),
            "results": results,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("sql_search_api failed: %s", e)
        return format_error(f"Search failed: {e}")
    finally:
        await db.close()


@mcp.tool(
    name="sql_get_api_content",
    annotations={
        "title": "Get API page markdown content from local DB",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sql_get_api_content(href: str) -> str:
    """Get markdown content for an API entry from api_content table (cached from rvtdocs.com)."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT title, entry_type, tag, namespace FROM api_entries WHERE href = ?",
            (href,),
        )
        entry = await cursor.fetchone()
        await cursor.close()

        cursor = await db.execute(
            "SELECT content_md, fetched_at, fetch_error FROM api_content WHERE href = ?",
            (href,),
        )
        content_row = await cursor.fetchone()
        await cursor.close()

        result = {
            "href": href,
            "entry": dict(entry) if entry else None,
        }

        if content_row:
            result["content_md"] = content_row["content_md"] or ""
            result["fetched_at"] = content_row["fetched_at"] or ""
            result["fetch_error"] = content_row["fetch_error"] or ""
        else:
            result["content_md"] = ""
            result["note"] = "No cached content found in api_content table"

        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("sql_get_api_content failed: %s", e)
        return format_error(f"Failed: {e}")
    finally:
        await db.close()


@mcp.tool(
    name="sql_search_api_content",
    annotations={
        "title": "Search API entries and return their cached markdown content",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sql_search_api_content(
    query: str,
    version: str = "",
    limit: int = 5,
    entry_type: Optional[str] = None,
) -> str:
    """Search API entries and return their cached content from api_content table.
    Optionally filter by version (checks api_entry_versions table)."""
    db = await _get_db()
    try:
        like = f"%{query}%"
        params: list = [like, like]

        if version:
            sql = """
                SELECT DISTINCT a.href, a.title, a.short_title, a.entry_type, a.namespace, a.tag, a.member_of
                FROM api_entries a
                JOIN api_entry_versions v ON v.href = a.href
                WHERE (a.title LIKE ? OR a.short_title LIKE ?) AND v.version = ?
            """
            params.append(version)
        else:
            sql = """
                SELECT href, title, short_title, entry_type, namespace, tag, member_of
                FROM api_entries
                WHERE (title LIKE ? OR short_title LIKE ?)
            """

        if entry_type:
            sql += " AND entry_type = ?"
            params.append(entry_type)

        sql += " ORDER BY entry_type, title LIMIT ?"
        params.append(limit)

        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()

        results = []
        for r in rows:
            href = r["href"]
            cursor = await db.execute(
                "SELECT content_md FROM api_content WHERE href = ? AND content_md IS NOT NULL",
                (href,),
            )
            content_row = await cursor.fetchone()
            await cursor.close()

            entry = {
                "href": href,
                "title": r["title"],
                "short_title": r["short_title"],
                "entry_type": r["entry_type"],
                "namespace": r["namespace"],
                "tag": r["tag"],
                "member_of": r["member_of"],
            }
            if content_row:
                entry["content_md"] = content_row["content_md"]
            results.append(entry)

        return json.dumps({
            "query": query,
            "version": version or "all",
            "entry_type": entry_type or "all",
            "count": len(results),
            "results": results,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("sql_search_api_content failed: %s", e)
        return format_error(f"Search failed: {e}")
    finally:
        await db.close()


@mcp.tool(
    name="sql_get_api_hierarchy",
    annotations={
        "title": "Get namespace → class → member hierarchy path",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sql_get_api_hierarchy(href: str, version: str = "2026") -> str:
    """Get the full hierarchy tree for an API entry from namespace down to member."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """SELECT a.title, a.href, a.entry_type, a.tag, vt.parent_href, vt.depth
               FROM api_version_tree vt
               JOIN api_entries a ON a.href = vt.href
               WHERE vt.version = ? AND vt.href = ?""",
            (version, href),
        )
        node = await cursor.fetchone()
        await cursor.close()

        if not node:
            return format_error(f"Entry not found in version tree: {href} @ {version}")

        # Walk up to root
        chain = [{
            "href": node["href"],
            "title": node["title"],
            "entry_type": node["entry_type"],
            "tag": node["tag"],
            "depth": node["depth"],
        }]

        parent_href = node["parent_href"]
        while parent_href:
            cursor = await db.execute(
                """SELECT a.title, a.href, a.entry_type, a.tag, vt.parent_href, vt.depth
                   FROM api_version_tree vt
                   JOIN api_entries a ON a.href = vt.href
                   WHERE vt.version = ? AND vt.href = ?""",
                (version, parent_href),
            )
            parent = await cursor.fetchone()
            await cursor.close()
            if not parent:
                break
            chain.append({
                "href": parent["href"],
                "title": parent["title"],
                "entry_type": parent["entry_type"],
                "tag": parent["tag"],
                "depth": parent["depth"],
            })
            parent_href = parent["parent_href"]

        chain.reverse()
        path = " / ".join(c["title"] for c in chain)

        return json.dumps({
            "version": version,
            "href": href,
            "hierarchy": chain,
            "path": path,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("sql_get_api_hierarchy failed: %s", e)
        return format_error(f"Failed: {e}")
    finally:
        await db.close()


@mcp.tool(
    name="sql_get_page_url",
    annotations={
        "title": "Get revitapidocs.com URL for an API entry",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sql_get_page_url(href: str, version: str = "2026") -> str:
    """Get the revitapidocs.com URL for an API entry and check if it exists in that version."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT title, short_title, entry_type FROM api_entries WHERE href = ?", (href,)
        )
        entry = await cursor.fetchone()
        await cursor.close()

        if not entry:
            return format_error(f"API entry not found: {href}")

        cursor = await db.execute(
            "SELECT version FROM api_entry_versions WHERE href = ? AND version = ?",
            (href, version),
        )
        exists = await cursor.fetchone() is not None
        await cursor.close()

        url = f"https://www.revitapidocs.com/{version}/{href}"
        return json.dumps({
            "href": href,
            "title": entry["title"],
            "entry_type": entry["entry_type"],
            "version": version,
            "available": exists,
            "url": url,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("sql_get_page_url failed: %s", e)
        return format_error(f"Failed: {e}")
    finally:
        await db.close()
