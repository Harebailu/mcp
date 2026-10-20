"""Pydantic models for MCP tool output/result structures.

These define the structured responses returned by the four MCP tools.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SearchResultEntry(BaseModel):
    """A single search result candidate."""
    endpoint_name: str
    method: str
    path: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    domain: Optional[str] = None
    use_when: Optional[list[str]] = None
    avoid_when: Optional[list[str]] = None
    input_summary: Optional[dict[str, str]] = None
    output_summary: Optional[str] = None
    has_dependencies: bool = False
    dependency_summary: Optional[list[str]] = None
    enabled: bool = False
    approval_status: str = "pending_review"
    relevance_score: float = 0.0


class SearchApisResult(BaseModel):
    """Result from search_apis tool."""
    query: str
    total_matches: int = 0
    results: list[SearchResultEntry] = Field(default_factory=list)
    search_backend: str = "yaml_keyword"
    message: Optional[str] = None


class ApiSchemaResult(BaseModel):
    """Result from get_api_schema tool."""
    endpoint_name: str
    method: str
    path: str
    display_name: Optional[str] = None
    domain: Optional[str] = None
    description: Optional[str] = None
    use_when: Optional[list[str]] = None
    avoid_when: Optional[list[str]] = None
    parameters: Optional[list[dict[str, Any]]] = None
    request_body: Optional[dict[str, Any]] = None
    responses: Optional[list[dict[str, Any]]] = None
    input_descriptions: Optional[dict[str, str]] = None
    parameter_mappings: Optional[dict[str, str]] = None
    output_description: Optional[str] = None
    response_field_descriptions: Optional[dict[str, str]] = None
    dependent_apis: Optional[list[dict[str, Any]]] = None
    enabled: bool = False
    approval_status: str = "pending_review"
    access_mode: str = "read_only"


class ExecuteApiResult(BaseModel):
    """Result from execute_api tool."""
    endpoint_name: str
    method: str
    path: str
    status_code: int
    success: bool
    data: Optional[Any] = None
    headers: Optional[dict[str, str]] = None
    error: Optional[str] = None
    truncated: bool = False
    empty_response: bool = False


class CatalogListEntry(BaseModel):
    """A single entry in the list_all_apis response."""
    endpoint_name: str
    method: str
    path: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    domain: Optional[str] = None
    enabled: bool = False
    approval_status: str = "pending_review"
    access_mode: str = "read_only"
    has_dependencies: bool = False
    dependency_summary: Optional[list[str]] = None


class ListAllApisResult(BaseModel):
    """Result from list_all_apis tool."""
    total_count: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0
    has_more: bool = False
    entries: list[CatalogListEntry] = Field(default_factory=list)
    message: Optional[str] = None
