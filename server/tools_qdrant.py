"""
Qdrant search tools for the MCP server.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import aiosqlite
from qdrant_client.models import Filter as QdrantFilter, FieldCondition, MatchValue

from server.config import get_cfg
from server.llm import get_embedding
from server.mcp_instance import mcp
from server.state import get_qdrant
from server.utils import (
    format_error,
    truncate,
    truncate_response,
)

_logger = logging.getLogger("revitnavis")


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
    version: Optional[str] = None,
) -> str:
    """Search a Qdrant collection using semantic search via RouterAI embeddings."""
    try:
        client = get_qdrant()
        vector = await get_embedding(query)
        qdrant_filter = None
        if version:
            qdrant_filter = QdrantFilter(
                must=[FieldCondition(key="versions", match=MatchValue(value=version))]
            )
        results = await client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=qdrant_filter,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        trunc_payload = get_cfg("output", "truncate_payload", default=400)
        trunc_syntax = get_cfg("output", "truncate_syntax", default=200)
        include_full_code = (
            include_full_code
            if include_full_code is not None
            else get_cfg("qdrant", "include_full_code", default=False)
        )

        _db: Optional[aiosqlite.Connection] = None
        if include_full_code:
            _db_path = Path(__file__).resolve().parent.parent / "revit_codebase.db"
            _db = await aiosqlite.connect(str(_db_path))

        formatted = []
        for point in results.points:
            payload = point.payload or {}
            entry = {
                "id": str(point.id),
                "score": round(point.score, 4),
                "payload": {
                    "name": payload.get("name", ""),
                    "summary": truncate(payload.get("summary", ""), trunc_payload),
                    "syntax": truncate(payload.get("syntax", ""), trunc_syntax),
                    "params": truncate(payload.get("params", ""), trunc_syntax),
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
        return truncate_response(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("qdrant_search failed: %s", e, exc_info=True)
        return format_error(f"Search failed: {e}")


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
        client = get_qdrant()
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
        return format_error(f"Failed: {e}")


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
        client = get_qdrant()
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
        return format_error(f"Failed: {e}")


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
        client = get_qdrant()
        points = await client.retrieve(
            collection_name=collection,
            ids=[point_id],
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return format_error(f"Point {point_id} not found")
        pt = points[0]
        return json.dumps({"id": pt.id, "payload": pt.payload}, indent=2, ensure_ascii=False)
    except Exception as e:
        _logger.error("qdrant_get_point failed: %s", e)
        return format_error(f"Failed: {e}")
