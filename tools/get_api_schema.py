"""MCP tool: get_api_schema — Retrieve detailed API contract.

Purpose: Return the complete business and technical contract for one API,
identified by its composite key (endpoint_name, method).

Does not accept an api_id. Does not execute APIs.
"""

from __future__ import annotations

import json
import time
from typing import Any

from observability.json_logging import get_logger
from schemas.errors import McpToolError
from schemas.tool_arguments import GetApiSchemaArgs
from server.mcp_compat import FastMCP

_logger = get_logger("tools.get_api_schema")


def register_get_api_schema(mcp: FastMCP, schema_service: Any) -> None:
    """Register the get_api_schema tool with the MCP server."""

    @mcp.tool(
        name="get_api_schema",
        description=(
            "Retrieve the detailed business and technical contract for a "
            "specific API identified by endpoint_name and method. "
            "Returns parameter details, request/response schemas, business "
            "descriptions, use cases, and dependency information. "
            "Use this after search_apis identifies a candidate, and before "
            "calling execute_api."
        ),
    )
    async def get_api_schema(
        endpoint_name: str,
        method: str,
    ) -> str:
        """Get the complete schema for an API.

        Args:
            endpoint_name: The API endpoint name from the catalog.
            method: HTTP method (e.g., GET, POST).

        Returns:
            JSON string with the complete API schema.
        """
        start_time = time.perf_counter()
        try:
            args = GetApiSchemaArgs(
                endpoint_name=endpoint_name,
                method=method,
            )
            result = schema_service.get_schema(
                endpoint_name=args.endpoint_name,
                method=args.method,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            _logger.info_event(
                "get_api_schema executed",
                tool_name="get_api_schema",
                endpoint_name=args.endpoint_name,
                method=args.method,
                duration_ms=duration_ms,
                outcome="success",
            )
            return json.dumps(result.model_dump(exclude_none=True), indent=2)

        except McpToolError as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            _logger.warning_event(
                "get_api_schema error",
                tool_name="get_api_schema",
                endpoint_name=endpoint_name,
                method=method.upper(),
                duration_ms=duration_ms,
                error_code=e.error.code.value,
                outcome="tool_error",
            )
            return json.dumps(e.error.to_dict(), indent=2)

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            _logger.error_event(
                "get_api_schema unexpected failure",
                tool_name="get_api_schema",
                endpoint_name=endpoint_name,
                method=method.upper(),
                duration_ms=duration_ms,
                error_code="INTERNAL_ERROR",
                outcome="internal_error",
                details={"error": str(e)},
            )
            return json.dumps({
                "error": True,
                "code": "INTERNAL_ERROR",
                "message": f"Schema retrieval failed: {type(e).__name__}",
            }, indent=2)
