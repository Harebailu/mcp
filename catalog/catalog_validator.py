"""Validate the API catalog for uniqueness, route mappings,
dependency integrity, and metadata consistency.

Validation rules:
1. Composite key (endpoint_name, method) must be unique.
2. Endpoint paths must be non-empty.
3. Dependency references must resolve to existing catalog entries.
4. Cyclic dependencies must be detected and reported.
5. Paths and methods must correspond to the intended OpenAPI operations when available.
6. Inconsistent path/operation_id mappings are rejected.
"""

from __future__ import annotations

from typing import Optional

from schemas.catalog import ApiCatalog, CatalogEntry
from schemas.api_contract import ResolvedOperation


class ValidationResult:
    """Accumulates validation errors and warnings."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def summary(self) -> str:
        parts = []
        if self.errors:
            parts.append(f"{len(self.errors)} error(s):")
            for e in self.errors:
                parts.append(f"  ERROR: {e}")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s):")
            for w in self.warnings:
                parts.append(f"  WARNING: {w}")
        if not parts:
            parts.append("Catalog validation passed.")
        return "\n".join(parts)


def validate_catalog(
    catalog: ApiCatalog,
    openapi_operations: Optional[dict[tuple[str, str], ResolvedOperation]] = None,
) -> ValidationResult:
    """Run all catalog validations.

    Args:
        catalog: The loaded API catalog.
        openapi_operations: Resolved OpenAPI operations keyed by (path, METHOD),
                           used for cross-validation.

    Returns:
        A ValidationResult with accumulated errors and warnings.
    """
    result = ValidationResult()

    _check_composite_key_uniqueness(catalog, result)
    _check_required_fields(catalog, result)
    _check_dependency_references(catalog, result)
    _check_cyclic_dependencies(catalog, result)

    if openapi_operations:
        _check_openapi_mapping(catalog, openapi_operations, result)

    return result


def _check_composite_key_uniqueness(
    catalog: ApiCatalog, result: ValidationResult
) -> None:
    """Ensure each (endpoint_name, method) is unique."""
    seen: dict[tuple[str, str], int] = {}
    for idx, entry in enumerate(catalog.apis):
        key = entry.composite_key
        if key in seen:
            result.add_error(
                f"Duplicate composite key {key} at entries "
                f"[{seen[key]}] and [{idx}]."
            )
        else:
            seen[key] = idx


def _check_required_fields(
    catalog: ApiCatalog, result: ValidationResult
) -> None:
    """Verify required fields are present and valid."""
    for entry in catalog.apis:
        if not entry.endpoint_name.strip():
            result.add_error("Entry with empty endpoint_name found.")
        if not entry.path.strip():
            result.add_error(
                f"Entry '{entry.endpoint_name}' ({entry.method}) has an empty path."
            )
        if not entry.method.strip():
            result.add_error(
                f"Entry '{entry.endpoint_name}' has an empty method."
            )

        # Warn on missing business metadata
        if not entry.description:
            result.add_warning(
                f"Entry '{entry.endpoint_name}' ({entry.method}) has no description. "
                f"Mark for review."
            )
        if not entry.display_name:
            result.add_warning(
                f"Entry '{entry.endpoint_name}' ({entry.method}) has no display_name."
            )


def _check_dependency_references(
    catalog: ApiCatalog, result: ValidationResult
) -> None:
    """Verify that all dependent_apis references resolve to existing entries."""
    all_keys = {entry.composite_key for entry in catalog.apis}

    for entry in catalog.apis:
        if not entry.dependent_apis:
            continue
        for dep in entry.dependent_apis:
            dep_key = (dep.endpoint_name, dep.method.upper())
            if dep_key not in all_keys:
                result.add_error(
                    f"Entry '{entry.endpoint_name}' ({entry.method}) has a "
                    f"dependent_api reference to {dep_key} which does not exist "
                    f"in the catalog."
                )


def _check_cyclic_dependencies(
    catalog: ApiCatalog, result: ValidationResult
) -> None:
    """Detect cyclic dependency chains."""
    # Build adjacency list
    adj: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for entry in catalog.apis:
        key = entry.composite_key
        adj[key] = []
        if entry.dependent_apis:
            for dep in entry.dependent_apis:
                dep_key = (dep.endpoint_name, dep.method.upper())
                adj[key].append(dep_key)

    # DFS-based cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[tuple[str, str], int] = {k: WHITE for k in adj}

    def dfs(node: tuple[str, str], path: list[tuple[str, str]]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in adj.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                # Found a cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycle_str = " -> ".join(f"{e[0]}({e[1]})" for e in cycle)
                result.add_error(f"Cyclic dependency detected: {cycle_str}")
            elif color[neighbor] == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for node in adj:
        if color[node] == WHITE:
            dfs(node, [])


def _check_openapi_mapping(
    catalog: ApiCatalog,
    openapi_operations: dict[tuple[str, str], ResolvedOperation],
    result: ValidationResult,
) -> None:
    """Cross-validate catalog entries against OpenAPI operations."""
    for entry in catalog.apis:
        expected_key = (entry.path, entry.method.upper())

        if expected_key not in openapi_operations:
            result.add_warning(
                f"Entry '{entry.endpoint_name}' ({entry.method}) with path "
                f"'{entry.path}' does not map to any OpenAPI operation."
            )
            continue

        op = openapi_operations[expected_key]

        # If operation_id is set, verify it matches
        if entry.operation_id and op.operation_id:
            if entry.operation_id != op.operation_id:
                result.add_error(
                    f"Entry '{entry.endpoint_name}' ({entry.method}) has "
                    f"operation_id '{entry.operation_id}' but the OpenAPI "
                    f"operation at {entry.path} has operationId "
                    f"'{op.operation_id}'. Ambiguous mapping."
                )
