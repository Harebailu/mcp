"""Reusable asynchronous HTTP client for the downstream API.

Responsibilities:
- Managed HTTP client lifecycle (reuse, not per-request creation).
- Configured API base URL from trusted configuration.
- Safe URL and query construction from trusted catalog paths.
- HTTP request execution with timeout enforcement.
- Response-size limits.
- Redirect restrictions.
- Response parsing and status handling.
- Resource cleanup during shutdown.

Security:
- The base URL comes from configuration, not from the agent.
- Endpoint paths come from the validated YAML catalog, not from agent input.
- Inbound MCP JWT credentials are never forwarded to the downstream API.
- Only server-controlled, explicitly permitted headers are sent.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

from schemas.errors import ErrorCode, McpToolError


class ApiClient:
    """Asynchronous HTTP client for calling the downstream API."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 30,
        max_response_bytes: int = 1_048_576,
        max_redirects: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._max_response_bytes = max_response_bytes
        self._max_redirects = max_redirects
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        """Initialize the HTTP client. Call once at application startup."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                follow_redirects=True,
                max_redirects=self._max_redirects,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "mcp_server/0.1.0",
                },
            )

    async def close(self) -> None:
        """Close the HTTP client. Call during shutdown."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure the client is initialized."""
        if self._client is None or self._client.is_closed:
            raise McpToolError.from_code(
                ErrorCode.INVALID_CONFIGURATION,
                "HTTP client is not initialized. Call start() first.",
            )
        return self._client

    def build_url(
        self,
        path_template: str,
        path_params: Optional[dict[str, Any]] = None,
    ) -> str:
        """Construct a safe URL from the trusted catalog path and parameters.

        The path comes from the validated YAML catalog (trusted),
        and path parameter values come from the agent (validated).

        Args:
            path_template: The URL path template from YAML (e.g., /api/projects/{projectId}).
            path_params: Values for path parameters.

        Returns:
            The resolved URL path.
        """
        resolved_path = path_template

        if path_params:
            for param_name, param_value in path_params.items():
                placeholder = "{" + param_name + "}"
                if placeholder in resolved_path:
                    # URL-encode the parameter value
                    encoded_value = quote(str(param_value), safe="")
                    resolved_path = resolved_path.replace(placeholder, encoded_value)

        # Check for unresolved placeholders
        import re
        remaining = re.findall(r"\{([^}]+)\}", resolved_path)
        if remaining:
            raise McpToolError.from_code(
                ErrorCode.MISSING_REQUIRED_ARGUMENT,
                f"Unresolved path parameters: {remaining}. "
                f"Provide values for all path parameters.",
                details={"missing_params": remaining, "path": path_template},
            )

        return resolved_path

    def build_query_string(
        self, query_params: Optional[dict[str, Any]] = None
    ) -> Optional[str]:
        """Build a safely encoded query string."""
        if not query_params:
            return None

        # Filter out None values
        filtered = {
            k: v for k, v in query_params.items() if v is not None
        }
        if not filtered:
            return None

        # Convert booleans to lowercase strings for API compatibility
        encoded_params = {}
        for k, v in filtered.items():
            if isinstance(v, bool):
                encoded_params[k] = str(v).lower()
            elif isinstance(v, list):
                # Handle array parameters
                encoded_params[k] = ",".join(str(item) for item in v)
            else:
                encoded_params[k] = str(v)

        return urlencode(encoded_params, doseq=False)

    async def execute_request(
        self,
        method: str,
        path: str,
        query_params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        additional_headers: Optional[dict[str, str]] = None,
    ) -> ApiResponse:
        """Execute an HTTP request to the downstream API.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: Resolved URL path (already has path params substituted).
            query_params: Query parameters to include.
            body: Request body (JSON).
            additional_headers: Additional headers (server-controlled only).

        Returns:
            An ApiResponse with status, data, and metadata.
        """
        client = self._ensure_client()

        # Build query string
        query_string = self.build_query_string(query_params)
        url = path
        if query_string:
            url = f"{path}?{query_string}"

        # Prepare headers (server-controlled only)
        headers = {}
        if additional_headers:
            # Only allow explicitly permitted headers
            allowed_header_prefixes = ("x-request-", "x-correlation-")
            for k, v in additional_headers.items():
                k_lower = k.lower()
                if k_lower.startswith(allowed_header_prefixes) or k_lower == "content-type":
                    headers[k] = v

        # Prepare request kwargs
        kwargs: dict[str, Any] = {
            "method": method.upper(),
            "url": url,
            "headers": headers if headers else None,
        }

        if body is not None and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            kwargs["json"] = body

        try:
            response = await client.request(**kwargs)
        except httpx.TimeoutException as e:
            raise McpToolError.from_code(
                ErrorCode.TIMEOUT,
                f"Request to {method} {path} timed out.",
                details={"path": path, "method": method},
            ) from e
        except httpx.TooManyRedirects as e:
            raise McpToolError.from_code(
                ErrorCode.DOWNSTREAM_FAILURE,
                f"Too many redirects for {method} {path}.",
            ) from e
        except httpx.ConnectError as e:
            raise McpToolError.from_code(
                ErrorCode.DOWNSTREAM_FAILURE,
                f"Cannot connect to the downstream API for {method} {path}: {e}",
            ) from e
        except Exception as e:
            raise McpToolError.from_code(
                ErrorCode.DOWNSTREAM_FAILURE,
                f"HTTP request failed for {method} {path}: {type(e).__name__}",
            ) from e

        return await self._process_response(response, method, path)

    async def _process_response(
        self, response: httpx.Response, method: str, path: str
    ) -> ApiResponse:
        """Process the HTTP response with size limits and status handling."""
        status_code = response.status_code
        content_length = response.headers.get("content-length")
        truncated = False

        # Check response size
        if content_length and int(content_length) > self._max_response_bytes:
            truncated = True

        # Read response content
        raw_content = response.content
        if len(raw_content) > self._max_response_bytes:
            raw_content = raw_content[: self._max_response_bytes]
            truncated = True

        # Try to parse JSON
        data: Any = None
        empty_response = len(raw_content.strip()) == 0

        if not empty_response:
            content_type = response.headers.get("content-type", "")
            if "json" in content_type or "text" in content_type:
                try:
                    data = json.loads(raw_content)
                except json.JSONDecodeError:
                    # Return raw text
                    data = raw_content.decode("utf-8", errors="replace")
            else:
                data = raw_content.decode("utf-8", errors="replace")

        # Handle error status codes
        is_success = 200 <= status_code < 300
        error_message = None

        if not is_success:
            error_message = self._classify_error(status_code, data, method, path)

        # Extract safe response headers
        safe_headers = {
            k: v for k, v in response.headers.items()
            if k.lower() in (
                "content-type", "content-length", "x-request-id",
                "x-correlation-id", "date", "cache-control",
            )
        }

        return ApiResponse(
            status_code=status_code,
            success=is_success,
            data=data,
            headers=safe_headers if safe_headers else None,
            error=error_message,
            truncated=truncated,
            empty_response=empty_response,
        )

    def _classify_error(
        self, status_code: int, data: Any, method: str, path: str
    ) -> str:
        """Classify an HTTP error status into a safe message."""
        detail = ""
        if isinstance(data, dict):
            detail = data.get("message", data.get("title", data.get("error", "")))
        elif isinstance(data, str) and len(data) < 500:
            detail = data

        if status_code == 400:
            return f"Upstream validation error for {method} {path}. {detail}".strip()
        elif status_code == 401:
            return f"Authentication required by upstream API for {method} {path}."
        elif status_code == 403:
            return f"Access denied by upstream API for {method} {path}."
        elif status_code == 404:
            return f"Resource not found at {method} {path}. {detail}".strip()
        elif status_code == 429:
            return f"Rate limited by upstream API for {method} {path}."
        elif status_code >= 500:
            return f"Upstream server error ({status_code}) for {method} {path}."
        else:
            return f"Upstream returned HTTP {status_code} for {method} {path}. {detail}".strip()


class ApiResponse:
    """Structured representation of an API response."""

    def __init__(
        self,
        status_code: int,
        success: bool,
        data: Any = None,
        headers: Optional[dict[str, str]] = None,
        error: Optional[str] = None,
        truncated: bool = False,
        empty_response: bool = False,
    ) -> None:
        self.status_code = status_code
        self.success = success
        self.data = data
        self.headers = headers
        self.error = error
        self.truncated = truncated
        self.empty_response = empty_response




