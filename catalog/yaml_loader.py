"""Load and validate the domain-based YAML API catalog.

Loads the root catalog manifest (catalog/api_catalog.yaml), resolves and validates
domain-specific YAML files (e.g. catalog/domains/*.yaml), enforces domain inheritance,
composite identity uniqueness, and produces a single combined ApiCatalog instance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from schemas.catalog import ApiCatalog, CatalogEntry, CatalogManifest, DomainCatalogFile


def _get_default_catalog_path() -> Path:
    """Return the default catalog root manifest path."""
    return Path(__file__).resolve().parent / "api_catalog.yaml"


def load_yaml_catalog(catalog_path: Optional[str | Path] = None) -> ApiCatalog:
    """Load and validate the domain-based YAML API catalog.

    Args:
        catalog_path: Path to the root catalog YAML file (manifest or single catalog).
                      Defaults to catalog/api_catalog.yaml.

    Returns:
        A combined and validated ApiCatalog instance.

    Raises:
        FileNotFoundError: If the manifest or any referenced domain file is missing.
        ValueError: If YAML syntax is invalid, paths escape the catalog root,
                    duplicate composite keys exist, or invalid fields are found.
    """
    manifest_path = Path(catalog_path) if catalog_path else _get_default_catalog_path()
    manifest_path = manifest_path.resolve()

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"API catalog manifest not found: {manifest_path}."
        )

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_raw = yaml.safe_load(f)

    if manifest_raw is None:
        return ApiCatalog()

    if not isinstance(manifest_raw, dict):
        raise ValueError(
            f"Catalog manifest must be a YAML mapping, got: {type(manifest_raw).__name__} in {manifest_path}"
        )

    catalog_dir = manifest_path.parent

    # Case A: Manifest-based catalog with domain_files
    if "domain_files" in manifest_raw:
        domain_files = manifest_raw.get("domain_files", [])
        if not isinstance(domain_files, list) or not domain_files:
            raise ValueError(f"Catalog manifest 'domain_files' must be a non-empty list in {manifest_path}")

        combined_apis: list[CatalogEntry] = []
        seen_identities: dict[tuple[str, str], str] = {}  # (name, method) -> source_file

        for rel_file in domain_files:
            domain_file_path = (catalog_dir / rel_file).resolve()

            # Security: ensure file remains inside the catalog directory (no path traversal)
            try:
                domain_file_path.relative_to(catalog_dir)
            except ValueError:
                raise ValueError(
                    f"Domain file '{rel_file}' attempts directory traversal outside catalog root: {catalog_dir}"
                )

            if not domain_file_path.exists():
                raise FileNotFoundError(
                    f"Referenced domain catalog file does not exist: {domain_file_path} (from {manifest_path})"
                )

            apis_in_file = _load_domain_file(domain_file_path, rel_file, seen_identities)
            combined_apis.extend(apis_in_file)

        return ApiCatalog(
            catalog_version=str(manifest_raw.get("catalog_version", "1.0")),
            domain_files=domain_files,
            apis=combined_apis,
        )

    # Case B: Legacy direct apis listing in single file
    elif "apis" in manifest_raw:
        apis_data = manifest_raw.get("apis", [])
        combined_apis = []
        seen_identities = {}
        for idx, entry_raw in enumerate(apis_data):
            _check_removed_fields(entry_raw, str(manifest_path), f"apis[{idx}]")
            entry = CatalogEntry.model_validate(entry_raw)
            key = entry.composite_key
            if key in seen_identities:
                raise ValueError(
                    f"Duplicate composite identity {key} found in {manifest_path}"
                )
            seen_identities[key] = str(manifest_path)
            combined_apis.append(entry)

        return ApiCatalog(
            catalog_version=str(manifest_raw.get("catalog_version", "1.0")),
            apis=combined_apis,
        )

    else:
        raise ValueError(
            f"Catalog root file {manifest_path} must contain either 'domain_files' or 'apis'."
        )


def _load_domain_file(
    file_path: Path,
    rel_path_str: str,
    seen_identities: dict[tuple[str, str], str],
) -> list[CatalogEntry]:
    """Parse and validate a single domain-specific YAML file."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Domain catalog file must be a YAML mapping: {file_path}")

    domain_name = data.get("domain")
    if not domain_name or not isinstance(domain_name, str) or not domain_name.strip():
        raise ValueError(f"Domain catalog file {file_path} must define a non-empty top-level 'domain' field.")

    domain_name = domain_name.strip()
    raw_apis = data.get("apis", [])
    if not isinstance(raw_apis, list):
        raise ValueError(f"'apis' field in {file_path} must be a list.")

    entries: list[CatalogEntry] = []

    for idx, entry_raw in enumerate(raw_apis):
        if not isinstance(entry_raw, dict):
            raise ValueError(f"Entry {idx} in {file_path} must be a mapping.")

        _check_removed_fields(entry_raw, rel_path_str, entry_raw.get("endpoint_name", f"apis[{idx}]"))

        # Domain inheritance
        entry_domain = entry_raw.get("domain")
        if entry_domain is None or entry_domain == "":
            entry_raw["domain"] = domain_name
        elif entry_domain != domain_name:
            raise ValueError(
                f"Entry '{entry_raw.get('endpoint_name')}' in {file_path} specifies domain '{entry_domain}' "
                f"which does not match containing file domain '{domain_name}'."
            )

        # Validate with strict CatalogEntry Pydantic model
        entry = CatalogEntry.model_validate(entry_raw)
        key = entry.composite_key

        if key in seen_identities:
            prev_file = seen_identities[key]
            raise ValueError(
                f"Duplicate API composite identity {key} detected in '{rel_path_str}'. "
                f"Already defined in '{prev_file}'."
            )

        seen_identities[key] = rel_path_str
        entries.append(entry)

    return entries


def _check_removed_fields(entry_dict: dict[str, Any], file_name: str, identifier: str) -> None:
    """Verify that removed fields (keywords, synonyms) are not present."""
    if "keywords" in entry_dict:
        raise ValueError(
            f"Forbidden field 'keywords' found in entry '{identifier}' ({file_name}). "
            f"Keywords have been permanently removed in favor of multilingual semantic retrieval."
        )
    if "synonyms" in entry_dict:
        raise ValueError(
            f"Forbidden field 'synonyms' found in entry '{identifier}' ({file_name}). "
            f"Synonyms have been permanently removed in favor of multilingual semantic retrieval."
        )


def save_yaml_catalog(
    catalog: ApiCatalog,
    catalog_path: Optional[str | Path] = None,
) -> Path:
    """Save the API catalog back to YAML manifest and domain files."""
    path = Path(catalog_path) if catalog_path else _get_default_catalog_path()
    catalog_dir = path.parent
    catalog_dir.mkdir(parents=True, exist_ok=True)

    domains_dir = catalog_dir / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)

    # Group APIs by domain
    domain_groups: dict[str, list[dict[str, Any]]] = {}
    for entry in catalog.apis:
        d = entry.domain or "default"
        if d not in domain_groups:
            domain_groups[d] = []
        entry_dict = entry.model_dump(mode="python", exclude_none=True)
        domain_groups[d].append(entry_dict)

    domain_file_refs = []
    for domain_name, apis in sorted(domain_groups.items()):
        rel_file = f"domains/{domain_name}.yaml"
        full_path = catalog_dir / rel_file
        domain_content = {
            "domain": domain_name,
            "apis": apis,
        }
        with open(full_path, "w", encoding="utf-8") as f:
            yaml.dump(
                domain_content,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )
        domain_file_refs.append(rel_file)

    manifest_data = {
        "catalog_version": catalog.catalog_version,
        "domain_files": domain_file_refs,
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            manifest_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )

    return path
