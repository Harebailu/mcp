"""Pydantic models for MCP tool input arguments.

These define the generic input schemas for the four MCP tools.
The execute_api tool uses a single generic schema rather than
a unique schema per endpoint.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class SearchApisArgs(BaseModel):
    """Input arguments for the search_apis tool."""
    query: str = Field(..., description="Natural-language search query for API discovery")
    domain: Optional[str] = Field(default=None, description="Optional domain/category filter")
    limit: Optional[int] = Field(default=None, ge=1, le=20, description="Maximum number of results to return")


class GetApiSchemaArgs(BaseModel):
    """Input arguments for the get_api_schema tool."""
    endpoint_name: str = Field(..., description="The endpoint name from the API catalog")
    method: str = Field(..., description="HTTP method (e.g., GET, POST)")

    @field_validator("method")
    @classmethod
    def _normalize_method(cls, v: str) -> str:
        return v.strip().upper()


class ExecuteApiArgs(BaseModel):
    """Input arguments for the execute_api tool.

    This is a single generic schema for all API executions.
    The endpoint_name/method pair identifies which API to call.
    Argument validation against the specific API contract is
    performed server-side at runtime.
    """
    endpoint_name: str = Field(..., description="The endpoint name from the API catalog")
    method: str = Field(..., description="HTTP method (e.g., GET)")
    path_params: Optional[dict[str, Any]] = Field(default=None, description="Path parameter values")
    query_params: Optional[dict[str, Any]] = Field(default=None, description="Query parameter values")
    body: Optional[dict[str, Any]] = Field(default=None, description="Request body (only if permitted by the API contract)")

    @field_validator("method")
    @classmethod
    def _normalize_method(cls, v: str) -> str:
        return v.strip().upper()


class ListAllApisArgs(BaseModel):
    """Input arguments for the list_all_apis tool."""
    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    page_size: int = Field(default=20, ge=1, le=50, description="Number of entries per page")
    domain: Optional[str] = Field(default=None, description="Optional domain filter")
