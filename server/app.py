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

from server.lifecycle import ApplicationLifecycle
from server.transport import get_transport_config, get_transport_type


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

        print(f"\n[server] Starting MCP server '{lifecycle.config.application.name}'...")
        print(f"[server] Configured transport: {lifecycle.config.mcp.transport} (mode: {transport_type})")
        if transport_type == "streamable-http":
            print(f"[server] Remote HTTP Host: {lifecycle.config.mcp.host}:{lifecycle.config.mcp.port}")
            print(f"[server] Endpoint: http://{lifecycle.config.mcp.host}:{lifecycle.config.mcp.port}/mcp")
        elif transport_type == "sse":
            print(f"[server] Remote HTTP Host: {lifecycle.config.mcp.host}:{lifecycle.config.mcp.port}")
            print(f"[server] SSE Endpoint: http://{lifecycle.config.mcp.host}:{lifecycle.config.mcp.port}/sse")

        transport = transport_config.pop("transport")
        mcp.run(transport=transport, **transport_config)

    except KeyboardInterrupt:
        print("\n[server] Server interrupted by user.")
    except Exception as e:
        print(f"\n[server] Fatal error during startup or execution: {e}")
        raise
    finally:
        print("\n[server] Cleaning up resources...")
        try:
            loop.run_until_complete(lifecycle.shutdown())
        except Exception as e:
            print(f"[server] Error during shutdown cleanup: {e}")
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

