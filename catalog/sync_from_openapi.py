"""Synchronize the YAML catalog from an OpenAPI specification.

Bootstrap or refresh the API inventory from discovered OpenAPI JSON.

Behavior:
- Extracts actual operation identifiers (operationId) when available.
- Preserves actual HTTP methods and paths.
- Validates endpoint-name/method uniqueness.
- Populates the initial endpoint inventory without inventing business metadata.
- Marks operations as disabled and pending_review by default.
- Preserves manually curated descriptions, synonyms, dependencies, and
  approval metadata when refreshing.
- Detects removed or changed operations and reports the differences.
- Rejects ambiguous path or operation mappings.

Endpoint name derivation:
- If operationId exists and is unique, use it as endpoint_name.
- If operationId is absent, derive a stable name from the method and path.
  For example: GET /api/superusers -> GetApiSuperusers
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Optional

# Ensure project root is in sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from schemas.catalog import ApiCatalog, CatalogEntry, DependentApi
from schemas.api_contract import ResolvedOperation


class SyncReport:
    """Report of changes from catalog synchronization."""

    def __init__(self) -> None:
        self.added: list[str] = []
        self.updated: list[str] = []
        self.removed: list[str] = []
        self.unchanged: list[str] = []
        self.conflicts: list[str] = []
        self.warnings: list[str] = []

    def summary(self) -> str:
        lines = [
            f"Sync Report:",
            f"  Added: {len(self.added)}",
            f"  Updated: {len(self.updated)}",
            f"  Removed: {len(self.removed)}",
            f"  Unchanged: {len(self.unchanged)}",
            f"  Conflicts: {len(self.conflicts)}",
            f"  Warnings: {len(self.warnings)}",
        ]
        if self.added:
            lines.append("\nAdded operations:")
            for a in self.added:
                lines.append(f"  + {a}")
        if self.updated:
            lines.append("\nUpdated operations:")
            for u in self.updated:
                lines.append(f"  ~ {u}")
        if self.removed:
            lines.append("\nRemoved operations (no longer in OpenAPI):")
            for r in self.removed:
                lines.append(f"  - {r}")
        if self.conflicts:
            lines.append("\nConflicts:")
            for c in self.conflicts:
                lines.append(f"  ! {c}")
        if self.warnings:
            lines.append("\nWarnings:")
            for w in self.warnings:
                lines.append(f"  ? {w}")
        return "\n".join(lines)


def derive_endpoint_name(
    path: str, method: str, operation_id: Optional[str] = None
) -> str:
    """Derive a stable endpoint name for a catalog entry.

    If operationId is available and non-empty, use it directly.
    Otherwise, derive from the method and path:
        GET /api/projects/{projectId} -> GetApiProjectsByProjectId

    Args:
        path: The API path.
        method: The HTTP method.
        operation_id: The OpenAPI operationId, if available.

    Returns:
        A stable endpoint name string.
    """
    if operation_id and operation_id.strip():
        return operation_id.strip()

    # Derive from path + method
    method_prefix = method.strip().upper()
    method_capitalized = method_prefix.capitalize()

    # Clean path: remove leading /, split by / and {}
    clean_path = path.strip("/")
    segments = clean_path.split("/")

    name_parts = [method_capitalized]
    for segment in segments:
        if segment.startswith("{") and segment.endswith("}"):
            param_name = segment[1:-1]
            name_parts.append("By" + _capitalize_first(param_name))
        else:
            # Remove non-alphanumeric, capitalize
            clean = re.sub(r"[^a-zA-Z0-9]", "", segment)
            if clean:
                name_parts.append(_capitalize_first(clean))

    return "".join(name_parts)


def _capitalize_first(s: str) -> str:
    """Capitalize first letter."""
    if not s:
        return s
    return s[0].upper() + s[1:]


def derive_domain_from_tags(tags: list[str]) -> Optional[str]:
    """Derive a domain from OpenAPI tags."""
    if tags:
        return tags[0].lower().replace(" ", "_")
    return None


def sync_catalog_from_openapi(
    existing_catalog: Optional[ApiCatalog],
    openapi_operations: dict[tuple[str, str], ResolvedOperation],
) -> tuple[ApiCatalog, SyncReport]:
    """Synchronize the catalog from discovered OpenAPI operations.

    Merges new operations into the existing catalog while preserving
    manually curated business metadata.

    Args:
        existing_catalog: The current catalog, or None for initial bootstrap.
        openapi_operations: Resolved operations from OpenAPI, keyed by (path, METHOD).

    Returns:
        Tuple of (updated catalog, sync report).
    """
    report = SyncReport()

    # Build lookup of existing entries by composite key
    existing_by_key: dict[tuple[str, str], CatalogEntry] = {}
    existing_by_path_method: dict[tuple[str, str], CatalogEntry] = {}
    if existing_catalog:
        for entry in existing_catalog.apis:
            existing_by_key[entry.composite_key] = entry
            existing_by_path_method[(entry.path, entry.method.upper())] = entry

    # Track which existing entries are still present
    matched_existing_keys: set[tuple[str, str]] = set()

    # Check for ambiguous operationIds
    op_id_count: dict[str, int] = {}
    for (path, method), op in openapi_operations.items():
        if op.operation_id:
            op_id_count[op.operation_id] = op_id_count.get(op.operation_id, 0) + 1

    ambiguous_op_ids = {oid for oid, count in op_id_count.items() if count > 1}
    if ambiguous_op_ids:
        for oid in ambiguous_op_ids:
            report.conflicts.append(
                f"operationId '{oid}' appears {op_id_count[oid]} times. "
                f"Using path-derived names for disambiguation."
            )

    new_entries: list[CatalogEntry] = []

    for (path, method), op in openapi_operations.items():
        # Determine endpoint_name
        use_op_id = op.operation_id if (
            op.operation_id and op.operation_id not in ambiguous_op_ids
        ) else None
        endpoint_name = derive_endpoint_name(path, method, use_op_id)
        key = (endpoint_name, method.upper())

        # Check if this entry already exists
        existing_entry = existing_by_key.get(key) or existing_by_path_method.get((path, method.upper()))

        if existing_entry:
            matched_existing_keys.add(existing_entry.composite_key)

            # Check for path changes
            if existing_entry.path != path:
                report.updated.append(
                    f"{endpoint_name} ({method}): path changed "
                    f"'{existing_entry.path}' -> '{path}'"
                )

            # Preserve existing entry with its curated metadata
            # Only update the path if it changed
            updated = existing_entry.model_copy(
                update={"path": path, "operation_id": use_op_id}
            )
            new_entries.append(updated)
            if existing_entry.path == path:
                report.unchanged.append(f"{endpoint_name} ({method})")
        else:
            # New operation - create entry with defaults
            display_name = (
                op.summary
                or (op.operation_id if op.operation_id else None)
                or endpoint_name
            )

            domain = derive_domain_from_tags(op.tags)

            new_entry = CatalogEntry(
                endpoint_name=endpoint_name,
                method=method.upper(),
                path=path,
                operation_id=use_op_id,
                domain=domain,
                display_name=display_name or endpoint_name,
                description=op.description or op.summary or f"Endpoint {endpoint_name} ({method.upper()})",
                enabled=False,
                approval_status="pending_review",
                access_mode="read_only",
            )
            new_entries.append(new_entry)
            report.added.append(f"{endpoint_name} ({method})")

    # Detect removed operations
    for key, entry in existing_by_key.items():
        if key not in matched_existing_keys:
            report.removed.append(f"{entry.endpoint_name} ({entry.method})")
            # Keep the entry but warn
            report.warnings.append(
                f"'{entry.endpoint_name}' ({entry.method}) is no longer "
                f"in the OpenAPI spec. The catalog entry is preserved "
                f"but should be reviewed."
            )
            new_entries.append(entry)

    # Check for new composite-key uniqueness
    seen_keys: set[tuple[str, str]] = set()
    for entry in new_entries:
        if entry.composite_key in seen_keys:
            report.conflicts.append(
                f"Duplicate key after sync: {entry.composite_key}"
            )
        seen_keys.add(entry.composite_key)

    updated_catalog = ApiCatalog(
        catalog_version=(
            existing_catalog.catalog_version if existing_catalog else "1.0"
        ),
        apis=new_entries,
    )

    return updated_catalog, report


async def run_sync_cli(
    swagger_ui_url: str = "http://localhost:5273/swagger/index.html",
    explicit_spec_url: Optional[str] = None,
    catalog_path: Optional[str] = None,
    write_back: bool = True,
) -> None:
    """CLI runner to sync catalog from OpenAPI specification."""
    from catalog.openapi_loader import OpenApiLoader
    from catalog.yaml_loader import load_yaml_catalog, save_yaml_catalog

    loader = OpenApiLoader()
    print(f"[sync] Discovering spec from Swagger UI: {swagger_ui_url}")
    spec_url = await loader.discover_spec_url(swagger_ui_url, explicit_spec_url)
    print(f"[sync] Loading OpenAPI spec from: {spec_url}")
    await loader.load_spec(spec_url)
    operations = loader.parse_operations()
    print(f"[sync] Parsed {len(operations)} operations: {loader.get_operation_count()}")

    existing_catalog = None
    try:
        existing_catalog = load_yaml_catalog(catalog_path)
        print(f"[sync] Loaded existing catalog with {len(existing_catalog.apis)} APIs.")
    except Exception as e:
        print(f"[sync] No existing catalog loaded ({e}). Starting fresh.")

    updated_catalog, report = sync_catalog_from_openapi(existing_catalog, operations)
    print(f"\n{report.summary()}\n")

    if write_back:
        saved_path = save_yaml_catalog(updated_catalog, catalog_path)
        print(f"[sync] Catalog successfully saved to: {saved_path}")


if __name__ == "__main__":
    import asyncio
    import sys
    from pathlib import Path

    # Add project root to path
    proj_root = Path(__file__).resolve().parent.parent
    if str(proj_root) not in sys.path:
        sys.path.insert(0, str(proj_root))

    asyncio.run(run_sync_cli())

