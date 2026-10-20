"""MCP tool: execute_api — Execute one approved API operation.

Executes a single .NET API operation after server-side validation.
Uses the generic input schema (endpoint_name, method, path_params,
query_params, body) rather than a unique schema per endpoint.

Security:
- Never accepts agent-supplied URLs, base URLs, or arbitrary headers.
- Enforces server-side read-only policy.
- Validates arguments against OpenAPI contract at runtime.
- Does not forward the inbound MCP JWT downstream.
- Does not automatically execute dependent APIs.
"""

from __future__ import annotations

import json
import time
from typing import Any

from observability.json_logging import get_logger
from schemas.errors import McpToolError
from schemas.tool_arguments import ExecuteApiArgs
from server.mcp_compat import FastMCP

_logger = get_logger("tools.execute_api")


def register_execute_api(
    mcp: FastMCP,
    execution_service: Any,
    auth_config: Any,
) -> None:
    """Register the execute_api tool with the MCP server."""

    @mcp.tool(
        name="execute_api",
        description=(
            "Execute a single approved API operation. "
            "Provide the endpoint_name and method from the catalog, "
            "along with any required path_params, query_params, or body. "
            "Only explicitly approved read-only operations may execute. "
            "Use get_api_schema first to understand required parameters. "
            "For APIs with dependencies, call the dependent APIs first "
            "through separate execute_api calls to obtain required values."
        ),
    )
    async def execute_api(
        endpoint_name: str,
        method: str,
        path_params: dict[str, Any] | None = None,
        query_params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> str:
        """Execute an approved API operation.

        Args:
            endpoint_name: The API endpoint name from the catalog.
            method: HTTP method (e.g., GET).
            path_params: Values for path parameters.
            query_params: Values for query parameters.
            body: Request body (only if permitted by the API contract).

        Returns:
            JSON string with the execution result.
        """
        start_time = time.perf_counter()
        try:
            args = ExecuteApiArgs(
                endpoint_name=endpoint_name,
                method=method,
                path_params=path_params,
                query_params=query_params,
                body=body,
            )

            result = await execution_service.execute(
                endpoint_name=args.endpoint_name,
                method=args.method,
                path_params=args.path_params,
                query_params=args.query_params,
                body=args.body,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            _logger.info_event(
                "execute_api executed",
                tool_name="execute_api",
                endpoint_name=args.endpoint_name,
                method=args.method,
                duration_ms=duration_ms,
                outcome="success" if result.success else "downstream_error",
                upstream_status=result.status_code,
            )
            return json.dumps(result.model_dump(exclude_none=True), indent=2)

        except McpToolError as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            _logger.warning_event(
                "execute_api policy or validation denial",
                tool_name="execute_api",
                endpoint_name=endpoint_name,
                method=method.upper(),
                duration_ms=duration_ms,
                error_code=e.error.code.value,
                outcome="denied",
            )
            return json.dumps(e.error.to_dict(), indent=2)

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            _logger.error_event(
                "execute_api unexpected failure",
                tool_name="execute_api",
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
                "message": f"Execution failed: {type(e).__name__}",
            }, indent=2)
