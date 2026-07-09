import json
import logging
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import HTTPException

from .cache import cache_get, cache_key, cache_set
from .clients import get_qdrant
from .config import get_cfg
from .embeddings import get_embedding
from .models import SearchRequest

_logger = logging.getLogger("revitnavis-web")

_DB_PATH = Path(__file__).resolve().parent.parent / "revit_api.db"


def _truncate(text: str, limit: int = 600) -> str:
    return text[:limit] + "..." if len(text) > limit else text


async def _get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(_DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


async def search_qdrant(req: SearchRequest, api_key: Optional[str] = None):
    ck = cache_key(req)
    cached = cache_get(ck)
    if cached:
        return cached
    try:
        client = get_qdrant()
        vector = await get_embedding(req.query, api_key=api_key)
        trunc_payload = get_cfg("output", "truncate_payload", default=400)
        trunc_syntax = get_cfg("output", "truncate_syntax", default=200)
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
        cache_set(ck, result)
        return result
    except Exception as e:
        _logger.error("qdrant search failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


async def _search_rvtdocs(query: str, limit: int) -> list[dict]:
    """SQLite-based search across ALL Revit versions (2022-2027)."""
    db = await _get_db()
    try:
        like = f"%{query}%"
        sql = """
            SELECT a.href, a.title, a.short_title, a.entry_type, a.namespace, a.description,
                   GROUP_CONCAT(v.version, ', ') as versions
            FROM api_entries a
            JOIN api_entry_versions v ON v.href = a.href
            WHERE (a.title LIKE ? OR a.short_title LIKE ?)
            GROUP BY a.href
            ORDER BY a.entry_type, a.title
            LIMIT ?
        """
        cursor = await db.execute(sql, (like, like, limit))
        rows = await cursor.fetchall()
        await cursor.close()

        formatted = []
        for r in rows:
            formatted.append({
                "title": r["title"],
                "type": r["entry_type"] or "",
                "namespace": r["namespace"] or "",
                "description": (r["description"] or "")[:300],
                "versions": r["versions"] or "",
                "url": r["href"],
            })

        return formatted
    except Exception as e:
        _logger.error("SQL rvtdocs search failed: %s", e)
        return []
    finally:
        await db.close()


async def search_rvtdocs_endpoint(req: SearchRequest):
    ck = cache_key(req)
    cached = cache_get(ck)
    if cached:
        return cached
    try:
        formatted = await _search_rvtdocs(req.query, req.limit)
        result = {"query": req.query, "count": len(formatted), "results": formatted}
        cache_set(ck, result)
        return result
    except Exception as e:
        _logger.error("rvtdocs search failed: %s", e)
        raise HTTPException(500, str(e))


async def build_context(req: SearchRequest, api_key: Optional[str] = None) -> tuple[dict, dict, str]:
    qdrant_data = await search_qdrant(req, api_key=api_key)
    qdrant_results = qdrant_data if isinstance(qdrant_data, dict) else qdrant_data

    rvtdocs_results_list = await _search_rvtdocs(req.query, req.limit)
    rvtdocs_results = {"results": rvtdocs_results_list, "count": len(rvtdocs_results_list)}

    context_parts: list[str] = []
    if qdrant_results.get("results"):
        context_parts.append("## Qdrant Results")
        for r in qdrant_results["results"]:
            coll = r.get("collection", "")
            versions = r.get("versions", [])
            versions_str = f" [versions: {', '.join(versions)}]" if versions else ""
            context_parts.append(f"- [{coll}]{versions_str} {r.get('name', '')} (score: {r.get('score', '')}): {r.get('summary', '')[:300]}")
    if rvtdocs_results.get("results"):
        context_parts.append("\n## rvtdocs Results (from local SQLite DB)")
        for r in rvtdocs_results["results"]:
            context_parts.append(f"- {r.get('title', '')} ({r.get('type', '')}) [versions: {r.get('versions', '')}]: {r.get('description', '')[:300]}")
        context_parts.append("\nNote: Results cover ALL Revit versions (2022-2027). Each result shows which versions it is available in.")

    context = "\n".join(context_parts) if context_parts else "No results found."
    return qdrant_results, rvtdocs_results, context
