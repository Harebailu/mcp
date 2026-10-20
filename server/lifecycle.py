"""Application lifecycle management.

Handles initialization and shutdown of all server components:
- Configuration loading and validation
- OpenAPI specification discovery and loading
- YAML catalog loading and validation
- Runtime registry population
- Service instantiation
- HTTP client lifecycle
- MCP tool registration
"""

from __future__ import annotations

import sys
from typing import Optional

from server.mcp_compat import FastMCP

from adapters.dotnet_api_client import DotNetApiClient
from catalog.catalog_validator import validate_catalog
from catalog.openapi_loader import OpenApiLoader
from catalog.registry import ApiRegistry
from catalog.yaml_loader import load_yaml_catalog
from config.config import AppConfig, load_config
from services.api_execution_service import ApiExecutionService
from services.api_schema_service import ApiSchemaService
from services.api_search_service import ApiSearchService
from services.dependency_service import DependencyService
from tools.execute_api import register_execute_api
from tools.get_api_schema import register_get_api_schema
from tools.list_all_apis import register_list_all_apis
from tools.search_apis import register_search_apis


class ApplicationLifecycle:
    """Manages the full application lifecycle."""

    def __init__(self) -> None:
        self.config: Optional[AppConfig] = None
        self.openapi_loader: Optional[OpenApiLoader] = None
        self.registry: Optional[ApiRegistry] = None
        self.api_client: Optional[DotNetApiClient] = None
        self.mcp: Optional[FastMCP] = None

        # Services
        self.search_service: Optional[ApiSearchService] = None
        self.schema_service: Optional[ApiSchemaService] = None
        self.execution_service: Optional[ApiExecutionService] = None
        self.dependency_service: Optional[DependencyService] = None

    async def initialize(self, config_path: Optional[str] = None) -> FastMCP:
        """Initialize all components and return the configured MCP server."""

        # 1. Load configuration
        print("[lifecycle] Loading configuration...")
        self.config = load_config(config_path)
        print(f"[lifecycle] Configuration loaded: {self.config.application.name} ({self.config.application.environment})")

        # 2. Initialize OpenAPI loader
        print("[lifecycle] Initializing OpenAPI loader...")
        self.openapi_loader = OpenApiLoader()

        # Try to discover and load OpenAPI spec
        openapi_operations = {}
        try:
            spec_url = await self.openapi_loader.discover_spec_url(
                swagger_ui_url=self.config.dotnet_api.swagger_ui_url,
                explicit_spec_url=self.config.dotnet_api.openapi_spec_url,
                timeout=float(self.config.dotnet_api.timeout_seconds),
            )
            print(f"[lifecycle] OpenAPI spec URL discovered: {spec_url}")

            await self.openapi_loader.load_spec(
                timeout=float(self.config.dotnet_api.timeout_seconds),
            )
            openapi_operations = self.openapi_loader.parse_operations()
            counts = self.openapi_loader.get_operation_count()
            print(f"[lifecycle] OpenAPI operations loaded: {counts}")
        except Exception as e:
            print(f"[lifecycle] WARNING: Could not load OpenAPI spec: {e}")
            print("[lifecycle] Server will start with catalog-only mode.")

        # 3. Load YAML catalog
        print("[lifecycle] Loading YAML catalog...")
        try:
            catalog = load_yaml_catalog()
            print(f"[lifecycle] Catalog loaded: {len(catalog.apis)} entries")
        except FileNotFoundError:
            print("[lifecycle] WARNING: No catalog file found. Starting with empty catalog.")
            from schemas.catalog import ApiCatalog
            catalog = ApiCatalog()

        # 4. Validate catalog
        print("[lifecycle] Validating catalog...")
        validation = validate_catalog(catalog, openapi_operations or None)
        if not validation.is_valid:
            print(f"[lifecycle] WARNING: Catalog validation issues:\n{validation.summary()}")
        else:
            if validation.warnings:
                print(f"[lifecycle] Catalog warnings:\n{validation.summary()}")
            else:
                print("[lifecycle] Catalog validation passed.")

        # 5. Build registry
        print("[lifecycle] Building runtime registry...")
        self.registry = ApiRegistry()
        self.registry.register_catalog(catalog)
        if openapi_operations:
            self.registry.register_operations(openapi_operations)
        print(f"[lifecycle] Registry: {self.registry.get_entry_count()} entries, domains: {self.registry.get_domains()}")

        # 6. Initialize HTTP client
        print("[lifecycle] Initializing .NET API client...")
        self.api_client = DotNetApiClient(
            base_url=self.config.dotnet_api.base_url,
            timeout_seconds=self.config.dotnet_api.timeout_seconds,
            max_response_bytes=self.config.dotnet_api.max_response_bytes,
            max_redirects=self.config.dotnet_api.max_redirects,
        )
        await self.api_client.start()
        print("[lifecycle] .NET API client initialized.")

        # 7. Initialize services
        print("[lifecycle] Initializing services...")
        self.dependency_service = DependencyService(self.registry)

        self.search_service = ApiSearchService(
            registry=self.registry,
            backend_name=self.config.search.backend,
            default_limit=self.config.search.max_results,
            max_limit=self.config.search.max_results_limit,
        )

        self.schema_service = ApiSchemaService(
            registry=self.registry,
            dependency_service=self.dependency_service,
        )

        self.execution_service = ApiExecutionService(
            registry=self.registry,
            api_client=self.api_client,
        )
        print("[lifecycle] Services initialized.")

        # 8. Create MCP server and register tools
        print("[lifecycle] Creating MCP server and registering tools...")
        self.mcp = FastMCP(
            name=self.config.application.name,
        )

        register_search_apis(self.mcp, self.search_service)
        register_get_api_schema(self.mcp, self.schema_service)
        register_execute_api(self.mcp, self.execution_service, self.config.authentication)
        register_list_all_apis(self.mcp, self.registry)

        print("[lifecycle] All 4 MCP tools registered.")
        print("[lifecycle] Initialization complete.")

        return self.mcp

    async def shutdown(self) -> None:
        """Clean up all resources."""
        print("[lifecycle] Shutting down...")

        if self.api_client:
            await self.api_client.close()
            print("[lifecycle] HTTP client closed.")

        print("[lifecycle] Shutdown complete.")
