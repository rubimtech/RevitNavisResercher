#!/usr/bin/env python3
"""
RevitNavisResearcher — MCP Server entry point.

Thin entry point — all logic lives in the ``server/`` package.
Usage:
    python mcp_server.py [--transport stdio|sse] [--port 8000] [--log-level INFO]
"""

from server.app import main

if __name__ == "__main__":
    main()
