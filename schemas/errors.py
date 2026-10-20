"""Machine-readable error codes and structured error models.

Provides consistent error codes across all MCP tools without
revealing tokens, secrets, or internal tracebacks.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Machine-readable error codes for MCP tool responses."""
    # Configuration
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"

    # Catalog / OpenAPI
    CATALOG_VALIDATION_ERROR = "CATALOG_VALIDATION_ERROR"
    OPENAPI_VALIDATION_ERROR = "OPENAPI_VALIDATION_ERROR"
    OPENAPI_UNREACHABLE = "OPENAPI_UNREACHABLE"

    # API identity
    UNKNOWN_ENDPOINT = "UNKNOWN_ENDPOINT"
    AMBIGUOUS_ENDPOINT = "AMBIGUOUS_ENDPOINT"
    DISABLED_ENDPOINT = "DISABLED_ENDPOINT"
    UNAPPROVED_ENDPOINT = "UNAPPROVED_ENDPOINT"

    # Execution
    READ_ONLY_VIOLATION = "READ_ONLY_VIOLATION"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    MISSING_REQUIRED_ARGUMENT = "MISSING_REQUIRED_ARGUMENT"
    UNEXPECTED_ARGUMENT = "UNEXPECTED_ARGUMENT"
    BODY_NOT_PERMITTED = "BODY_NOT_PERMITTED"

    # Authentication
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_MISSING = "TOKEN_MISSING"
    TOKEN_MALFORMED = "TOKEN_MALFORMED"
    TOKEN_UNPARSEABLE = "TOKEN_UNPARSEABLE"
    MISSING_DOWNSTREAM_CREDENTIALS = "MISSING_DOWNSTREAM_CREDENTIALS"

    # Upstream / downstream
    UPSTREAM_VALIDATION_ERROR = "UPSTREAM_VALIDATION_ERROR"
    UPSTREAM_NOT_FOUND = "UPSTREAM_NOT_FOUND"
    UPSTREAM_AUTH_FAILURE = "UPSTREAM_AUTH_FAILURE"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    DOWNSTREAM_FAILURE = "DOWNSTREAM_FAILURE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    RESPONSE_TRUNCATED = "RESPONSE_TRUNCATED"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"

    # Search
    SEARCH_BACKEND_ERROR = "SEARCH_BACKEND_ERROR"
    UNSUPPORTED_SEARCH_BACKEND = "UNSUPPORTED_SEARCH_BACKEND"

    # Dependency
    DEPENDENCY_NOT_FOUND = "DEPENDENCY_NOT_FOUND"
    CYCLIC_DEPENDENCY = "CYCLIC_DEPENDENCY"

    # General
    INTERNAL_ERROR = "INTERNAL_ERROR"


class McpError(BaseModel):
    """Structured error response for MCP tool results."""
    code: ErrorCode
    message: str
    details: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "error": True,
            "code": self.code.value,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


class McpToolError(Exception):
    """Exception wrapping a structured MCP error."""

    def __init__(self, error: McpError) -> None:
        self.error = error
        super().__init__(error.message)

    @classmethod
    def from_code(
        cls,
        code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ) -> "McpToolError":
        return cls(McpError(code=code, message=message, details=details))
