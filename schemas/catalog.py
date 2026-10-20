"""Pydantic models for the YAML API catalog.

Defines the structure of catalog entries including business metadata,
dependency declarations, and exposure/approval status.
The composite key (endpoint_name, method) uniquely identifies each API.

Keywords and synonyms have been removed; abbreviations are retained.
Strict validation is enforced on method, access_mode, approval_status,
and enabled states.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_ALLOWED_APPROVAL_STATUSES = frozenset({"pending_review", "approved", "rejected"})
_ALLOWED_ACCESS_MODES = frozenset({"read_only", "read_write"})


class DependentApi(BaseModel):
    """A dependency reference to another catalog API."""
    endpoint_name: str
    method: str
    purpose: Optional[str] = None
    output_to_input: Optional[dict[str, str]] = None

    @field_validator("method")
    @classmethod
    def _normalize_method(cls, v: str) -> str:
        v_upper = v.strip().upper()
        if v_upper not in _ALLOWED_METHODS:
            raise ValueError(f"method must be one of {sorted(_ALLOWED_METHODS)}, got: '{v}'")
        return v_upper


class CatalogEntry(BaseModel):
    """A single API entry in the YAML catalog.

    The composite key (endpoint_name, method) is the unique API identity.
    No generated api_id, UUID, or numeric identifier is used.
    """
    endpoint_name: str
    method: str
    path: str
    display_name: str
    description: str
    enabled: bool = False
    approval_status: str = "pending_review"
    access_mode: str = "read_only"
    dependent_apis: list[DependentApi] = Field(default_factory=list)

    operation_id: Optional[str] = None
    domain: Optional[str] = None

    use_when: Optional[list[str]] = None
    avoid_when: Optional[list[str]] = None
    abbreviations: Optional[list[str]] = None

    input_descriptions: Optional[dict[str, str]] = None
    parameter_mappings: Optional[dict[str, str]] = None
    output_description: Optional[str] = None
    response_field_descriptions: Optional[dict[str, str]] = None

    @field_validator("method")
    @classmethod
    def _validate_method(cls, v: str) -> str:
        v_upper = v.strip().upper()
        if v_upper not in _ALLOWED_METHODS:
            raise ValueError(f"method must be one of {sorted(_ALLOWED_METHODS)}, got: '{v}'")
        return v_upper

    @field_validator("approval_status")
    @classmethod
    def _validate_approval(cls, v: str) -> str:
        if v not in _ALLOWED_APPROVAL_STATUSES:
            raise ValueError(f"approval_status must be one of {sorted(_ALLOWED_APPROVAL_STATUSES)}, got: '{v}'")
        return v

    @field_validator("access_mode")
    @classmethod
    def _validate_access_mode(cls, v: str) -> str:
        if v not in _ALLOWED_ACCESS_MODES:
            raise ValueError(f"access_mode must be one of {sorted(_ALLOWED_ACCESS_MODES)}, got: '{v}'")
        return v

    @field_validator("enabled", mode="before")
    @classmethod
    def _validate_enabled_type(cls, v: Any) -> bool:
        if not isinstance(v, bool):
            raise ValueError(f"enabled must be a strict boolean (true/false), got: {type(v).__name__} ({v})")
        return v

    @model_validator(mode="after")
    def _validate_approval_and_enabled_combination(self) -> "CatalogEntry":
        # enabled: true is ONLY permitted when approval_status is "approved"
        if self.enabled and self.approval_status != "approved":
            raise ValueError(
                f"Invalid field combination for endpoint '{self.endpoint_name}' ({self.method}): "
                f"enabled=true is only allowed when approval_status='approved'. "
                f"Current approval_status='{self.approval_status}'."
            )
        return self

    @property
    def composite_key(self) -> tuple[str, str]:
        """Return the unique (endpoint_name, METHOD) identity."""
        return (self.endpoint_name, self.method.upper())

    @property
    def is_searchable(self) -> bool:
        """Whether this API is eligible for semantic search retrieval.

        Must be approved, enabled, read_only, and method GET.
        """
        return (
            self.enabled
            and self.approval_status == "approved"
            and self.access_mode == "read_only"
            and self.method == "GET"
        )

    @property
    def is_executable(self) -> bool:
        """Whether this API can be executed (enabled and approved)."""
        return self.enabled and self.approval_status == "approved"


class DomainCatalogFile(BaseModel):
    """Schema for a single domain-specific YAML catalog file."""
    domain: str
    apis: list[CatalogEntry] = Field(default_factory=list)


class CatalogManifest(BaseModel):
    """Schema for root api_catalog.yaml manifest listing domain files."""
    catalog_version: str = "1.0"
    domain_files: list[str] = Field(default_factory=list)


class ApiCatalog(BaseModel):
    """Logical root model representing the combined validated catalog."""
    catalog_version: str = "1.0"
    domain_files: Optional[list[str]] = None
    apis: list[CatalogEntry] = Field(default_factory=list)
