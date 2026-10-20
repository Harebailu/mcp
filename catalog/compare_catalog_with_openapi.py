"""Compare curated API catalog with live OpenAPI specification.

REPORT-ONLY TOOL:
- Compares the curated domain-based YAML catalog against current OpenAPI specification.
- Produces a clear diff report of:
  * Matching operations
  * Path or parameter discrepancies
  * Removed operations (present in YAML, missing in OpenAPI)
  * Untracked operations (present in OpenAPI, not yet tracked in YAML)
- NEVER automatically rewrites, appends, or overwrites curated catalog files.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from catalog.openapi_loader import OpenApiLoader
from catalog.yaml_loader import load_yaml_catalog
from schemas.catalog import ApiCatalog
from schemas.api_contract import ResolvedOperation


class CatalogComparisonReport:
    """Structured report comparing YAML catalog with OpenAPI operations."""

    def __init__(self) -> None:
        self.matched: list[str] = []
        self.path_mismatches: list[str] = []
        self.removed_from_openapi: list[str] = []
        self.untracked_in_yaml: list[str] = []
        self.operation_id_conflicts: list[str] = []

    def summary(self) -> str:
        lines = [
            "============================================================",
            "        CATALOG VS OPENAPI CONTRACT DRIFT REPORT            ",
            "============================================================",
            f"  Matched Curated Operations:     {len(self.matched)}",
            f"  Removed from OpenAPI (in YAML): {len(self.removed_from_openapi)}",
            f"  Untracked in YAML (in OpenAPI): {len(self.untracked_in_yaml)}",
            f"  Path/Method Mismatches:         {len(self.path_mismatches)}",
            f"  Operation ID Conflicts:         {len(self.operation_id_conflicts)}",
            "------------------------------------------------------------",
        ]

        if self.matched:
            lines.append("\n[MATCHED OPERATIONS]:")
            for m in self.matched:
                lines.append(f"  OK   {m}")

        if self.removed_from_openapi:
            lines.append("\n[OPERATIONS REMOVED FROM OPENAPI (Still in YAML)]:")
            lines.append("  (Review whether these endpoints should be deprecated or removed)")
            for r in self.removed_from_openapi:
                lines.append(f"  WARN {r}")

        if self.untracked_in_yaml:
            lines.append("\n[UNTRACKED OPENAPI OPERATIONS (Not yet in YAML Catalog)]:")
            lines.append("  (Informational: these are new or uncurated operations in OpenAPI)")
            for u in self.untracked_in_yaml:
                lines.append(f"  INFO {u}")

        if self.path_mismatches:
            lines.append("\n[PATH/METHOD MISMATCHES]:")
            for p in self.path_mismatches:
                lines.append(f"  DIFF {p}")

        if self.operation_id_conflicts:
            lines.append("\n[OPERATION_ID CONFLICTS]:")
            for c in self.operation_id_conflicts:
                lines.append(f"  ERR  {c}")

        lines.append("\n============================================================")
        lines.append("NOTE: This is a read-only audit report. No catalog files were modified.")
        lines.append("============================================================")
        return "\n".join(lines)


def compare_catalog_with_openapi(
    catalog: ApiCatalog,
    openapi_operations: dict[tuple[str, str], ResolvedOperation],
) -> CatalogComparisonReport:
    """Compare the catalog against OpenAPI operations and return a drift report."""
    report = CatalogComparisonReport()

    # Map OpenAPI operations by (path, method) and by operation_id
    openapi_by_path_method = {
        (path, method.upper()): op for (path, method), op in openapi_operations.items()
    }
    matched_openapi_keys: set[tuple[str, str]] = set()

    for entry in catalog.apis:
        expected_key = (entry.path, entry.method.upper())

        if expected_key in openapi_by_path_method:
            op = openapi_by_path_method[expected_key]
            matched_openapi_keys.add(expected_key)
            report.matched.append(
                f"{entry.endpoint_name} [{entry.method} {entry.path}]"
            )

            # Check operationId consistency if specified
            if entry.operation_id and op.operation_id:
                if entry.operation_id != op.operation_id:
                    report.operation_id_conflicts.append(
                        f"{entry.endpoint_name}: YAML operation_id='{entry.operation_id}' != OpenAPI operationId='{op.operation_id}'"
                    )
        else:
            report.removed_from_openapi.append(
                f"{entry.endpoint_name} [{entry.method} {entry.path}]"
            )

    # Detect untracked OpenAPI operations
    for (path, method), op in openapi_operations.items():
        if (path, method.upper()) not in matched_openapi_keys:
            report.untracked_in_yaml.append(
                f"[{method} {path}] (tags={op.tags}, op_id={op.operation_id})"
            )

    return report


async def run_comparison_cli(
    swagger_ui_url: str = "http://localhost:5273/swagger/index.html",
    explicit_spec_url: Optional[str] = None,
    catalog_path: Optional[str] = None,
) -> CatalogComparisonReport:
    """CLI runner to perform read-only contract drift comparison."""
    loader = OpenApiLoader()
    print(f"[compare] Discovering OpenAPI spec from Swagger UI: {swagger_ui_url} ...")
    spec_url = await loader.discover_spec_url(swagger_ui_url, explicit_spec_url)
    print(f"[compare] Loading specification from: {spec_url} ...")
    await loader.load_spec(spec_url)
    operations = loader.parse_operations()
    print(f"[compare] Parsed {len(operations)} operations from OpenAPI.")

    catalog = load_yaml_catalog(catalog_path)
    print(f"[compare] Loaded curated catalog with {len(catalog.apis)} APIs across domain files.")

    report = compare_catalog_with_openapi(catalog, operations)
    print("\n" + report.summary())
    return report


if __name__ == "__main__":
    asyncio.run(run_comparison_cli())

