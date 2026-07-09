#!/usr/bin/env python3
"""
Ingest Revit API documentation from revit_api.db (api_content + api_entries + api_entry_versions)
into Qdrant collections — both local (embedded qdrant_data/) and remote Qdrant server.

Usage:
    python ingest_api_content.py [--collection COLLECTION] [--recreate] [--batch-size N]
                                  [--local-only] [--remote-only]

Environment variables (from .env):
    QDRANT_URL — remote Qdrant server URL (e.g. http://host:6333)
    LLM_PROVIDER, ROUTERAI_API_KEY, EMBEDDING_MODEL, OLLAMA_BASE_URL — for embeddings
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

import aiosqlite
import httpx
from dotenv import load_dotenv
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

load_dotenv(Path(__file__).parent / ".env")

COLLECTION_NAME = "revit_api_knowledge"
VECTOR_SIZE = 1024

_http: Optional[httpx.AsyncClient] = None
_logger = logging.getLogger("ingest_api_content")

_BASE_DIR = Path(__file__).resolve().parent
_DB_PATH = _BASE_DIR / "revit_api.db"
_LOCAL_QDRANT_DIR = _BASE_DIR / "qdrant_data"


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=300)
    return _http


async def _close_http():
    global _http
    if _http:
        await _http.aclose()
        _http = None


def _create_qdrant_client(location: Optional[str] = None, url: Optional[str] = None) -> AsyncQdrantClient:
    if url:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return AsyncQdrantClient(host=parsed.hostname, port=parsed.port, prefer_grpc=False, https=parsed.scheme == "https")
    return AsyncQdrantClient(path=location)


def _llm_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "routerai")


async def _routerai_embedding(texts: list[str]) -> list[list[float]]:
    client = _get_http()
    url = os.environ.get("ROUTERAI_BASE_URL", "https://routerai.ru/api/v1")
    model = os.environ.get("EMBEDDING_MODEL", "baai/bge-m3")
    api_key = os.environ.get("ROUTERAI_API_KEY", "")
    url = f"{url.rstrip('/')}/embeddings"
    resp = await client.post(
        url,
        json={"model": model, "input": texts},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [item["embedding"] for item in data]


async def _ollama_embedding(texts: list[str]) -> list[list[float]]:
    client = _get_http()
    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("EMBEDDING_MODEL", "bge-m3")
    resp = await client.post(
        f"{base.rstrip('/')}/api/embed",
        json={"model": model, "input": texts, "keep_alive": "5m"},
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


async def _get_embeddings(texts: list[str]) -> list[list[float]]:
    if _llm_provider() == "ollama":
        return await _ollama_embedding(texts)
    return await _routerai_embedding(texts)


def _extract_syntax(content_md: str) -> str:
    m = re.search(r"```[\w]*\n(.*?)```", content_md, re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_params(content_md: str) -> str:
    lines = content_md.split("\n")
    in_params = False
    params_lines: list[str] = []
    for line in lines:
        if re.search(r"(?i)^##?\s*(parameters|params|properties)", line):
            in_params = True
            continue
        if in_params:
            if re.search(r"^##?\s+", line) and not re.search(r"(?i)(parameters|params|properties)", line):
                break
            params_lines.append(line)
    return "\n".join(params_lines).strip() if params_lines else ""


async def fetch_data(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        _logger.error("Database not found: %s", db_path)
        sys.exit(1)

    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    try:
        sql = """
            SELECT
                a.href,
                a.title,
                a.short_title,
                a.namespace,
                a.entry_type,
                a.tag,
                a.member_of,
                a.description,
                c.content_md,
                c.fetched_at
            FROM api_content c
            JOIN api_entries a ON a.href = c.href
            WHERE c.content_md IS NOT NULL AND c.content_md != ''
              AND (c.fetch_error IS NULL OR c.fetch_error = '')
            ORDER BY a.entry_type, a.title
        """
        cursor = await db.execute(sql)
        rows = await cursor.fetchall()
        await cursor.close()

        entries = []
        for r in rows:
            href = r["href"]

            ver_cursor = await db.execute(
                "SELECT version, status FROM api_entry_versions WHERE href = ? ORDER BY version",
                (href,),
            )
            versions = []
            for vr in await ver_cursor.fetchall():
                versions.append({"version": vr["version"], "status": vr["status"]})
            await ver_cursor.close()

            entries.append({
                "href": href,
                "title": r["title"] or "",
                "short_title": r["short_title"] or "",
                "namespace": r["namespace"] or "",
                "entry_type": r["entry_type"] or "",
                "tag": r["tag"] or "",
                "member_of": r["member_of"] or "",
                "description": r["description"] or "",
                "content_md": r["content_md"] or "",
                "fetched_at": r["fetched_at"] or "",
                "versions": [v["version"] for v in versions if v["status"] == "exists"],
            })

        _logger.info("Loaded %d entries from %s", len(entries), db_path.name)
        return entries
    finally:
        await db.close()


async def _ensure_collection(client: AsyncQdrantClient, name: str, label: str):
    try:
        info = await client.get_collection(collection_name=name)
        _logger.info("[%s] Collection '%s' exists: %d points", label, name, info.points_count)
    except Exception:
        _logger.info("[%s] Creating collection '%s' (vectors: %d, distance: Cosine)...", label, name, VECTOR_SIZE)
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        _logger.info("[%s] Collection created.", label)


async def _recreate_collection(client: AsyncQdrantClient, name: str, label: str):
    try:
        await client.delete_collection(collection_name=name)
        _logger.info("[%s] Deleted existing collection '%s'", label, name)
    except Exception:
        pass
    _logger.info("[%s] Creating collection '%s' (vectors: %d, distance: Cosine)...", label, name, VECTOR_SIZE)
    await client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    _logger.info("[%s] Collection created.", label)


async def ingest_to_client(
    client: AsyncQdrantClient,
    entries: list[dict[str, Any]],
    collection: str,
    label: str,
    batch_size: int,
    recreate: bool,
):
    if recreate:
        await _recreate_collection(client, collection, label)
    else:
        await _ensure_collection(client, collection, label)

    total = len(entries)
    upserted = 0
    skipped = 0

    for i in range(0, total, batch_size):
        batch = entries[i : i + batch_size]
        _logger.info(
            "[%s] Processing batch %d/%d (%d entries)...",
            label, i // batch_size + 1, (total - 1) // batch_size + 1, len(batch),
        )

        texts = []
        valid_indices = []
        for idx, entry in enumerate(batch):
            text = (
                f"{entry['namespace']} {entry['title']}: "
                f"{entry['description'] or entry['short_title']}\n\n"
                f"{entry['content_md'][:3000]}"
            )
            texts.append(text)
            valid_indices.append(idx)

        if not texts:
            continue

        try:
            vectors = await _get_embeddings(texts)
        except Exception as e:
            _logger.warning("  [%s] Batch embedding failed: %s", label, e)
            skipped += len(texts)
            continue

        points = []
        for idx_in_batch, vector in zip(valid_indices, vectors):
            entry = batch[idx_in_batch]
            points.append(PointStruct(
                id=abs(hash(entry["href"]) % (2**63)),
                vector=vector,
                payload={
                    "name": entry["title"],
                    "summary": (entry["description"] or entry["short_title"] or "")[:2000],
                    "syntax": _extract_syntax(entry["content_md"])[:2000],
                    "params": _extract_params(entry["content_md"])[:2000],
                    "content_md": entry["content_md"],
                    "versions": entry["versions"],
                    "db_id": entry["href"],
                    "entry_type": entry["entry_type"],
                    "namespace": entry["namespace"],
                    "tag": entry["tag"],
                    "member_of": entry["member_of"],
                },
            ))

        if points:
            try:
                await client.upsert(collection_name=collection, points=points)
                upserted += len(points)
                _logger.info("  [%s] Upserted %d points (total: %d)", label, len(points), upserted)
            except Exception as e:
                _logger.error("  [%s] Upsert batch failed: %s", label, e)

    _logger.info("[%s] Done! Upserted %d / %d entries, skipped %d", label, upserted, total, skipped)

    try:
        info = await client.get_collection(collection_name=collection)
        _logger.info("[%s] Collection '%s': %d points, %d indexed vectors",
                     label, collection, info.points_count, info.indexed_vectors_count)
    except Exception:
        pass


async def main():
    parser = argparse.ArgumentParser(description="Ingest Revit API documentation from revit_api.db into Qdrant")
    parser.add_argument("--collection", type=str, default=COLLECTION_NAME,
                        help=f"Qdrant collection name (default: {COLLECTION_NAME})")
    parser.add_argument("--recreate", action="store_true",
                        help="Drop and recreate the collection before ingesting")
    parser.add_argument("--batch-size", type=int, default=50,
                        help="Batch size for embedding + Qdrant upsert (default: 50)")
    parser.add_argument("--local-only", action="store_true",
                        help="Only ingest into local Qdrant (embedded qdrant_data/)")
    parser.add_argument("--remote-only", action="store_true",
                        help="Only ingest into remote Qdrant server")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING"], default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if _llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        _logger.error("ROUTERAI_API_KEY not set and LLM_PROVIDER != ollama")
        sys.exit(1)

    entries = await fetch_data(_DB_PATH)
    if not entries:
        _logger.warning("No entries found in api_content table")
        return

    targets: list[tuple[str, str, Optional[str]]] = []

    if not args.remote_only:
        targets.append(("local", str(_LOCAL_QDRANT_DIR), None))

    if not args.local_only:
        remote_url = os.environ.get("QDRANT_URL", "")
        if remote_url:
            targets.append(("remote", remote_url, remote_url))
        else:
            _logger.warning("QDRANT_URL not set in .env, skipping remote Qdrant")

    if not targets:
        _logger.error("No Qdrant targets configured (use --local-only, --remote-only, or set QDRANT_URL)")
        sys.exit(1)

    clients: list[tuple[str, AsyncQdrantClient]] = []
    for label, location, url in targets:
        try:
            if url:
                client = _create_qdrant_client(url=url)
            else:
                client = _create_qdrant_client(location=location)
            clients.append((label, client))
            _logger.info("Connected to %s Qdrant: %s", label, url or location)
        except Exception as e:
            _logger.error("Failed to connect to %s Qdrant: %s", label, e)

    if not clients:
        _logger.error("No Qdrant clients available")
        sys.exit(1)

    for label, client in clients:
        try:
            await ingest_to_client(
                client=client,
                entries=entries,
                collection=args.collection,
                label=label,
                batch_size=args.batch_size,
                recreate=args.recreate,
            )
        except Exception as e:
            _logger.error("[%s] Ingestion failed: %s", label, e, exc_info=True)
        finally:
            await client.close()

    await _close_http()
    _logger.info("All done.")


if __name__ == "__main__":
    asyncio.run(main())
