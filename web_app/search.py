import json
from typing import Optional

from fastapi import HTTPException

from .cache import cache_get, cache_key, cache_set
from .clients import get_http, get_qdrant
from .config import get_cfg
from .embeddings import get_embedding
from .models import SearchRequest


def _truncate(text: str, limit: int = 600) -> str:
    return text[:limit] + "..." if len(text) > limit else text


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
        import logging
        logging.getLogger("revitnavis-web").error("qdrant search failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


async def _search_rvtdocs(query: str, version: str, limit: int) -> list[dict]:
    client = get_http()
    try:
        r = await client.post(
            "https://rvtdocs.com/search/api/search",
            json={"query": query, "current_version": version, "include_description": True},
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("current_version_results", [])
    except Exception:
        results = []

    if not results:
        fallback_versions = ["2025", "2023", "2022"]
        for v in fallback_versions:
            if v == version:
                continue
            try:
                r = await client.post(
                    "https://rvtdocs.com/search/api/search",
                    json={"query": query, "current_version": v, "include_description": True},
                )
                r.raise_for_status()
                data = r.json()
                results = data.get("current_version_results", [])
                if results:
                    version = v
                    break
            except Exception:
                continue

    formatted = []
    for item in results[:limit]:
        formatted.append({
            "title": item.get("title", ""),
            "type": item.get("type", ""),
            "namespace": item.get("namespace", ""),
            "description": item.get("description", ""),
            "version": item.get("year_version", ""),
            "url": f"https://rvtdocs.com{item.get('url', '')}",
        })
    return formatted


async def search_rvtdocs_endpoint(req: SearchRequest):
    ck = cache_key(req)
    cached = cache_get(ck)
    if cached:
        return cached
    try:
        formatted = await _search_rvtdocs(req.query, req.revit_version, req.limit)
        result = {"query": req.query, "version": req.revit_version, "count": len(formatted), "results": formatted}
        cache_set(ck, result)
        return result
    except Exception as e:
        import logging
        logging.getLogger("revitnavis-web").error("rvtdocs search failed: %s", e)
        raise HTTPException(500, str(e))


async def build_context(req: SearchRequest, api_key: Optional[str] = None) -> tuple[dict, dict, str]:
    qdrant_data = await search_qdrant(req, api_key=api_key)
    qdrant_results = qdrant_data if isinstance(qdrant_data, dict) else qdrant_data

    rvtdocs_results_list = await _search_rvtdocs(req.query, req.revit_version, req.limit)
    rvtdocs_results = {"results": rvtdocs_results_list, "count": len(rvtdocs_results_list)}

    context_parts: list[str] = []
    if qdrant_results.get("results"):
        context_parts.append("## Qdrant Results")
        for r in qdrant_results["results"]:
            coll = r.get("collection", "")
            context_parts.append(f"- [{coll}] {r.get('name', '')} (score: {r.get('score', '')}): {r.get('summary', '')[:300]}")
    if rvtdocs_results.get("results"):
        context_parts.append("\n## rvtdocs Results")
        for r in rvtdocs_results["results"]:
            context_parts.append(f"- {r.get('title', '')} ({r.get('type', '')}): {r.get('description', '')[:300]}")

    context = "\n".join(context_parts) if context_parts else "No results found."
    return qdrant_results, rvtdocs_results, context
