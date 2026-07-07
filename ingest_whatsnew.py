#!/usr/bin/env python3
"""
Ingest Revit API "What's New" markdown files into a Qdrant collection.

Reads markdown files from D:\DEV\LLM\revit-api-whatsnew, splits into
subsection chunks, generates embeddings via RouterAI / Ollama (same
config as mcp_server.py), and upserts into the `revit_api_whatsnew`
Qdrant collection.

Usage:
    python ingest_whatsnew.py [--whatsnew-dir PATH] [--recreate]

Environment variables (from .env):
    ROUTERAI_API_KEY, ROUTERAI_BASE_URL, EMBEDDING_MODEL
    QDRANT_URL, LLM_PROVIDER, OLLAMA_BASE_URL
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    CollectionInfo,
    Distance,
    PointStruct,
    VectorParams,
)

load_dotenv(Path(__file__).parent / ".env")

COLLECTION_NAME = "revit_api_whatsnew"
VECTOR_SIZE = 1024  # bge-m3
DEFAULT_WHATSNEW_DIR = Path(r"D:\DEV\LLM\revit-api-whatsnew")

_http: Optional[httpx.AsyncClient] = None
_qdrant: Optional[AsyncQdrantClient] = None
_logger = logging.getLogger("ingest_whatsnew")

# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=60)
    return _http


def _get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        from urllib.parse import urlparse
        parsed = urlparse(url)
        _qdrant = AsyncQdrantClient(host=parsed.hostname, port=parsed.port, prefer_grpc=False, https=False)
    return _qdrant


def _llm_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "routerai")


# ── Embedding ────────────────────────────────────────────────────────────────


async def _routerai_embedding(text: str) -> list[float]:
    client = _get_http()
    url = os.environ.get("ROUTERAI_BASE_URL", "https://routerai.ru/api/v1")
    model = os.environ.get("EMBEDDING_MODEL", "baai/bge-m3")
    api_key = os.environ.get("ROUTERAI_API_KEY", "")
    url = f"{url.rstrip('/')}/embeddings"
    resp = await client.post(
        url,
        json={"model": model, "input": text},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


async def _ollama_embedding(text: str) -> list[float]:
    client = _get_http()
    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
    resp = await client.post(
        f"{base.rstrip('/')}/api/embed",
        json={"model": model, "input": text},
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


async def _get_embedding(text: str) -> list[float]:
    if _llm_provider() == "ollama":
        return await _ollama_embedding(text)
    return await _routerai_embedding(text)


# ── Markdown parsing ─────────────────────────────────────────────────────────

SECTION_KEYWORDS = {
    "api changes",
    "изменения api",
    "obsolete api removal",
    "удаление устаревшего api",
    "api additions",
    "new features",
    "новые возможности",
}


def _parse_section_heading(line: str) -> str | None:
    m = re.match(r"^##\s+(.+)$", line.strip())
    if m:
        return m.group(1).strip()
    return None


def _parse_subsection_heading(line: str) -> str | None:
    m = re.match(r"^###\s+(.+)$", line.strip())
    if m:
        return m.group(1).strip()
    return None


def _classify_section(heading: str) -> str:
    hl = heading.lower()
    if any(k in hl for k in ("api changes", "изменения api")):
        return "API Changes"
    if any(k in hl for k in ("obsolete", "удаление")):
        return "Obsolete API Removal"
    if any(k in hl for k in ("api additions", "new feature", "новые возможности")):
        return "API Additions"
    return f"Section: {heading}"


def _chunk_markdown(text: str, version: str) -> list[dict[str, str]]:
    lines = text.split("\n")
    chunks: list[dict[str, str]] = []

    current_section: str | None = None
    current_subsection: str | None = None
    current_lines: list[str] = []
    collecting = False

    def _flush():
        nonlocal collecting, current_lines
        if not collecting or not current_lines:
            return
        content = "\n".join(current_lines).strip()
        if not content:
            return
        first_line = content.split("\n")[0][:120]
        chunks.append({
            "version": version,
            "section": _classify_section(current_section) if current_section else "General",
            "subsection": current_subsection or first_line,
            "content": content,
            "summary": f"Revit {version} — {_classify_section(current_section) if current_section else 'General'}: {current_subsection or first_line}",
        })

    for line in lines:
        section_h = _parse_section_heading(line)
        if section_h:
            _flush()
            current_section = section_h
            current_subsection = None
            current_lines = []
            collecting = True
            continue

        sub_h = _parse_subsection_heading(line)
        if sub_h:
            _flush()
            current_subsection = sub_h
            current_lines = [line]
            collecting = True
            continue

        if collecting:
            current_lines.append(line)

    _flush()
    return chunks


# ── Qdrant operations ────────────────────────────────────────────────────────


async def _ensure_collection():
    client = _get_qdrant()
    try:
        info = await client.get_collection(collection_name=COLLECTION_NAME)
        _logger.info("Collection '%s' exists: %d points", COLLECTION_NAME, info.points_count)
    except Exception:
        _logger.info("Creating collection '%s' (vectors: %d, distance: Cosine)...", COLLECTION_NAME, VECTOR_SIZE)
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        _logger.info("Collection created.")


async def _recreate_collection():
    client = _get_qdrant()
    try:
        await client.delete_collection(collection_name=COLLECTION_NAME)
        _logger.info("Deleted existing collection '%s'", COLLECTION_NAME)
    except Exception:
        pass
    _logger.info("Creating collection '%s' (vectors: %d, distance: Cosine)...", COLLECTION_NAME, VECTOR_SIZE)
    await client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    _logger.info("Collection created.")


# ── Main ─────────────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Revit API What's New data into Qdrant")
    parser.add_argument(
        "--whatsnew-dir",
        type=Path,
        default=DEFAULT_WHATSNEW_DIR,
        help=f"Path to whatsnew markdown files (default: {DEFAULT_WHATSNEW_DIR})",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate the collection before ingesting",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Qdrant upsert batch size (default: 50)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING"],
        default="INFO",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s | %(message)s",
    )

    if _llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        _logger.error("ROUTERAI_API_KEY not set and LLM_PROVIDER != ollama")
        sys.exit(1)

    whatsnew_dir: Path = args.whatsnew_dir
    if not whatsnew_dir.is_dir():
        _logger.error("Directory not found: %s", whatsnew_dir)
        sys.exit(1)

    md_files = sorted(whatsnew_dir.glob("revit-api-*-whatsnew.md"))
    if not md_files:
        _logger.error("No revit-api-*-whatsnew.md files found in %s", whatsnew_dir)
        sys.exit(1)

    _logger.info("Found %d whatsnew files", len(md_files))

    # Parse all chunks
    all_chunks: list[dict[str, str]] = []
    for fp in md_files:
        m = re.search(r"(\d{4})", fp.stem)
        version = m.group(1) if m else "unknown"
        text = fp.read_text(encoding="utf-8")
        chunks = _chunk_markdown(text, version)
        _logger.info("  %s → %d chunks (Revit %s)", fp.name, len(chunks), version)
        all_chunks.extend(chunks)

    _logger.info("Total chunks: %d", len(all_chunks))

    # Setup Qdrant collection
    if args.recreate:
        await _recreate_collection()
    else:
        await _ensure_collection()

    # Generate embeddings and upsert in batches
    batch_size = args.batch_size
    total = len(all_chunks)
    upserted = 0

    for i in range(0, total, batch_size):
        batch = all_chunks[i : i + batch_size]
        _logger.info("Processing batch %d/%d (%d chunks)...", i // batch_size + 1, (total - 1) // batch_size + 1, len(batch))

        points: list[PointStruct] = []
        for idx, chunk in enumerate(batch):
            text_for_embedding = f"{chunk['section']}: {chunk['subsection']}\n\n{chunk['content']}"
            try:
                vector = await _get_embedding(text_for_embedding)
            except Exception as e:
                _logger.warning("  Embedding failed for chunk %d (Revit %s, %s): %s", i + idx, chunk["version"], chunk["subsection"][:60], e)
                continue

            points.append(PointStruct(
                id=i + idx + 1,
                vector=vector,
                payload={
                    "version": chunk["version"],
                    "section": chunk["section"],
                    "subsection": chunk["subsection"],
                    "content": chunk["content"],
                    "summary": chunk["summary"],
                    "source": "revit-api-whatsnew",
                },
            ))

        if points:
            client = _get_qdrant()
            await client.upsert(
                collection_name=COLLECTION_NAME,
                points=points,
            )
            upserted += len(points)
            _logger.info("  Upserted %d points (total: %d)", len(points), upserted)

    _logger.info("Done! Upserted %d points into '%s'", upserted, COLLECTION_NAME)

    # Show collection info
    info = await _get_qdrant().get_collection(collection_name=COLLECTION_NAME)
    _logger.info("Collection '%s': %d points, %d indexed vectors",
                 COLLECTION_NAME, info.points_count, info.indexed_vectors_count)

    # Cleanup
    if _qdrant:
        await _qdrant.close()
    if _http:
        await _http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
