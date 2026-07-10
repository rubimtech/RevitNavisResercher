#!/usr/bin/env python3
"""
pg_client.py — Async PostgreSQL client using asyncpg.

Provides connection pooling and query helpers for the Revit API data browser.
"""

import logging
import os
from typing import Any, Optional

import asyncpg

_logger = logging.getLogger("revitnavis-pg")

_pool: Optional[asyncpg.Pool] = None


def _pg_config() -> dict:
    return {
        "host": os.environ.get("PG_HOST", "localhost"),
        "port": int(os.environ.get("PG_PORT", "5432")),
        "database": os.environ.get("PG_DB", "revitnavis"),
        "user": os.environ.get("PG_USER", "postgres"),
        "password": os.environ.get("PG_PASSWORD", "postgres"),
    }


async def init_pool(min_size: int = 2, max_size: int = 10):
    global _pool
    if _pool is not None:
        return
    cfg = _pg_config()
    try:
        _pool = await asyncpg.create_pool(**cfg, min_size=min_size, max_size=max_size)
        _logger.info("PG pool created: %s:%s/%s", cfg["host"], cfg["port"], cfg["database"])
    except Exception as e:
        _logger.warning("PG pool init failed (DB may not be available): %s", e)


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def fetch(query: str, *args) -> list[asyncpg.Record]:
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args) -> Optional[asyncpg.Record]:
    if _pool is None:
        return None
    async with _pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def get_versions() -> list[str]:
    rows = await fetch(
        "SELECT DISTINCT version FROM api_entry_versions ORDER BY version"
    )
    return [r["version"] for r in rows]


async def get_namespaces(version: str) -> list[dict]:
    rows = await fetch(
        """
        SELECT ae.href, ae.title, ae.entry_type
        FROM api_version_tree vt
        JOIN api_entries ae ON vt.href = ae.href
        WHERE vt.version = $1 AND vt.depth = 1
        ORDER BY vt.sort_order
        """,
        version,
    )
    return [dict(r) for r in rows]


async def get_children(version: str, parent_href: str) -> list[dict]:
    rows = await fetch(
        """
        SELECT ae.href, ae.title, ae.entry_type,
               (SELECT COUNT(*) FROM api_version_tree vt2
                WHERE vt2.version = $1 AND vt2.parent_href = ae.href) AS child_count,
               c.content_md IS NOT NULL AS has_content
        FROM api_version_tree vt
        JOIN api_entries ae ON vt.href = ae.href
        LEFT JOIN api_content c ON ae.href = c.href
        WHERE vt.version = $1 AND vt.parent_href = $2
        ORDER BY vt.sort_order
        """,
        version,
        parent_href,
    )
    return [dict(r) for r in rows]


async def get_content(href: str, version: str) -> Optional[dict]:
    row = await fetchrow(
        """
        SELECT ae.href, ae.title, ae.entry_type, ae.namespace, ae.description,
               ae.path, ae.member_of, c.content_md
        FROM api_entries ae
        LEFT JOIN api_content c ON ae.href = c.href
        WHERE ae.href = $1
        """,
        href,
    )
    if row is None:
        return None
    return dict(row)


async def search_entries(version: str, query: str, limit: int = 20) -> list[dict]:
    rows = await fetch(
        """
        SELECT ae.href, ae.title, ae.entry_type, ae.path,
               c.content_md IS NOT NULL AS has_content
        FROM api_entry_versions ev
        JOIN api_entries ae ON ev.href = ae.href
        LEFT JOIN api_content c ON ae.href = c.href
        WHERE ev.version = $1
          AND (ae.title ILIKE $2 OR ae.short_title ILIKE $2 OR ae.path ILIKE $2
               OR c.content_md ILIKE $2)
        ORDER BY
          CASE WHEN ae.title ILIKE $4 THEN 0
               WHEN ae.short_title ILIKE $4 THEN 1
               ELSE 2 END,
          ae.title
        LIMIT $3
        """,
        version,
        f"%{query}%",
        limit,
        f"{query}%",
    )
    return [dict(r) for r in rows]


async def get_code_files(limit: int = 20, offset: int = 0) -> list[dict]:
    rows = await fetch(
        "SELECT id, file_name, summary FROM code_files ORDER BY file_name LIMIT $1 OFFSET $2",
        limit,
        offset,
    )
    return [dict(r) for r in rows]


async def get_code_file(file_id: str) -> Optional[dict]:
    row = await fetchrow(
        "SELECT id, file_name, file_path, summary, full_code FROM code_files WHERE id = $1",
        file_id,
    )
    return dict(row) if row else None


async def get_version_diffs(version_from: str, version_to: str, limit: int = 100, offset: int = 0) -> list[dict]:
    rows = await fetch(
        """
        SELECT d.version_from, d.version_to, d.href, d.diff_type, d.old_status, d.new_status,
               ae.title, ae.entry_type, ae.path
        FROM api_diffs d
        JOIN api_entries ae ON d.href = ae.href
        WHERE (d.version_from = $1 AND d.version_to = $2)
           OR (d.version_from = $2 AND d.version_to = $1)
        ORDER BY d.diff_type, ae.title
        LIMIT $3 OFFSET $4
        """,
        version_from, version_to, limit, offset,
    )
    return [dict(r) for r in rows]


async def count_version_diffs(version_from: str, version_to: str) -> int:
    row = await fetchrow(
        """
        SELECT COUNT(*) as cnt FROM api_diffs d
        WHERE (d.version_from = $1 AND d.version_to = $2)
           OR (d.version_from = $2 AND d.version_to = $1)
        """,
        version_from, version_to,
    )
    return row["cnt"] if row else 0


async def get_whatsnew(version: str) -> list[dict]:
    rows = await fetch(
        """
        SELECT id, version, section, subsection, title, content, content_type
        FROM whatsnew_entries
        WHERE version = $1
        ORDER BY id
        """,
        version,
    )
    return [dict(r) for r in rows]
