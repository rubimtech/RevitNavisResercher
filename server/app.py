"""
Application entrypoint — wires config, logging, tool registration, and CLI.
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from server.config import DEFAULT_CONFIG_PATH, get_cfg, load_config, set_config
from server.logging_setup import setup_logging
from server.mcp_instance import mcp
from server.state import shutdown

# Import tool modules so @mcp.tool decorators register on the shared instance.
# This is done here (not in __init__.py) so config is available at import time.
if os.environ.get("RVTDOC_API_URL"):
    # Remote mode: use HTTP API instead of local SQLite
    import server.tools_rvtdocs_api  # noqa: F401
else:
    # Local mode: use direct SQLite access
    import server.tools_rvtdocs  # noqa: F401
    import server.tools_revitapidocs  # noqa: F401
    import server.tools_sqlite  # noqa: F401
import server.tools_qdrant  # noqa: F401
import server.tools_analyze  # noqa: F401

_logger: logging.Logger = None  # type: ignore[assignment]


async def _shutdown_then_exit() -> None:
    """Shutdown and exit."""
    await shutdown()
    sys.exit(0)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="RevitNavisResearcher MCP Server")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to YAML config")
    parser.add_argument("--transport", choices=["stdio", "sse"], help="Transport mode")
    parser.add_argument("--host", type=str, help="SSE host")
    parser.add_argument("--port", type=int, help="SSE port")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    parser.add_argument("--log-format", choices=["text", "json"], help="Log format")
    return parser.parse_args(argv)


async def amain(argv: Optional[list[str]] = None) -> None:
    """Async main entrypoint."""
    global _logger

    args = _parse_args(argv)

    # Load & store config
    cfg = load_config(args.config)
    set_config(cfg)

    # Setup logging
    log_level = args.log_level or get_cfg("logging", "level", default="INFO")
    log_format = args.log_format or get_cfg("logging", "format", default="text")
    _logger = setup_logging(log_level, log_format)

    # Resolve transport
    transport = args.transport or get_cfg("transport", "mode", default="stdio")
    host = args.host or get_cfg("transport", "host", default="0.0.0.0")
    port = args.port or get_cfg("transport", "port", default=8000)

    # Register signal handlers for graceful shutdown (Unix only)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown_then_exit()))
        except (NotImplementedError, ValueError):
            pass  # Windows doesn't support add_signal_handler

    _logger.info("🚀 Starting RevitNavis MCP server (transport=%s)", transport)
    _logger.info("   Qdrant: %s", get_cfg("qdrant", "url", default="http://localhost:6333"))
    _logger.info("   LLM provider: %s", get_cfg("llm", "provider", default="routerai"))

    if get_cfg("llm", "provider") == "ollama":
        _logger.info("   Ollama: %s | embed=%s, chat=%s",
            get_cfg("ollama", "base_url"),
            get_cfg("ollama", "embedding_model"),
            get_cfg("ollama", "chat_model"),
        )
    else:
        _logger.info("   RouterAI base: %s", get_cfg("llm", "base_url"))
        _logger.info("   Models: embed=%s, llm=%s", get_cfg("llm", "embedding_model"), get_cfg("llm", "chat_model"))
        api_key = os.environ.get("ROUTERAI_API_KEY", "")
        if not api_key or api_key in ("sk-placeholder", "sk-your-key-here"):
            _logger.warning("ROUTERAI_API_KEY not set or is a placeholder — LLM tools will fail")
        else:
            _logger.info("   RouterAI API key: OK")

    if transport == "sse":
        _logger.info("   SSE mode on http://%s:%d/mcp", host, port)
        mcp.settings.host = host
        mcp.settings.port = port
        try:
            await mcp.run_sse_async()
        except KeyboardInterrupt:
            _logger.info("Received KeyboardInterrupt, shutting down...")
        finally:
            await shutdown()
    else:
        _logger.info("   stdio mode — waiting for MCP messages...")
        try:
            await mcp.run_stdio_async()
        except KeyboardInterrupt:
            _logger.info("Received KeyboardInterrupt, shutting down...")
        finally:
            await shutdown()


def main(argv: Optional[list[str]] = None) -> None:
    """Synchronous entrypoint for console_scripts."""
    asyncio.run(amain(argv))
