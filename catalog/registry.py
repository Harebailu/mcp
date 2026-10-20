"""Runtime API registry.

Publishes validated catalog metadata and resolved OpenAPI contracts
for runtime lookup by MCP tools and services.

The registry is the single source of truth at runtime. Tools and services
query the registry by composite key (endpoint_name, method) rather than
accessing YAML or OpenAPI directly.
"""

from __future__ import annotations

from typing import Optional

from schemas.catalog import ApiCatalog, CatalogEntry
from schemas.api_contract import ResolvedOperation
from schemas.errors import ErrorCode, McpToolError


class ApiRegistry:
    """Runtime registry for validated API metadata and contracts."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], CatalogEntry] = {}
        self._operations: dict[tuple[str, str], ResolvedOperation] = {}
        # Map composite key -> (path, method) for OpenAPI lookups
        self._key_to_path: dict[tuple[str, str], tuple[str, str]] = {}

    def register_catalog(self, catalog: ApiCatalog) -> None:
        """Register all validated catalog entries."""
        self._entries.clear()
        self._key_to_path.clear()

        for entry in catalog.apis:
            key = entry.composite_key
            self._entries[key] = entry
            self._key_to_path[key] = (entry.path, entry.method.upper())

    def register_operations(
        self, operations: dict[tuple[str, str], ResolvedOperation]
    ) -> None:
        """Register resolved OpenAPI operations."""
        self._operations = dict(operations)

    def get_entry(
        self, endpoint_name: str, method: str
    ) -> CatalogEntry:
        """Look up a catalog entry by composite key.

        Args:
            endpoint_name: The API endpoint name.
            method: The HTTP method.

        Returns:
            The matching CatalogEntry.

        Raises:
            McpToolError: If the entry is not found.
        """
        key = (endpoint_name, method.upper())
        entry = self._entries.get(key)
        if entry is None:
            raise McpToolError.from_code(
                ErrorCode.UNKNOWN_ENDPOINT,
                f"No API found with endpoint_name='{endpoint_name}' "
                f"and method='{method.upper()}'. "
                f"Use search_apis or list_all_apis to discover available APIs.",
                details={"endpoint_name": endpoint_name, "method": method.upper()},
            )
        return entry

    def get_operation(
        self, endpoint_name: str, method: str
    ) -> Optional[ResolvedOperation]:
        """Look up the resolved OpenAPI operation for a catalog entry."""
        key = (endpoint_name, method.upper())
        path_key = self._key_to_path.get(key)
        if path_key is None:
            return None
        return self._operations.get(path_key)

    def get_all_entries(self) -> list[CatalogEntry]:
        """Return all catalog entries."""
        return list(self._entries.values())

    def get_entries_by_domain(self, domain: str) -> list[CatalogEntry]:
        """Return catalog entries filtered by domain."""
        domain_lower = domain.lower()
        return [
            e for e in self._entries.values()
            if e.domain and e.domain.lower() == domain_lower
        ]

    def get_entry_count(self) -> int:
        """Return the total number of catalog entries."""
        return len(self._entries)

    def has_entry(self, endpoint_name: str, method: str) -> bool:
        """Check if an entry exists in the registry."""
        return (endpoint_name, method.upper()) in self._entries

    def get_all_composite_keys(self) -> list[tuple[str, str]]:
        """Return all registered composite keys."""
        return list(self._entries.keys())

    def get_domains(self) -> list[str]:
        """Return all unique domains."""
        domains = set()
        for entry in self._entries.values():
            if entry.domain:
                domains.add(entry.domain)
        return sorted(domains)
