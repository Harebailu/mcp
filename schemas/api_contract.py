"""Models for resolved OpenAPI technical contracts.

These models represent the technical details extracted from the OpenAPI
specification: parameters, request bodies, response schemas, and
resolved component references.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ParameterSchema(BaseModel):
    """Resolved parameter from the OpenAPI specification."""
    name: str
    location: str  # "path", "query", "header", "cookie"
    required: bool = False
    schema_type: Optional[str] = None
    schema_format: Optional[str] = None
    description: Optional[str] = None
    default: Optional[Any] = None
    enum: Optional[list[Any]] = None
    nullable: bool = False
    full_schema: Optional[dict[str, Any]] = None


class RequestBodySchema(BaseModel):
    """Resolved request body from the OpenAPI specification."""
    required: bool = False
    content_types: list[str] = Field(default_factory=list)
    schema_definition: Optional[dict[str, Any]] = None
    description: Optional[str] = None


class ResponseSchema(BaseModel):
    """A single response status code and its schema."""
    status_code: str
    description: Optional[str] = None
    content_types: list[str] = Field(default_factory=list)
    schema_definition: Optional[dict[str, Any]] = None


class ResolvedOperation(BaseModel):
    """A fully resolved OpenAPI operation with dereferenced schemas."""
    path: str
    method: str
    operation_id: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    parameters: list[ParameterSchema] = Field(default_factory=list)
    request_body: Optional[RequestBodySchema] = None
    responses: list[ResponseSchema] = Field(default_factory=list)
    deprecated: bool = False

    @property
    def path_parameters(self) -> list[ParameterSchema]:
        return [p for p in self.parameters if p.location == "path"]

    @property
    def query_parameters(self) -> list[ParameterSchema]:
        return [p for p in self.parameters if p.location == "query"]

    @property
    def required_parameters(self) -> list[ParameterSchema]:
        return [p for p in self.parameters if p.required]
