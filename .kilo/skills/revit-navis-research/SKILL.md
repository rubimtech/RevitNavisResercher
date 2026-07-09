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
- **revit_api.db (SQLite)** — local cached API documentation with version filtering, cross-version diffs, and full markdown content (replaces direct rvtdocs.com/revitapidocs.com calls)
- **LLM analysis** (deepseek-v4-flash or local Ollama) — synthesizes results

> **Note:** rvtdocs.com and revitapidocs.com are no longer called directly. All API search and page content is served from the local `revit_api.db` (tables: `api_entries`, `api_content`, `api_entry_versions`, `api_diffs`).

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

### `rvtdocs_search` — Search API entries in local DB (previously rvtdocs.com)

```python
rvtdocs_search(query="Wall.Create", version="2024", limit=10)
```

Powered by local `revit_api.db` (api_entries + api_entry_versions). Returns title, type, namespace, description.

### `rvtdocs_get_page` — Full API page content from local DB cache

```python
rvtdocs_get_page(url="<href>")  # href from rvtdocs_search results
```

Returns cached markdown content from `api_content` table (23K+ cached pages).

### `rvtdocs_cross_version_search` — Check API lifecycle via local DB

```python
rvtdocs_cross_version_search(
    query="ElementId.Value",
    versions=["2021","2022","2023","2024","2025","2026","2027"]
)
```

Powered by `api_entry_versions` table — detects which versions have the API. No rvtdocs.com calls.

### `sql_search_api` — Search API entries in SQLite

```python
sql_search_api(query="Curve", entry_type="class", limit=10)
```

### `sql_get_api` — Full API entry details + versions + diffs

```python
sql_get_api(href="d4648875-d41a-783b-d5f4-638df39ee413.htm")
```

### `sql_get_api_content` — Get cached markdown from api_content

```python
sql_get_api_content(href="f35ba9fc-0b6b-4284-60eb-91788761127c.htm")
```

### `sql_search_api_content` — Search + return content in one call

```python
sql_search_api_content(query="ApplicationInitialized", version="2024", limit=3)
```

### `sql_get_page_url` — Get API page content from local DB (replaces revitapidocs.com)

```python
sql_get_page_url(href="f35ba9fc-0b6b-4284-60eb-91788761127c.htm", version="2026")
```

### `sql_search_diffs` — Find APIs added/removed between versions

```python
sql_search_diffs(version_from="2026", version_to="2025", diff_type="added")
```

### `sql_get_api_hierarchy` — Hierarchy path (namespace → class → member)

```python
sql_get_api_hierarchy(href="d4648875-d41a-783b-d5f4-638df39ee413.htm", version="2026")
```

### `analyze` — LLM analysis of search results

```python
analyze(query="user question", context="search results JSON", instructions="")
```

### `analyze_build_errors` — Build errors → fix recipes (VersionCompat)

```python
analyze_build_errors(
    report_content="...",       # the build-errors-report.md text
    report_path="",             # OR path to the .md file
    research_apis=True          # research failing APIs via Qdrant/rvtdocs
)
```

Takes a Revit multi-version build errors report, parses all CS errors, researches failing APIs lifecycle, and generates a structured fix plan with C# code for VersionCompat wrappers.

**Example usage from Kilo:**

```python
@revit-navis-research analyze_build_errors(
    report_path="D:\\DEV\\ReviBE\\build-reports\\logs\\20260708-084556\\build-errors-report.md"
)
```

Output: JSON with `report_analyzed` (parsed errors summary), `apis_researched` count, and `fix_plan` (markdown with code snippets grouped by file).

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
