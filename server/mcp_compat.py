"""Compatibility layer for MCP Python SDK across versions.

Supports both MCP v2.x (MCPServer) and MCP v1.x (FastMCP).
"""

from __future__ import annotations

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:
        from mcp.server import Server as MCPServer

# Provide both names for compatibility
FastMCP = MCPServer

__all__ = ["MCPServer", "FastMCP"]

