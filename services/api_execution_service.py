"""API execution service with server-side validation and policy enforcement.

Responsible for:
- Resolving endpoint_name/method against the validated registry.
- Rejecting unknown, disabled, or unapproved operations.
- Enforcing the server-side read-only policy.
- Validating arguments against the OpenAPI contract.
- Checking required inputs, types, formats, enums.
- Rejecting unexpected argument keys.
- Constructing URLs from trusted base URL and catalog path.
- Delegating HTTP execution to the API client adapter.
- Returning structured results.

Security:
- The agent never supplies the URL, base URL, or arbitrary headers.
- The inbound MCP token is never forwarded downstream.
- Each execution goes through the same validation pipeline.
"""

from __future__ import annotations

from typing import Any, Optional

from adapters.api_client import ApiClient
from catalog.registry import ApiRegistry
from policies.read_only import enforce_read_only_policy
from schemas.api_contract import ResolvedOperation
from schemas.catalog import CatalogEntry
from schemas.tool_results import ExecuteApiResult
from schemas.errors import ErrorCode, McpToolError


class ApiExecutionService:
    """Validates and executes approved API operations."""

    def __init__(
        self,
        registry: ApiRegistry,
        api_client: ApiClient,
    ) -> None:
        self._registry = registry
        self._api_client = api_client

    async def execute(
        self,
        endpoint_name: str,
        method: str,
        path_params: Optional[dict[str, Any]] = None,
        query_params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
    ) -> ExecuteApiResult:
        """Execute a single approved API operation.

        Args:
            endpoint_name: The catalog endpoint name.
            method: The HTTP method.
            path_params: Path parameter values.
            query_params: Query parameter values.
            body: Request body (if permitted).

        Returns:
            ExecuteApiResult with the operation outcome.

        Raises:
            McpToolError: For validation or execution failures.
        """
        method = method.upper()

        # 1. Resolve against validated registry
        entry = self._registry.get_entry(endpoint_name, method)

        # 2. Enforce read-only policy (checks enabled, approved, method, access_mode)
        enforce_read_only_policy(entry)

        # 3. Get OpenAPI operation for validation
        operation = self._registry.get_operation(endpoint_name, method)

        # 4. Validate arguments against OpenAPI contract
        self._validate_arguments(entry, operation, path_params, query_params, body)

        # 5. Build URL from trusted path
        resolved_path = self._api_client.build_url(entry.path, path_params)

        # 6. Execute request
        response = await self._api_client.execute_request(
            method=method,
            path=resolved_path,
            query_params=query_params,
            body=body,
        )

        # 7. Return structured result
        return ExecuteApiResult(
            endpoint_name=endpoint_name,
            method=method,
            path=entry.path,
            status_code=response.status_code,
            success=response.success,
            data=response.data,
            headers=response.headers,
            error=response.error,
            truncated=response.truncated,
            empty_response=response.empty_response,
        )

    def _validate_arguments(
        self,
        entry: CatalogEntry,
        operation: Optional[ResolvedOperation],
        path_params: Optional[dict[str, Any]],
        query_params: Optional[dict[str, Any]],
        body: Optional[dict[str, Any]],
    ) -> None:
        """Validate arguments against the API contract."""
        if not operation:
            # No OpenAPI contract available - allow execution with minimal validation
            return

        # Check body permission
        if body is not None and entry.method.upper() in ("GET", "HEAD", "OPTIONS"):
            if operation.request_body is None:
                raise McpToolError.from_code(
                    ErrorCode.BODY_NOT_PERMITTED,
                    f"Request body is not permitted for {entry.method} "
                    f"{entry.endpoint_name}.",
                )

        # Validate path parameters
        self._validate_path_params(operation, path_params)

        # Validate query parameters
        self._validate_query_params(operation, query_params)

        # Validate request body
        if body is not None and operation.request_body:
            self._validate_body(operation, body)

    def _validate_path_params(
        self,
        operation: ResolvedOperation,
        path_params: Optional[dict[str, Any]],
    ) -> None:
        """Validate path parameters against the OpenAPI contract."""
        required_path_params = [
            p for p in operation.parameters
            if p.location == "path" and p.required
        ]

        if not required_path_params:
            return

        provided = path_params or {}

        for param in required_path_params:
            if param.name not in provided:
                raise McpToolError.from_code(
                    ErrorCode.MISSING_REQUIRED_ARGUMENT,
                    f"Missing required path parameter: '{param.name}'.",
                    details={
                        "parameter": param.name,
                        "location": "path",
                        "type": param.schema_type,
                    },
                )

        # Check for unexpected path params
        expected_names = {p.name for p in operation.parameters if p.location == "path"}
        for key in provided:
            if key not in expected_names:
                raise McpToolError.from_code(
                    ErrorCode.UNEXPECTED_ARGUMENT,
                    f"Unexpected path parameter: '{key}'. "
                    f"Expected: {sorted(expected_names)}.",
                    details={"unexpected": key, "expected": sorted(expected_names)},
                )

        # Type validation for path params
        for param in operation.parameters:
            if param.location == "path" and param.name in provided:
                self._validate_param_type(param.name, provided[param.name], param)

    def _validate_query_params(
        self,
        operation: ResolvedOperation,
        query_params: Optional[dict[str, Any]],
    ) -> None:
        """Validate query parameters against the OpenAPI contract."""
        required_query_params = [
            p for p in operation.parameters
            if p.location == "query" and p.required
        ]

        provided = query_params or {}

        for param in required_query_params:
            if param.name not in provided:
                raise McpToolError.from_code(
                    ErrorCode.MISSING_REQUIRED_ARGUMENT,
                    f"Missing required query parameter: '{param.name}'.",
                    details={
                        "parameter": param.name,
                        "location": "query",
                        "type": param.schema_type,
                    },
                )

        # Check for unexpected query params
        expected_names = {p.name for p in operation.parameters if p.location == "query"}
        for key in provided:
            if key not in expected_names:
                raise McpToolError.from_code(
                    ErrorCode.UNEXPECTED_ARGUMENT,
                    f"Unexpected query parameter: '{key}'. "
                    f"Expected: {sorted(expected_names)}.",
                    details={"unexpected": key, "expected": sorted(expected_names)},
                )

        # Type validation for query params
        for param in operation.parameters:
            if param.location == "query" and param.name in provided:
                self._validate_param_type(param.name, provided[param.name], param)

    def _validate_param_type(
        self, name: str, value: Any, param: Any
    ) -> None:
        """Basic type validation for a parameter value."""
        if value is None and not param.nullable:
            raise McpToolError.from_code(
                ErrorCode.INVALID_ARGUMENTS,
                f"Parameter '{name}' cannot be null.",
            )

        if value is None:
            return

        # Enum validation
        if param.enum and value not in param.enum:
            raise McpToolError.from_code(
                ErrorCode.INVALID_ARGUMENTS,
                f"Parameter '{name}' must be one of {param.enum}, got: {value}",
                details={"parameter": name, "enum": param.enum, "value": value},
            )

        # Basic type checking
        if param.schema_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                try:
                    int(value)
                except (ValueError, TypeError):
                    raise McpToolError.from_code(
                        ErrorCode.INVALID_ARGUMENTS,
                        f"Parameter '{name}' must be an integer, got: {type(value).__name__}",
                    )
        elif param.schema_type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                try:
                    float(value)
                except (ValueError, TypeError):
                    raise McpToolError.from_code(
                        ErrorCode.INVALID_ARGUMENTS,
                        f"Parameter '{name}' must be a number, got: {type(value).__name__}",
                    )
        elif param.schema_type == "boolean":
            if not isinstance(value, bool):
                if str(value).lower() not in ("true", "false", "0", "1"):
                    raise McpToolError.from_code(
                        ErrorCode.INVALID_ARGUMENTS,
                        f"Parameter '{name}' must be a boolean, got: {type(value).__name__}",
                    )

    def _validate_body(
        self,
        operation: ResolvedOperation,
        body: dict[str, Any],
    ) -> None:
        """Basic request body validation."""
        if not operation.request_body:
            return

        rb = operation.request_body
        if not rb.schema_definition:
            return

        schema = rb.schema_definition

        # Check required properties
        required_props = schema.get("required", [])
        for prop in required_props:
            if prop not in body:
                raise McpToolError.from_code(
                    ErrorCode.MISSING_REQUIRED_ARGUMENT,
                    f"Missing required body property: '{prop}'.",
                    details={"property": prop, "location": "body"},
                )

        # Check for unexpected properties (if additionalProperties is false)
        if schema.get("additionalProperties") is False:
            allowed_props = set(schema.get("properties", {}).keys())
            for key in body:
                if key not in allowed_props:
                    raise McpToolError.from_code(
                        ErrorCode.UNEXPECTED_ARGUMENT,
                        f"Unexpected body property: '{key}'. "
                        f"Allowed: {sorted(allowed_props)}.",
                        details={"unexpected": key, "allowed": sorted(allowed_props)},
                    )

