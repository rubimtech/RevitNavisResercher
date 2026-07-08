#!/usr/bin/env python3
"""
MCP test client — connects to the server via stdio, calls analyze_build_errors.
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    report_path = Path(r"D:\DEV\ReviBE\build-reports\logs\20260708-110826\build-errors-report.md")
    if not report_path.exists():
        print(f"Report not found: {report_path}", file=sys.stderr)
        sys.exit(1)

    report_content = report_path.read_text(encoding="utf-8")

    server_params = StdioServerParameters(
        command=sys.executable or "python",
        args=["mcp_server.py", "--log-level", "INFO"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✓ Connected to MCP server", file=sys.stderr)

            # List tools
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"✓ Tools available: {tool_names}", file=sys.stderr)

            # Call analyze_build_errors
            print("→ Calling analyze_build_errors...", file=sys.stderr)
            result = await session.call_tool(
                "analyze_build_errors",
                arguments={
                    "report_content": report_content,
                    "research_apis": False,
                },
            )

            # Print the result
            for content_item in result.content:
                if hasattr(content_item, "text"):
                    # Try to parse and pretty-print JSON
                    try:
                        data = json.loads(content_item.text)
                        print(json.dumps(data, indent=2, ensure_ascii=False))
                    except (json.JSONDecodeError, TypeError):
                        print(content_item.text)
                else:
                    print(str(content_item))


if __name__ == "__main__":
    asyncio.run(main())
