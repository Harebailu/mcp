"""Load and validate the YAML API catalog.

The initial implementation loads a single catalog file:
    catalog/api_catalog.yaml

The loader is isolated from tool and service implementations so that
changing from one YAML file to multiple domain-specific files does not
require rewriting MCP tools, API execution logic, or search interfaces.

Future extension:
    catalog/
    +-- api_catalog.yaml
    +-- domains/
        +-- projects.yaml
        +-- jobs.yaml
        +-- other-domain.yaml

A future multi-file loader would merge entries into one logical ApiCatalog
and preserve the same composite API identity (endpoint_name, method).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from schemas.catalog import ApiCatalog, CatalogEntry


def _get_default_catalog_path() -> Path:
    """Return the default catalog file path."""
    return Path(__file__).resolve().parent / "api_catalog.yaml"


def load_yaml_catalog(catalog_path: Optional[str | Path] = None) -> ApiCatalog:
    """Load and validate the YAML API catalog.

    Args:
        catalog_path: Path to the catalog YAML file.
                     Defaults to catalog/api_catalog.yaml.

    Returns:
        A validated ApiCatalog instance.

    Raises:
        FileNotFoundError: If the catalog file does not exist.
        ValueError: If the YAML structure is invalid.
        ValidationError: If entries fail Pydantic validation.
    """
    path = Path(catalog_path) if catalog_path else _get_default_catalog_path()

    if not path.exists():
        raise FileNotFoundError(
            f"API catalog file not found: {path}. "
            f"Create catalog/api_catalog.yaml or run catalog synchronization."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        # Empty file - return empty catalog
        return ApiCatalog()

    if not isinstance(raw, dict):
        raise ValueError(
            f"API catalog must be a YAML mapping, got: {type(raw).__name__}"
        )

    return ApiCatalog.model_validate(raw)


def save_yaml_catalog(
    catalog: ApiCatalog,
    catalog_path: Optional[str | Path] = None,
) -> Path:
    """Save the API catalog back to YAML.

    Args:
        catalog: The catalog to save.
        catalog_path: Target path. Defaults to catalog/api_catalog.yaml.

    Returns:
        The path where the catalog was saved.
    """
    path = Path(catalog_path) if catalog_path else _get_default_catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = catalog.model_dump(mode="python", exclude_none=True)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )

    return path
