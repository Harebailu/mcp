"""Main application entry point for pm_mcp_server.

Starts the MCP server with the configured transport and handles
the full application lifecycle.

Usage:
    python -m server.app
    python server/app.py
    pm-mcp-server (via pyproject.toml entry point)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from observability.json_logging import get_logger
from server.lifecycle import ApplicationLifecycle
from server.transport import get_transport_config, get_transport_type

_logger = get_logger("server.app")


def run_server(config_path: str | None = None) -> None:
    """Initialize and run the MCP server."""
    lifecycle = ApplicationLifecycle()

    # Create event loop for initialization and shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        mcp = loop.run_until_complete(lifecycle.initialize(config_path))
        transport_type = get_transport_type(lifecycle.config)
        transport_config = get_transport_config(lifecycle.config)

        _logger.info_event(
            "Starting MCP server transport",
            details={
                "server_name": lifecycle.config.application.name,
                "transport": lifecycle.config.mcp.transport,
                "mode": transport_type,
                "host": lifecycle.config.mcp.host,
                "port": lifecycle.config.mcp.port,
            },
        )

        transport = transport_config.pop("transport")
        mcp.run(transport=transport, **transport_config)

    except KeyboardInterrupt:
        _logger.info_event("Server interrupted by user")
    except Exception as e:
        _logger.error_event("Fatal error during startup or execution", details={"error": str(e)})
        raise
    finally:
        _logger.info_event("Cleaning up server resources...")
        try:
            loop.run_until_complete(lifecycle.shutdown())
        except Exception as e:
            _logger.error_event("Error during shutdown cleanup", details={"error": str(e)})
        finally:
            loop.close()


def main() -> None:
    """CLI entrypoint."""
    config_path = None
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        config_path = sys.argv[1]

    run_server(config_path)


if __name__ == "__main__":
    main()

