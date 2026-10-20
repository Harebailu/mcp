"""Validate the API catalog for uniqueness, route mappings,
dependency integrity, enumeration constraints, and status consistency.

Validation rules:
1. Composite key (endpoint_name, method) must be unique across all domain files.
2. Endpoint paths and names must be non-empty.
3. method must be one of GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS.
4. access_mode must be read_only or read_write.
5. approval_status must be pending_review, approved, or rejected.
6. enabled must be a strict boolean; enabled=true is only allowed when approval_status='approved'.
7. Dependency references must resolve to existing catalog entries.
8. Cyclic dependencies must be detected and reported.
9. Paths and methods must correspond to intended OpenAPI operations when available.
10. Inconsistent path/operation_id mappings are rejected.
"""

from __future__ import annotations

from typing import Optional

from schemas.catalog import ApiCatalog, CatalogEntry
from schemas.api_contract import ResolvedOperation

_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_ALLOWED_APPROVAL_STATUSES = frozenset({"pending_review", "approved", "rejected"})
_ALLOWED_ACCESS_MODES = frozenset({"read_only", "read_write"})


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
    """Run all catalog validations across all domain-loaded entries.

    Args:
        catalog: The loaded API catalog (combined domain entries).
        openapi_operations: Resolved OpenAPI operations keyed by (path, METHOD),
                           used for cross-validation.

    Returns:
        A ValidationResult with accumulated errors and warnings.
    """
    result = ValidationResult()

    _check_composite_key_uniqueness(catalog, result)
    _check_required_fields_and_constraints(catalog, result)
    _check_status_consistency(catalog, result)
    _check_dependency_references(catalog, result)
    _check_cyclic_dependencies(catalog, result)

    if openapi_operations:
        _check_openapi_mapping(catalog, openapi_operations, result)

    return result


def _check_composite_key_uniqueness(
    catalog: ApiCatalog, result: ValidationResult
) -> None:
    """Ensure each (endpoint_name, method) is unique across all domain files."""
    seen: dict[tuple[str, str], int] = {}
    for idx, entry in enumerate(catalog.apis):
        key = entry.composite_key
        if key in seen:
            result.add_error(
                f"Duplicate composite identity {key} at entries "
                f"[{seen[key]}] and [{idx}]."
            )
        else:
            seen[key] = idx


def _check_required_fields_and_constraints(
    catalog: ApiCatalog, result: ValidationResult
) -> None:
    """Verify required fields are present and enumeration constraints are satisfied."""
    for entry in catalog.apis:
        if not entry.endpoint_name or not entry.endpoint_name.strip():
            result.add_error("Entry with empty endpoint_name found.")
        if not entry.path or not entry.path.strip():
            result.add_error(
                f"Entry '{entry.endpoint_name}' ({entry.method}) has an empty path."
            )
        if not entry.display_name or not entry.display_name.strip():
            result.add_error(
                f"Entry '{entry.endpoint_name}' ({entry.method}) has an empty display_name."
            )
        if not entry.description or not entry.description.strip():
            result.add_error(
                f"Entry '{entry.endpoint_name}' ({entry.method}) has an empty description."
            )

        # Method validation
        if entry.method.upper() not in _ALLOWED_METHODS:
            result.add_error(
                f"Entry '{entry.endpoint_name}' has invalid method '{entry.method}'. "
                f"Allowed: {sorted(_ALLOWED_METHODS)}."
            )

        # Access mode validation
        if entry.access_mode not in _ALLOWED_ACCESS_MODES:
            result.add_error(
                f"Entry '{entry.endpoint_name}' has invalid access_mode '{entry.access_mode}'. "
                f"Allowed: {sorted(_ALLOWED_ACCESS_MODES)}."
            )

        # Approval status validation
        if entry.approval_status not in _ALLOWED_APPROVAL_STATUSES:
            result.add_error(
                f"Entry '{entry.endpoint_name}' has invalid approval_status '{entry.approval_status}'. "
                f"Allowed: {sorted(_ALLOWED_APPROVAL_STATUSES)}."
            )

        # Strict boolean check for enabled
        if not isinstance(entry.enabled, bool):
            result.add_error(
                f"Entry '{entry.endpoint_name}' has non-boolean enabled value: {entry.enabled}."
            )


def _check_status_consistency(
    catalog: ApiCatalog, result: ValidationResult
) -> None:
    """Ensure enabled: true is ONLY permitted when approval_status='approved'."""
    for entry in catalog.apis:
        if entry.enabled and entry.approval_status != "approved":
            result.add_error(
                f"Entry '{entry.endpoint_name}' ({entry.method}) has enabled=true but "
                f"approval_status='{entry.approval_status}'. "
                f"enabled=true is only allowed when approval_status='approved'."
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
    adj: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for entry in catalog.apis:
        key = entry.composite_key
        adj[key] = []
        if entry.dependent_apis:
            for dep in entry.dependent_apis:
                dep_key = (dep.endpoint_name, dep.method.upper())
                adj[key].append(dep_key)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[tuple[str, str], int] = {k: WHITE for k in adj}

    def dfs(node: tuple[str, str], path: list[tuple[str, str]]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in adj.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
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

        if entry.operation_id and op.operation_id:
            if entry.operation_id != op.operation_id:
                result.add_error(
                    f"Entry '{entry.endpoint_name}' ({entry.method}) has "
                    f"operation_id '{entry.operation_id}' but the OpenAPI "
                    f"operation at {entry.path} has operationId "
                    f"'{op.operation_id}'. Ambiguous mapping."
                )
