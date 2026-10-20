"""Discover, load, and parse the OpenAPI JSON specification.

Responsible for:
- Discovering the actual OpenAPI JSON URL from the configured Swagger UI.
- Retrieving and caching the OpenAPI specification.
- Resolving $ref references within the specification.
- Extracting operation details: paths, methods, parameters, bodies, responses.
- Providing resolved technical contracts for registry use.

The Swagger UI URL and OpenAPI spec URL are distinct configuration concepts.
If openapi_spec_url is explicitly configured, it is used directly.
Otherwise, the spec URL is discovered from the Swagger UI page.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

from schemas.api_contract import (
    ParameterSchema,
    RequestBodySchema,
    ResolvedOperation,
    ResponseSchema,
)
from schemas.errors import ErrorCode, McpToolError


class OpenApiLoader:
    """Loads, caches, and resolves an OpenAPI 3.x specification."""

    def __init__(self) -> None:
        self._spec: Optional[dict[str, Any]] = None
        self._spec_url: Optional[str] = None
        self._operations: dict[tuple[str, str], ResolvedOperation] = {}

    @property
    def spec(self) -> Optional[dict[str, Any]]:
        return self._spec

    @property
    def spec_url(self) -> Optional[str]:
        return self._spec_url

    @property
    def operations(self) -> dict[tuple[str, str], ResolvedOperation]:
        return dict(self._operations)

    async def discover_spec_url(
        self,
        swagger_ui_url: str,
        explicit_spec_url: Optional[str] = None,
        timeout: float = 15.0,
    ) -> str:
        """Discover the actual OpenAPI JSON URL.

        If explicit_spec_url is provided, use it directly.
        Otherwise, fetch the Swagger UI HTML and extract the spec URL
        from its JavaScript configuration.

        Args:
            swagger_ui_url: The Swagger UI page URL.
            explicit_spec_url: Optional explicit override.
            timeout: HTTP timeout in seconds.

        Returns:
            The verified OpenAPI spec URL.
        """
        if explicit_spec_url:
            self._spec_url = explicit_spec_url
            return explicit_spec_url

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(swagger_ui_url)
                response.raise_for_status()
                html = response.text
        except httpx.ConnectError as e:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_UNREACHABLE,
                f"Cannot reach Swagger UI at {swagger_ui_url}: {e}",
            ) from e
        except httpx.HTTPStatusError as e:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_UNREACHABLE,
                f"Swagger UI returned HTTP {e.response.status_code} at {swagger_ui_url}",
            ) from e
        except Exception as e:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_UNREACHABLE,
                f"Failed to fetch Swagger UI at {swagger_ui_url}: {e}",
            ) from e

        # Parse the Swagger UI config to find the spec URL
        spec_url = self._extract_spec_url_from_html(html, swagger_ui_url)

        if not spec_url:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_UNREACHABLE,
                "Could not discover the OpenAPI specification URL from the "
                f"Swagger UI at {swagger_ui_url}. Configure openapi_spec_url explicitly.",
            )

        self._spec_url = spec_url
        return spec_url

    def _extract_spec_url_from_html(self, html: str, base_url: str) -> Optional[str]:
        """Extract the OpenAPI spec URL from Swagger UI HTML.

        Swagger UI stores its configuration in a JSON.parse() call within
        the page's JavaScript. The 'urls' array or 'url' field contains
        the spec location.
        """
        # Try to find configObject JSON in the HTML
        # Pattern: JSON.parse('{...}')
        config_match = re.search(
            r"JSON\.parse\('(\{.*?\"urls\".*?\})(?:'|\\')\)",
            html,
            re.DOTALL,
        )

        if config_match:
            try:
                config_json = config_match.group(1)
                # Unescape any JSON string escapes
                config_json = config_json.replace("\\'", "'")
                config = json.loads(config_json)

                # Check 'urls' array first
                if "urls" in config and isinstance(config["urls"], list):
                    for url_entry in config["urls"]:
                        if isinstance(url_entry, dict) and "url" in url_entry:
                            raw_url = url_entry["url"]
                            return self._resolve_spec_url(raw_url, base_url)

                # Check 'url' field
                if "url" in config:
                    return self._resolve_spec_url(config["url"], base_url)
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback: look for url patterns in the HTML
        url_patterns = [
            r'"url"\s*:\s*"([^"]+\.json)"',
            r"'url'\s*:\s*'([^']+\.json)'",
            r'url\s*:\s*"([^"]+swagger[^"]*\.json)"',
            r'configUrl\s*:\s*"([^"]+)"',
        ]

        for pattern in url_patterns:
            match = re.search(pattern, html)
            if match:
                return self._resolve_spec_url(match.group(1), base_url)

        return None

    def _resolve_spec_url(self, raw_url: str, base_url: str) -> str:
        """Resolve a potentially relative spec URL against the base."""
        if raw_url.startswith(("http://", "https://")):
            return raw_url
        if raw_url.startswith("/"):
            # Absolute path - resolve against the origin
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{raw_url}"
        # Relative path - resolve against Swagger UI directory
        # e.g., base = http://host/swagger/index.html, url = v1/swagger.json
        # -> http://host/swagger/v1/swagger.json
        if base_url.endswith(".html") or base_url.endswith("/"):
            base_dir = base_url.rsplit("/", 1)[0] + "/"
        else:
            base_dir = base_url + "/"
        return urljoin(base_dir, raw_url)

    async def load_spec(
        self,
        spec_url: Optional[str] = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Retrieve and parse the OpenAPI JSON specification.

        Args:
            spec_url: The URL to fetch. Uses discovered URL if not provided.
            timeout: HTTP timeout.

        Returns:
            The parsed OpenAPI specification dictionary.
        """
        url = spec_url or self._spec_url
        if not url:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_UNREACHABLE,
                "No OpenAPI specification URL available. "
                "Run discover_spec_url() first or configure openapi_spec_url.",
            )

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                self._spec = response.json()
        except httpx.ConnectError as e:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_UNREACHABLE,
                f"Cannot reach OpenAPI spec at {url}: {e}",
            ) from e
        except httpx.HTTPStatusError as e:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_UNREACHABLE,
                f"OpenAPI spec returned HTTP {e.response.status_code} at {url}",
            ) from e
        except json.JSONDecodeError as e:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_VALIDATION_ERROR,
                f"OpenAPI spec at {url} is not valid JSON: {e}",
            ) from e
        except Exception as e:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_UNREACHABLE,
                f"Failed to fetch OpenAPI spec at {url}: {e}",
            ) from e

        if not isinstance(self._spec, dict):
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_VALIDATION_ERROR,
                "OpenAPI spec must be a JSON object.",
            )

        return self._spec

    def resolve_ref(self, ref_or_schema: dict[str, Any]) -> dict[str, Any]:
        """Resolve a $ref reference within the OpenAPI specification.

        Follows $ref pointers to their definitions in components/schemas
        and returns the resolved schema. Handles nested references.

        Args:
            ref_or_schema: A schema dict that may contain $ref.

        Returns:
            The resolved schema without $ref.
        """
        if not self._spec:
            return ref_or_schema

        visited: set[str] = set()
        return self._resolve_ref_recursive(ref_or_schema, visited)

    def _resolve_ref_recursive(
        self, schema: dict[str, Any], visited: set[str]
    ) -> dict[str, Any]:
        """Recursively resolve $ref references."""
        if not isinstance(schema, dict):
            return schema

        if "$ref" in schema:
            ref_path = schema["$ref"]
            if ref_path in visited:
                return {"type": "object", "description": f"Circular reference: {ref_path}"}
            visited.add(ref_path)

            resolved = self._follow_ref(ref_path)
            if resolved is None:
                return {"type": "object", "description": f"Unresolved reference: {ref_path}"}
            return self._resolve_ref_recursive(resolved, visited)

        # Resolve nested schemas
        result = {}
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                result[key] = {
                    k: self._resolve_ref_recursive(v, visited.copy())
                    for k, v in value.items()
                }
            elif key == "items" and isinstance(value, dict):
                result[key] = self._resolve_ref_recursive(value, visited.copy())
            elif key in ("allOf", "oneOf", "anyOf") and isinstance(value, list):
                result[key] = [
                    self._resolve_ref_recursive(item, visited.copy())
                    if isinstance(item, dict) else item
                    for item in value
                ]
            elif key == "additionalProperties" and isinstance(value, dict):
                result[key] = self._resolve_ref_recursive(value, visited.copy())
            else:
                result[key] = value

        return result

    def _follow_ref(self, ref_path: str) -> Optional[dict[str, Any]]:
        """Follow a JSON $ref path within the spec."""
        if not ref_path.startswith("#/"):
            return None

        parts = ref_path[2:].split("/")
        current: Any = self._spec
        for part in parts:
            # Handle JSON Pointer escaping
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current if isinstance(current, dict) else None

    def parse_operations(self) -> dict[tuple[str, str], ResolvedOperation]:
        """Parse all operations from the loaded OpenAPI specification.

        Returns:
            Dictionary mapping (path, METHOD) to ResolvedOperation.
        """
        if not self._spec:
            raise McpToolError.from_code(
                ErrorCode.OPENAPI_VALIDATION_ERROR,
                "No OpenAPI spec loaded. Call load_spec() first.",
            )

        self._operations.clear()
        paths = self._spec.get("paths", {})

        http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            # Path-level parameters apply to all operations under this path
            path_level_params = path_item.get("parameters", [])

            for method_lower, operation in path_item.items():
                if method_lower not in http_methods:
                    continue
                if not isinstance(operation, dict):
                    continue

                method = method_lower.upper()

                # Merge path-level + operation-level parameters
                op_params = operation.get("parameters", [])
                all_params = self._merge_parameters(path_level_params, op_params)

                parameters = [
                    self._parse_parameter(p) for p in all_params
                ]

                request_body = None
                if "requestBody" in operation:
                    request_body = self._parse_request_body(operation["requestBody"])

                responses = []
                for status, resp_def in operation.get("responses", {}).items():
                    if isinstance(resp_def, dict):
                        responses.append(self._parse_response(status, resp_def))

                resolved = ResolvedOperation(
                    path=path,
                    method=method,
                    operation_id=operation.get("operationId"),
                    summary=operation.get("summary"),
                    description=operation.get("description"),
                    tags=operation.get("tags", []),
                    parameters=parameters,
                    request_body=request_body,
                    responses=responses,
                    deprecated=operation.get("deprecated", False),
                )

                self._operations[(path, method)] = resolved

        return dict(self._operations)

    def _merge_parameters(
        self, path_params: list[dict], op_params: list[dict]
    ) -> list[dict]:
        """Merge path-level and operation-level parameters.

        Operation-level parameters override path-level ones with the
        same name and location.
        """
        merged: dict[tuple[str, str], dict] = {}

        for p in path_params:
            if isinstance(p, dict):
                resolved_p = self.resolve_ref(p) if "$ref" in p else p
                key = (resolved_p.get("name", ""), resolved_p.get("in", ""))
                merged[key] = resolved_p

        for p in op_params:
            if isinstance(p, dict):
                resolved_p = self.resolve_ref(p) if "$ref" in p else p
                key = (resolved_p.get("name", ""), resolved_p.get("in", ""))
                merged[key] = resolved_p

        return list(merged.values())

    def _parse_parameter(self, param: dict[str, Any]) -> ParameterSchema:
        """Parse a single OpenAPI parameter."""
        resolved = self.resolve_ref(param)
        schema = resolved.get("schema", {})
        resolved_schema = self.resolve_ref(schema) if isinstance(schema, dict) else {}

        return ParameterSchema(
            name=resolved.get("name", "unknown"),
            location=resolved.get("in", "query"),
            required=resolved.get("required", False),
            schema_type=resolved_schema.get("type"),
            schema_format=resolved_schema.get("format"),
            description=resolved.get("description") or resolved_schema.get("description"),
            default=resolved_schema.get("default"),
            enum=resolved_schema.get("enum"),
            nullable=resolved_schema.get("nullable", False),
            full_schema=resolved_schema if resolved_schema else None,
        )

    def _parse_request_body(self, body: dict[str, Any]) -> RequestBodySchema:
        """Parse a request body definition."""
        resolved = self.resolve_ref(body)
        content = resolved.get("content", {})
        content_types = list(content.keys())

        # Get schema from the first available content type
        schema_def = None
        for ct in ["application/json", "text/json"]:
            if ct in content and isinstance(content[ct], dict):
                raw_schema = content[ct].get("schema", {})
                schema_def = self.resolve_ref(raw_schema) if isinstance(raw_schema, dict) else raw_schema
                break

        if schema_def is None and content_types:
            first_ct = content_types[0]
            if isinstance(content.get(first_ct), dict):
                raw_schema = content[first_ct].get("schema", {})
                schema_def = self.resolve_ref(raw_schema) if isinstance(raw_schema, dict) else raw_schema

        return RequestBodySchema(
            required=resolved.get("required", False),
            content_types=content_types,
            schema_definition=schema_def,
            description=resolved.get("description"),
        )

    def _parse_response(self, status_code: str, response: dict[str, Any]) -> ResponseSchema:
        """Parse a single response definition."""
        resolved = self.resolve_ref(response)
        content = resolved.get("content", {})
        content_types = list(content.keys())

        schema_def = None
        for ct in ["application/json", "text/json"]:
            if ct in content and isinstance(content[ct], dict):
                raw_schema = content[ct].get("schema", {})
                schema_def = self.resolve_ref(raw_schema) if isinstance(raw_schema, dict) else raw_schema
                break

        if schema_def is None and content_types:
            first_ct = content_types[0]
            if isinstance(content.get(first_ct), dict):
                raw_schema = content[first_ct].get("schema", {})
                schema_def = self.resolve_ref(raw_schema) if isinstance(raw_schema, dict) else raw_schema

        return ResponseSchema(
            status_code=status_code,
            description=resolved.get("description"),
            content_types=content_types,
            schema_definition=schema_def,
        )

    def get_operation_by_path_method(
        self, path: str, method: str
    ) -> Optional[ResolvedOperation]:
        """Retrieve a resolved operation by its path and method."""
        return self._operations.get((path, method.upper()))

    def get_all_paths(self) -> list[str]:
        """Return all paths in the specification."""
        if not self._spec:
            return []
        return list(self._spec.get("paths", {}).keys())

    def get_operation_count(self) -> dict[str, int]:
        """Return counts of operations grouped by HTTP method."""
        counts: dict[str, int] = {}
        for (_, method), _ in self._operations.items():
            counts[method] = counts.get(method, 0) + 1
        return counts
