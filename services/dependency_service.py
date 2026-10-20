"""Resolve and describe API dependencies.

Responsible for:
- Resolving dependent_apis references against the validated registry.
- Providing dependency metadata to help the agent discover upstream APIs.
- Detecting unresolvable or ambiguous dependency references.
- NOT automatically executing dependency chains.

The agent is responsible for calling upstream APIs through execute_api
to obtain required identifiers.
"""

from __future__ import annotations

from typing import Any, Optional

from catalog.registry import ApiRegistry
from schemas.catalog import CatalogEntry, DependentApi
from schemas.errors import ErrorCode, McpToolError


class DependencyService:
    """Resolves and describes API dependencies."""

    def __init__(self, registry: ApiRegistry) -> None:
        self._registry = registry

    def resolve_dependencies(
        self, entry: CatalogEntry
    ) -> list[ResolvedDependency]:
        """Resolve all dependencies for a catalog entry.

        Args:
            entry: The catalog entry whose dependencies to resolve.

        Returns:
            List of resolved dependency information.

        Raises:
            McpToolError: If a dependency reference cannot be resolved.
        """
        if not entry.dependent_apis:
            return []

        resolved: list[ResolvedDependency] = []

        for dep in entry.dependent_apis:
            dep_key = (dep.endpoint_name, dep.method.upper())

            if not self._registry.has_entry(dep.endpoint_name, dep.method):
                raise McpToolError.from_code(
                    ErrorCode.DEPENDENCY_NOT_FOUND,
                    f"Dependency '{dep.endpoint_name}' ({dep.method}) "
                    f"referenced by '{entry.endpoint_name}' ({entry.method}) "
                    f"does not exist in the catalog.",
                    details={
                        "source": entry.composite_key,
                        "missing_dependency": dep_key,
                    },
                )

            dep_entry = self._registry.get_entry(dep.endpoint_name, dep.method)

            resolved.append(
                ResolvedDependency(
                    endpoint_name=dep.endpoint_name,
                    method=dep.method.upper(),
                    path=dep_entry.path,
                    display_name=dep_entry.display_name,
                    purpose=dep.purpose,
                    output_to_input=dep.output_to_input,
                    is_available=dep_entry.is_executable,
                    approval_status=dep_entry.approval_status,
                )
            )

        return resolved

    def get_dependency_summaries(
        self, entry: CatalogEntry
    ) -> Optional[list[str]]:
        """Get human-readable dependency summaries for search results.

        Returns None if there are no dependencies.
        """
        if not entry.dependent_apis:
            return None

        summaries: list[str] = []
        for dep in entry.dependent_apis:
            summary = f"{dep.endpoint_name} ({dep.method})"
            if dep.purpose:
                summary += f": {dep.purpose.strip()}"
            summaries.append(summary)

        return summaries

    def format_dependencies_for_schema(
        self, entry: CatalogEntry
    ) -> Optional[list[dict[str, Any]]]:
        """Format dependency metadata for get_api_schema results."""
        if not entry.dependent_apis:
            return None

        deps_info: list[dict[str, Any]] = []
        for dep in entry.dependent_apis:
            dep_info: dict[str, Any] = {
                "endpoint_name": dep.endpoint_name,
                "method": dep.method.upper(),
                "purpose": dep.purpose,
            }

            # Add availability info
            if self._registry.has_entry(dep.endpoint_name, dep.method):
                dep_entry = self._registry.get_entry(dep.endpoint_name, dep.method)
                dep_info["path"] = dep_entry.path
                dep_info["is_available"] = dep_entry.is_executable
                dep_info["approval_status"] = dep_entry.approval_status

            if dep.output_to_input:
                dep_info["output_to_input"] = dep.output_to_input

            deps_info.append(dep_info)

        return deps_info


class ResolvedDependency:
    """A resolved dependency with full metadata."""

    def __init__(
        self,
        endpoint_name: str,
        method: str,
        path: str,
        display_name: Optional[str],
        purpose: Optional[str],
        output_to_input: Optional[dict[str, str]],
        is_available: bool,
        approval_status: str,
    ) -> None:
        self.endpoint_name = endpoint_name
        self.method = method
        self.path = path
        self.display_name = display_name
        self.purpose = purpose
        self.output_to_input = output_to_input
        self.is_available = is_available
        self.approval_status = approval_status

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "endpoint_name": self.endpoint_name,
            "method": self.method,
            "path": self.path,
            "purpose": self.purpose,
            "is_available": self.is_available,
            "approval_status": self.approval_status,
        }
        if self.display_name:
            result["display_name"] = self.display_name
        if self.output_to_input:
            result["output_to_input"] = self.output_to_input
        return result
