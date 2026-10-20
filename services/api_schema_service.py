"""API schema service combining YAML business metadata with OpenAPI contracts.

Responsible for:
- Retrieving the detailed business and technical contract for one API.
- Combining OpenAPI technical information with YAML business descriptions.
- Not inventing constraints or overriding the actual technical contract.
- Rejecting unknown, ambiguous, or invalid endpoint-name/method combinations.
"""

from __future__ import annotations

from typing import Any, Optional

from catalog.registry import ApiRegistry
from services.dependency_service import DependencyService
from schemas.api_contract import ResolvedOperation
from schemas.catalog import CatalogEntry
from schemas.tool_results import ApiSchemaResult
from schemas.errors import ErrorCode, McpToolError


class ApiSchemaService:
    """Retrieves combined business and technical API schemas."""

    def __init__(
        self,
        registry: ApiRegistry,
        dependency_service: DependencyService,
    ) -> None:
        self._registry = registry
        self._dependency_service = dependency_service

    def get_schema(
        self,
        endpoint_name: str,
        method: str,
    ) -> ApiSchemaResult:
        """Get the combined schema for an API.

        Args:
            endpoint_name: The API endpoint name.
            method: The HTTP method.

        Returns:
            ApiSchemaResult with business and technical details.

        Raises:
            McpToolError: If the endpoint is unknown or ambiguous.
        """
        # Look up catalog entry (raises if not found)
        entry = self._registry.get_entry(endpoint_name, method)

        # Look up OpenAPI operation
        operation = self._registry.get_operation(endpoint_name, method)

        # Build parameters from OpenAPI
        parameters = None
        if operation and operation.parameters:
            parameters = [
                self._format_parameter(p) for p in operation.parameters
            ]

        # Build request body from OpenAPI
        request_body = None
        if operation and operation.request_body:
            rb = operation.request_body
            request_body = {
                "required": rb.required,
                "content_types": rb.content_types,
            }
            if rb.schema_definition:
                request_body["schema"] = rb.schema_definition
            if rb.description:
                request_body["description"] = rb.description

        # Build responses from OpenAPI
        responses = None
        if operation and operation.responses:
            responses = [
                self._format_response(r) for r in operation.responses
            ]

        # Build dependency info
        dependent_apis = self._dependency_service.format_dependencies_for_schema(entry)

        return ApiSchemaResult(
            endpoint_name=entry.endpoint_name,
            method=entry.method,
            path=entry.path,
            display_name=entry.display_name,
            domain=entry.domain,
            description=entry.description,
            use_when=entry.use_when,
            avoid_when=entry.avoid_when,
            parameters=parameters,
            request_body=request_body,
            responses=responses,
            input_descriptions=entry.input_descriptions,
            parameter_mappings=entry.parameter_mappings,
            output_description=entry.output_description,
            response_field_descriptions=entry.response_field_descriptions,
            dependent_apis=dependent_apis,
            enabled=entry.enabled,
            approval_status=entry.approval_status,
            access_mode=entry.access_mode,
        )

    def _format_parameter(self, param: Any) -> dict[str, Any]:
        """Format a parameter for the schema result."""
        result: dict[str, Any] = {
            "name": param.name,
            "location": param.location,
            "required": param.required,
        }
        if param.schema_type:
            result["type"] = param.schema_type
        if param.schema_format:
            result["format"] = param.schema_format
        if param.description:
            result["description"] = param.description
        if param.default is not None:
            result["default"] = param.default
        if param.enum:
            result["enum"] = param.enum
        if param.nullable:
            result["nullable"] = True
        if param.full_schema:
            result["schema"] = param.full_schema
        return result

    def _format_response(self, resp: Any) -> dict[str, Any]:
        """Format a response for the schema result."""
        result: dict[str, Any] = {
            "status_code": resp.status_code,
        }
        if resp.description:
            result["description"] = resp.description
        if resp.content_types:
            result["content_types"] = resp.content_types
        if resp.schema_definition:
            result["schema"] = resp.schema_definition
        return result

