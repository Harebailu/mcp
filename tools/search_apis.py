"""MCP tool: search_apis — Primary API discovery tool.

This is the agent's first choice for finding APIs. It searches the
business metadata catalog using multilingual semantic search and reranking.

Usage workflow:
1. Agent calls search_apis with a natural-language query.
2. Evaluates returned candidates.
3. If results are insufficient, uses list_all_apis as fallback.
4. Selects a candidate and calls get_api_schema.
5. Resolves dependencies if needed.
6. Calls execute_api with validated arguments.
"""

from __future__ import annotations

import json
import time
from typing import Any

from observability.json_logging import get_logger
from schemas.errors import McpToolError
from schemas.tool_arguments import SearchApisArgs
from server.mcp_compat import FastMCP

_logger = get_logger("tools.search_apis")


def register_search_apis(mcp: FastMCP, search_service: Any) -> None:
    """Register the search_apis tool with the MCP server."""

    @mcp.tool(
        name="search_apis",
        description=(
            "Search for APIs using natural-language queries. "
            "This is the PRIMARY and PREFERRED tool for API discovery. "
            "Use this tool FIRST to find relevant APIs before trying list_all_apis. "
            "Returns matching API candidates with business descriptions, "
            "endpoint names, methods, paths, and dependency information. "
            "After identifying a candidate, use get_api_schema to retrieve "
            "its detailed technical contract."
        ),
    )
    async def search_apis(
        query: str,
        domain: str | None = None,
        limit: int | None = None,
    ) -> str:
        """Search for APIs matching a natural-language query.

        Args:
            query: Natural-language description of the API you need (supports English and Korean).
            domain: Optional domain/category filter (e.g., 'superuser', 'auth').
            limit: Maximum number of results to return (default: 5, max: 20).

        Returns:
            JSON string with matching API candidates.
        """
        start_time = time.perf_counter()
        try:
            args = SearchApisArgs(
                query=query,
                domain=domain,
                limit=limit,
            )
            # Await async semantic search service
            if hasattr(search_service, "search"):
                import inspect
                if inspect.iscoroutinefunction(search_service.search):
                    result = await search_service.search(
                        query=args.query,
                        domain=args.domain,
                        limit=args.limit,
                    )
                else:
                    result = search_service.search(
                        query=args.query,
                        domain=args.domain,
                        limit=args.limit,
                    )
            else:
                raise RuntimeError("Configured search service has no 'search' method.")

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            _logger.info_event(
                "search_apis executed",
                tool_name="search_apis",
                duration_ms=duration_ms,
                outcome="success",
                candidate_count=result.total_matches,
            )
            return json.dumps(result.model_dump(exclude_none=True), indent=2)

        except McpToolError as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            _logger.warning_event(
                "search_apis error",
                tool_name="search_apis",
                duration_ms=duration_ms,
                error_code=e.error.code.value,
                outcome="tool_error",
            )
            return json.dumps(e.error.to_dict(), indent=2)

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            _logger.error_event(
                "search_apis unexpected failure",
                tool_name="search_apis",
                duration_ms=duration_ms,
                error_code="INTERNAL_ERROR",
                outcome="internal_error",
                details={"error": str(e)},
            )
            return json.dumps({
                "error": True,
                "code": "INTERNAL_ERROR",
                "message": f"Search failed: {type(e).__name__}: {e}",
            }, indent=2)
