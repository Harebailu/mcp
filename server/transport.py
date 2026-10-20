"""MCP transport configuration.

Configures transport settings for the MCP server.
Supports remote HTTP (Streamable HTTP / SSE) and STDIO for local development.
"""

from __future__ import annotations

from typing import Any, Literal
from config.config import AppConfig


def get_transport_type(config: AppConfig) -> str:
    """Normalize and return the transport type for MCP Server.

    Supports:
    - 'streamable-http' (remote HTTP transport with /mcp endpoint)
    - 'sse' (SSE HTTP transport)
    - 'stdio' (standard input/output)
    """
    transport = config.mcp.transport.lower().replace("_", "-")
    if transport in ("streamable-http", "http"):
        return "streamable-http"
    elif transport == "sse":
        return "sse"
    elif transport == "stdio":
        return "stdio"
    else:
        raise ValueError(
            f"Unsupported transport: {config.mcp.transport}. "
            f"Supported transports: 'streamable_http', 'sse', 'stdio'"
        )


def get_transport_config(config: AppConfig) -> dict[str, Any]:
    """Get transport configuration keyword arguments for the MCP server."""
    transport_type = get_transport_type(config)
    if transport_type in ("streamable-http", "sse"):
        return {
            "transport": transport_type,
            "host": config.mcp.host,
            "port": config.mcp.port,
        }
    return {
        "transport": "stdio",
    }

