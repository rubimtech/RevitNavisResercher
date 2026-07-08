"""
LLM-based analysis tools and the combined research pipeline.
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from server.config import get_cfg
from server.llm import llm_chat, llm_provider
from server.mcp_instance import mcp
from server.utils import format_error, truncate_response

# Import sibling tools for the research pipeline
from server.tools_qdrant import qdrant_search
from server.tools_rvtdocs import rvtdocs_search, rvtdocs_cross_version_search

_logger = logging.getLogger("revitnavis")


@mcp.tool(
    name="analyze",
    annotations={
        "title": "Analyze search results with LLM",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def analyze_results(query: str, context: str, instructions: str = "") -> str:
    """Use RouterAI LLM to analyze Qdrant/rvtdocs search results."""
    if llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        return format_error("ROUTERAI_API_KEY not set (or set LLM_PROVIDER=ollama)")
    try:
        system = get_cfg("prompts", "analyze", default="") + " " + instructions
        result = await llm_chat(
            [
                {
                    "role": "user",
                    "content": f"## Research Question\n{query}\n\n## Context\n{context}",
                }
            ],
            system=system,
        )
        return truncate_response(result)
    except Exception as e:
        _logger.error("analyze failed: %s", e)
        return format_error(f"LLM analysis failed: {e}")


# ─── Build Error Analysis ──────────────────────────────────────────────────

_BUILD_ERROR_PATTERNS = {
    "CS0246": {
        "title": "Type not found",
        "fix": "Type doesn't exist in this version → use `#if !REVIT{prev}_OR_NEWER` guard or reflection via `Assembly.GetType()`",
    },
    "CS0122": {
        "title": "Inaccessible (internal)",
        "fix": "Type is `internal` in this version → use reflection via `typeof(Document).Assembly.GetType(\"full.namespace.TypeName\")` + `dynamic` return",
    },
    "CS1061": {
        "title": "Missing member",
        "fix": "Method/property doesn't exist → guard with `#if REVIT{year}_OR_NEWER` for new API, `#if !REVIT{year}_OR_NEWER` for removed API",
    },
    "CS0117": {
        "title": "Missing enum value",
        "fix": "Enum member removed/renamed → use numeric cast `(EnumType)N` in wrapper property",
    },
    "CS1503": {
        "title": "Wrong argument type",
        "fix": ".NET Framework vs modern .NET API diff → `#if NET48` / `#else` for different overloads",
    },
    "CS0019": {
        "title": "Operator not applicable",
        "fix": "Return type changed between versions → create wrapper normalizing to old return type",
    },
    "CS1615": {
        "title": "out keyword mismatch",
        "fix": "Method signature changed: `out` parameter removed → wrapper handling new return type",
    },
}


@mcp.tool(
    name="analyze_build_errors",
    annotations={
        "title": "Analyze build errors report → fix recipes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def analyze_build_errors(
    report_content: str = "",
    report_path: str = "",
    research_apis: bool = True,
) -> str:
    """Analyze a Revit build errors report and generate fix recipes for VersionCompat."""
    try:
        if report_path and not report_content:
            path = Path(report_path)
            if not path.exists():
                return format_error(f"Report file not found: {report_path}")
            report_content = path.read_text(encoding="utf-8")
        elif not report_content:
            return format_error("Either report_content or report_path is required")

        # Step 2: Parse errors with LLM
        system = (
            "You are a Revit API VersionCompat expert. "
            "Analyze the given build errors report for a multi-version Revit plugin (R22-R27). "
            "Extract ALL unique errors and classify them.\n\n"
            "Return a JSON array of objects with fields:\n"
            "- version: Revit version (R22, R23, etc.)\n"
            "- code: CS error code (CS0246, CS1061, etc.)\n"
            "- file: filename only (e.g., AnalyticalCompat.cs)\n"
            "- line: line number (int)\n"
            "- symbol: the API that's failing\n"
            "- description: one-line explanation\n"
            "- category: one of: missing_type | internal_type | missing_member | missing_enum | "
            "wrong_overload | operator_change | return_type_change\n\n"
            "IMPORTANT: Deduplicate — if the same error appears for multiple files or versions, "
            "list each version separately but combine into one entry per unique (symbol, file, line) combo. "
            "Output ONLY the JSON array, no other text."
        )
        parse_result = await llm_chat(
            [{"role": "user", "content": f"## Build Errors Report\n\n{report_content}"}],
            system=system,
            temperature=0.1,
        )

        parse_result = parse_result.strip()
        if parse_result.startswith("```"):
            parse_result = parse_result.split("\n", 1)[1]
        if parse_result.endswith("```"):
            parse_result = parse_result.rsplit("\n", 1)[0]
        if parse_result.startswith("json"):
            parse_result = parse_result[4:].strip()

        try:
            errors = json.loads(parse_result)
        except json.JSONDecodeError as je:
            _logger.warning("LLM parse failed (%s), falling back to regex", je)
            errors = _regex_parse_errors(report_content)

        if not errors:
            return json.dumps({"error": "Could not parse any errors from report", "raw_llm": parse_result}, indent=2)

        # Step 3: Research failing APIs
        researched_apis: dict[str, str] = {}
        if research_apis:
            symbols = set()
            for e in errors:
                sym = e.get("symbol", "")
                if sym and sym != "unknown":
                    symbols.add(sym)

            for sym in sorted(symbols):
                try:
                    _logger.info("Researching API: %s", sym)
                    research_result = await research(query=sym, revit_version="2024")
                    data = json.loads(research_result)
                    researched_apis[sym] = data.get("analysis", "No analysis available")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    _logger.warning("Research failed for %s: %s", sym, e)
                    researched_apis[sym] = f"Research failed: {e}"

        # Step 4: Generate fix recipes
        system2 = (
            "You are a Revit VersionCompat code generator. "
            "Given a list of build errors and API research results, "
            "generate a structured fix plan markdown document.\n\n"
            "For each error, include:\n"
            "1. **Problem**: what the error means\n"
            "2. **Root Cause**: which versions have the API, which don't\n"
            "3. **Fix Strategy**: which pattern applies\n"
            "4. **Code**: exact C# code for the VersionCompat wrapper method\n\n"
            "Available fix patterns:\n"
            "- **Guard direction swap**: `#if !REVIT_X_OR_NEWER` ↔ `#if REVIT_X_OR_NEWER`\n"
            "- **Guard version change**: `REVIT2026` → `REVIT2025` (or vice versa)\n"
            "- **3-way lifecycle**: API exists in some versions, not in older, renamed in newer\n"
            "- **Reflection path**: internal type needs `Assembly.GetType()` + `dynamic`\n"
            "- **NET48 branch**: .NET Framework API diff needs `#if NET48`\n"
            "- **New compat file**: completely new wrapper file\n\n"
            "Group by file and order by: R22/R23 first → R24/R25 → R27\n"
            "Output in clean GitHub-flavored markdown."
        )

        context_parts = [f"## Parsed Errors ({len(errors)} total)"]
        context_parts.append(json.dumps(errors, indent=2, ensure_ascii=False))

        if researched_apis:
            context_parts.append("\n## API Research Results")
            for sym, analysis in researched_apis.items():
                context_parts.append(f"\n### {sym}\n{analysis[:2000]}")

        fix_plan = await llm_chat(
            [{"role": "user", "content": "\n".join(context_parts)}],
            system=system2,
            temperature=0.2,
        )

        summary: dict[str, Any] = {
            "report_analyzed": {
                "total_errors_parsed": len(errors),
                "versions_affected": sorted(set(e.get("version", "") for e in errors)),
                "unique_symbols": sorted(set(e.get("symbol", "") for e in errors if e.get("symbol"))),
                "error_categories": {},
            },
            "apis_researched": len(researched_apis),
            "fix_plan": fix_plan,
        }

        for e in errors:
            cat = e.get("category", "unknown")
            summary["report_analyzed"]["error_categories"].setdefault(cat, 0)
            summary["report_analyzed"]["error_categories"][cat] += 1

        return json.dumps(summary, indent=2, ensure_ascii=False)

    except Exception as e:
        _logger.error("analyze_build_errors failed: %s", e, exc_info=True)
        return format_error(f"Build error analysis failed: {e}")


def _regex_parse_errors(report_content: str) -> list[dict]:
    """Fallback: parse errors from report using regex when LLM fails."""
    errors: list[dict] = []
    current_version = "unknown"
    version_pattern = re.compile(r"##\s+[❌✅]\s*(R\d{2})\s*\(Revit\s+\d{4}\)")

    current_header = ""
    for line in report_content.split("\n"):
        vm = version_pattern.search(line)
        if vm:
            current_version = vm.group(1)

        cm = re.search(r"(CS\d{4})\s*[—–-]+\s*(.*)", line)
        if cm:
            errors.append({
                "version": current_version,
                "code": cm.group(1),
                "symbol": cm.group(2).split("—")[0].split("—")[0].strip(),
                "description": cm.group(2).strip(),
                "category": "unknown",
                "file": current_header,
                "line": 0,
            })
        elif line.strip().startswith("- **File:**"):
            current_header = line.split("**File:**")[1].strip().split("`")[1] if "`" in line else ""

    return errors


# ─── Combined Research Pipeline ────────────────────────────────────────────

@mcp.tool(
    name="research",
    annotations={
        "title": "Full research: Qdrant + rvtdocs + LLM analysis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def research(query: str, revit_version: str = "2024") -> str:
    """Complete research pipeline: Qdrant + rvtdocs → LLM analysis with cross-version awareness."""
    if llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        return format_error("ROUTERAI_API_KEY not set for LLM analysis (or set LLM_PROVIDER=ollama). Qdrant search still works.")

    try:
        qdrant_results = json.loads(
            await qdrant_search(query=query, collection="revit_api_knowledge", limit=5, version=revit_version)
        )
        sdk_results = json.loads(
            await qdrant_search(query=query, collection="Revit_SDK_Samples", limit=5, version=revit_version)
        )
        whatsnew_results = json.loads(
            await qdrant_search(query=query, collection="revit_api_whatsnew", limit=8)
        )
        rvtdocs_results = json.loads(
            await rvtdocs_search(query=query, version=revit_version, limit=8)
        )
        config_versions = get_cfg("revit_versions", default=["2021","2022","2023","2024","2025","2026","2027"])
        cross_version = json.loads(
            await rvtdocs_cross_version_search(query=query, limit=3, versions=config_versions)
        )

        context_parts: list[str] = []
        if "results" in qdrant_results:
            context_parts.append(f"## Qdrant Results — revit_api_knowledge (filtered for Revit {revit_version})")
            for r in qdrant_results["results"]:
                context_parts.append(
                    f"- {r['payload']['name']} (score: {r['score']}): {r['payload']['summary'][:300]}"
                )
        if "results" in sdk_results:
            context_parts.append(f"\n## Qdrant Results — Revit_SDK_Samples (filtered for Revit {revit_version})")
            for r in sdk_results["results"]:
                context_parts.append(
                    f"- {r['payload']['name']} (score: {r['score']}): {r['payload']['summary'][:300]}"
                )
        if "results" in rvtdocs_results:
            context_parts.append(f"\n## rvtdocs Results (version {revit_version})")
            for r in rvtdocs_results["results"]:
                context_parts.append(f"- {r['title']} ({r['type']}): {r['description'][:300]}")

        if "results" in whatsnew_results:
            context_parts.append("\n## Revit API What's New (changelogs 2022-2026)")
            context_parts.append("IMPORTANT: These changelogs show what changed BETWEEN versions.")
            for r in whatsnew_results["results"]:
                context_parts.append(
                    f"- Revit {r['payload'].get('version', '?')} [{r['payload'].get('section', '')}] "
                    f"{r['payload'].get('subsection', '')[:200]} (score: {r['score']})"
                )

        if cross_version.get("results_by_version"):
            context_parts.append("\n## Cross-Version API Availability")
            for ver, items in cross_version["results_by_version"].items():
                titles = [i["title"] for i in items]
                if titles:
                    context_parts.append(f"- Revit {ver}: {', '.join(titles)}")
                else:
                    context_parts.append(f"- Revit {ver}: (no direct matches)")

        context = "\n".join(context_parts) if context_parts else "No results found."

        system = get_cfg("prompts", "research", default="").format(
            revit_version=revit_version,
        )
        result = await llm_chat(
            [{"role": "user", "content": f"## Question\n{query}\n\n## Search Results\n{context}"}],
            system=system,
        )

        response = {
            "query": query,
            "revit_version": revit_version,
            "qdrant_count": qdrant_results.get("count", 0),
            "sdk_count": sdk_results.get("count", 0),
            "whatsnew_count": whatsnew_results.get("count", 0),
            "rvtdocs_count": rvtdocs_results.get("count", 0),
            "cross_version_searched": config_versions,
            "analysis": result,
        }
        return truncate_response(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        _logger.error("research failed: %s", e, exc_info=True)
        return format_error(f"Research failed: {e}")
