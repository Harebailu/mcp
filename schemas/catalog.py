"""Pydantic models for the YAML API catalog.

Defines the structure of catalog entries including business metadata,
dependency declarations, and exposure/approval status.
The composite key (endpoint_name, method) uniquely identifies each API.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class DependentApi(BaseModel):
    """A dependency reference to another catalog API."""
    endpoint_name: str
    method: str
    purpose: Optional[str] = None
    output_to_input: Optional[dict[str, str]] = None

    @field_validator("method")
    @classmethod
    def _normalize_method(cls, v: str) -> str:
        return v.strip().upper()


class CatalogEntry(BaseModel):
    """A single API entry in the YAML catalog.

    The composite key (endpoint_name, method) is the unique API identity.
    No generated api_id, UUID, or numeric identifier is used.
    """
    endpoint_name: str
    method: str
    path: str
    operation_id: Optional[str] = None
    domain: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None

    use_when: Optional[list[str]] = None
    avoid_when: Optional[list[str]] = None

    keywords: Optional[list[str]] = None
    synonyms: Optional[list[str]] = None
    abbreviations: Optional[list[str]] = None

    input_descriptions: Optional[dict[str, str]] = None
    parameter_mappings: Optional[dict[str, str]] = None
    output_description: Optional[str] = None
    response_field_descriptions: Optional[dict[str, str]] = None

    dependent_apis: Optional[list[DependentApi]] = None

    enabled: bool = False
    approval_status: str = "pending_review"
    access_mode: str = "read_only"

    @field_validator("method")
    @classmethod
    def _normalize_method(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("approval_status")
    @classmethod
    def _validate_approval(cls, v: str) -> str:
        allowed = {"approved", "pending_review", "rejected", "deprecated"}
        if v not in allowed:
            raise ValueError(f"approval_status must be one of {allowed}, got: {v}")
        return v

    @field_validator("access_mode")
    @classmethod
    def _validate_access_mode(cls, v: str) -> str:
        allowed = {"read_only", "read_write", "restricted"}
        if v not in allowed:
            raise ValueError(f"access_mode must be one of {allowed}, got: {v}")
        return v

    @property
    def composite_key(self) -> tuple[str, str]:
        """Return the unique (endpoint_name, METHOD) identity."""
        return (self.endpoint_name, self.method.upper())

    @property
    def is_executable(self) -> bool:
        """Whether this API can be executed (enabled and approved)."""
        return self.enabled and self.approval_status == "approved"


class ApiCatalog(BaseModel):
    """Root model for the YAML API catalog file."""
    catalog_version: str = "1.0"
    apis: list[CatalogEntry] = Field(default_factory=list)
