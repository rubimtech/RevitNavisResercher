---
name: revit-navis-research
description: >-
  Use the RevitNavisResearcher MCP server to search Revit API documentation,
  Revit SDK samples, Navisworks API, and Revit API What's New changelogs.
  Combines vector search (Qdrant), live rvtdocs.com API, and LLM analysis
  for comprehensive Revit & Navisworks API research.
---

# Revit & Navisworks API Research Skill

## Overview

This MCP server provides tools for researching **Revit API**, **Revit SDK Samples**, **Navisworks API**, and **Revit API What's New changelogs** (2022–2026). It combines:

- **Qdrant vector search** — semantic search over pre-ingested API docs, SDK code, and changelogs
- **rvtdocs.com** — live search and page retrieval (versions 2021–2027)
- **revitapidocs.com** — alternative autocomplete search
- **LLM analysis** (deepseek-v4-flash or local Ollama) — synthesizes results

## Collections

| Collection | Description | Use Case |
|---|---|---|
| `revit_api_knowledge` | Revit API classes, methods, properties | General Revit API questions |
| `Revit_SDK_Samples` | Revit SDK sample code | Code examples, patterns |
| `navisworks_api_bge` | Navisworks API docs | Navisworks automation |
| `revit_api_whatsnew` | What's New changelogs 2022–2026 | Breaking changes, deprecations, new features |

## Available Tools

### `research` — Full pipeline (recommended for most queries)

```python
research(query="create wall with parameters", revit_version="2024")
```

Automatically searches:
1. `revit_api_knowledge` (Qdrant, 5 results)
2. `revit_api_whatsnew` (Qdrant, 3 results)
3. `rvtdocs.com` for the target version (8 results)
4. Cross-version rvtdocs search (2021–2027, 3 results per version)
5. Sends everything to LLM for synthesis

### `qdrant_search` — Raw semantic search

```python
qdrant_search(
    query="FilteredElementCollector bounding box",
    collection="revit_api_knowledge",  # any collection name
    limit=10,
    score_threshold=0.5,       # optional, filters low-relevance results
    include_full_code=False    # True to pull SDK source from SQLite
)
```

### `rvtdocs_search` — Search rvtdocs.com by name

```python
rvtdocs_search(query="Wall.Create", version="2024", limit=10)
```

### `rvtdocs_get_page` — Full API page with syntax & remarks

```python
rvtdocs_get_page(url="/2024/<guid>")
```

### `rvtdocs_cross_version_search` — Check API lifecycle

```python
rvtdocs_cross_version_search(
    query="ElementId.Value",
    versions=["2021","2022","2023","2024","2025","2026","2027"]
)
```

Detects when an API was introduced, changed, or removed.

### `analyze` — LLM analysis of search results

```python
analyze(query="user question", context="search results JSON", instructions="")
```

## Strategy

1. **Start with `research()`** — covers all sources in one call
2. If results are sparse, drill down with `qdrant_search()` on specific collections
3. For exact class/method docs, use `rvtdocs_search()` + `rvtdocs_get_page()`
4. To check API version lifecycle, use `rvtdocs_cross_version_search()`
5. Use `analyze()` to synthesize raw results into a coherent answer

## Version Awareness

Always specify `revit_version` when known. The server supports 2021–2027. Key changes:

- **2022**: ForgeTypeId migration (ParameterTypeId, SpecTypeId, DisciplineTypeId)
- **2024**: ElementId 64-bit (`.Value` deprecated), Toposurface → Toposolid
- **2025**: .NET 8 migration (net8.0-windows), CefSharp upgrade
- **2026**: Classification/Assembly codes renamed, Curve intersection API overhaul
- **2027**: (check rvtdocs.com for latest)

## What's New Collection Details

The `revit_api_whatsnew` collection contains changelogs for Revit 2022–2026. Each point has:

| Payload Field | Description |
|---|---|
| `version` | Revit version (2022–2026) |
| `section` | API Changes / Obsolete API Removal / API Additions |
| `subsection` | Specific change name (e.g. "CefSharp Removed") |
| `content` | Full markdown with tables, code, descriptions |
| `summary` | One-line summary |

Use this collection via `qdrant_search(collection="revit_api_whatsnew", ...)` or let `research()` include it automatically.

## Troubleshooting

- **Qdrant scores < 0.5** are usually irrelevant
- **LLM analysis fails**: check `ROUTERAI_API_KEY` is set, or use `LLM_PROVIDER=ollama`
- **No results in whatsnew collection**: ensure ingestion was run (`python ingest_whatsnew.py`)
- **Response truncated**: refine query to narrow scope (limit is ~25K characters)
