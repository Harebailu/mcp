"""MCP tool: list_all_apis — Fallback catalog enumeration.

This is a SECONDARY discovery tool, not the primary search strategy.
Agents should use search_apis first for normal API discovery.
Use this tool only when search does not reveal a suitable API
or its results are insufficient to make a reliable selection.
"""

from __future__ import annotations

import json
import math
from typing import Any

from server.mcp_compat import FastMCP

from catalog.registry import ApiRegistry
from schemas.tool_arguments import ListAllApisArgs
from schemas.tool_results import CatalogListEntry, ListAllApisResult
from schemas.errors import McpToolError


def register_list_all_apis(mcp: FastMCP, registry: ApiRegistry) -> None:
    """Register the list_all_apis tool with the MCP server."""

    @mcp.tool(
        name="list_all_apis",
        description=(
            "FALLBACK DISCOVERY: Enumerate all APIs in the catalog with pagination. "
            "IMPORTANT: First use search_apis for normal API discovery. "
            "Use list_all_apis ONLY when search does not reveal a suitable API "
            "or its results are insufficient to make a reliable selection. "
            "Once a candidate is identified, use get_api_schema for its "
            "complete technical contract. "
            "Includes disabled and pending-review entries with clear status."
        ),
    )
    async def list_all_apis(
        page: int = 1,
        page_size: int = 20,
        domain: str | None = None,
    ) -> str:
        """List all APIs in the catalog with pagination.

        Args:
            page: Page number (1-based, default: 1).
            page_size: Entries per page (1-50, default: 20).
            domain: Optional domain filter.

        Returns:
            JSON string with paginated catalog entries.
        """
        try:
            args = ListAllApisArgs(
                page=page,
                page_size=page_size,
                domain=domain,
            )

            # Get entries
            if args.domain:
                all_entries = registry.get_entries_by_domain(args.domain)
            else:
                all_entries = registry.get_all_entries()

            total_count = len(all_entries)
            total_pages = max(1, math.ceil(total_count / args.page_size))

            # Paginate
            start_idx = (args.page - 1) * args.page_size
            end_idx = start_idx + args.page_size
            page_entries = all_entries[start_idx:end_idx]

            entries: list[CatalogListEntry] = []
            for entry in page_entries:
                dep_summaries = None
                if entry.dependent_apis:
                    dep_summaries = []
                    for dep in entry.dependent_apis:
                        summary = f"{dep.endpoint_name} ({dep.method})"
                        if dep.purpose:
                            summary += f": {dep.purpose.strip()}"
                        dep_summaries.append(summary)

                entries.append(
                    CatalogListEntry(
                        endpoint_name=entry.endpoint_name,
                        method=entry.method,
                        path=entry.path,
                        display_name=entry.display_name,
                        description=entry.description,
                        domain=entry.domain,
                        enabled=entry.enabled,
                        approval_status=entry.approval_status,
                        access_mode=entry.access_mode,
                        has_dependencies=bool(entry.dependent_apis),
                        dependency_summary=dep_summaries,
                    )
                )

            has_more = args.page < total_pages

            result = ListAllApisResult(
                total_count=total_count,
                page=args.page,
                page_size=args.page_size,
                total_pages=total_pages,
                has_more=has_more,
                entries=entries,
                message=(
                    f"Showing page {args.page} of {total_pages}. "
                    f"Total APIs: {total_count}."
                    + (f" Filtered by domain: {args.domain}." if args.domain else "")
                ),
            )

            return json.dumps(result.model_dump(exclude_none=True), indent=2)
        except McpToolError as e:
            return json.dumps(e.error.to_dict(), indent=2)
        except Exception as e:
            return json.dumps({
                "error": True,
                "code": "INTERNAL_ERROR",
                "message": f"Listing failed: {type(e).__name__}",
            }, indent=2)

