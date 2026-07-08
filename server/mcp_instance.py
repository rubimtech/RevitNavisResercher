"""
Shared MCP application instance.

All tool modules import `mcp` from here and register via @mcp.tool(...).
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("revit_navis_mcp")
