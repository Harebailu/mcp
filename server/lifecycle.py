"""Application lifecycle management.

Handles initialization and shutdown of all server components:
- Configuration loading and validation
- Structured JSON logging setup
- OpenAPI specification discovery and loading
- Domain-based YAML catalog loading and integrity validation
- Runtime registry population
- Multilingual semantic search, embedding cache, and candidate reranking setup via local Ollama
- Optional bilingual query enrichment setup (English / Korean)
- Downstream HTTP client lifecycle
- MCP tool registration
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from adapters.api_client import ApiClient
from catalog.catalog_validator import validate_catalog
from catalog.openapi_loader import OpenApiLoader
from catalog.registry import ApiRegistry
from catalog.yaml_loader import load_yaml_catalog
from config.config import AppConfig, load_config
from observability.json_logging import get_logger, setup_json_logging
from schemas.errors import ErrorCode, McpToolError
from search.embeddings.ollama_provider import OllamaEmbeddingProvider
from search.embeddings.remote_provider import RemoteEmbeddingProvider
from search.enrichment.ollama_provider import OllamaQueryEnrichmentProvider
from search.enrichment.remote_provider import RemoteApiQueryEnrichmentProvider
from search.enrichment.service import QueryEnrichmentService
from search.reranking.ollama_provider import OllamaRerankerProvider
from search.reranking.remote_provider import RemoteRerankerProvider
from search.retrieval.embedding_cache import EmbeddingCache
from search.retrieval.vector_index import VectorIndex
from search.service import SemanticSearchService
from server.mcp_compat import FastMCP
from services.api_execution_service import ApiExecutionService
from services.api_schema_service import ApiSchemaService
from services.dependency_service import DependencyService
from tools.execute_api import register_execute_api
from tools.get_api_schema import register_get_api_schema
from tools.list_all_apis import register_list_all_apis
from tools.search_apis import register_search_apis

_logger = get_logger("server.lifecycle")


class ApplicationLifecycle:
    """Manages the full application lifecycle."""

    def __init__(self) -> None:
        self.config: Optional[AppConfig] = None
        self.openapi_loader: Optional[OpenApiLoader] = None
        self.registry: Optional[ApiRegistry] = None
        self.api_client: Optional[ApiClient] = None
        self.mcp: Optional[FastMCP] = None

        # Search components
        self.embedding_cache: Optional[EmbeddingCache] = None
        self.vector_index: Optional[VectorIndex] = None
        self.query_enrichment_service: Optional[QueryEnrichmentService] = None
        self.search_service: Optional[SemanticSearchService] = None

        # Core services
        self.schema_service: Optional[ApiSchemaService] = None
        self.execution_service: Optional[ApiExecutionService] = None
        self.dependency_service: Optional[DependencyService] = None

    async def initialize(self, config_path: Optional[str] = None) -> FastMCP:
        """Initialize all components and return the configured MCP server."""
        init_start = time.perf_counter()

        # 1. Load configuration
        self.config = load_config(config_path)

        # 2. Setup structured JSON logging
        setup_json_logging(
            level=self.config.logging.level,
            output=self.config.logging.output,
        )
        _logger.info_event(
            "Application initialization started",
            details={
                "environment": self.config.application.environment,
                "transport": self.config.mcp.transport,
                "host": self.config.mcp.host,
                "port": self.config.mcp.port,
            },
        )

        # 3. Discover and load OpenAPI specification
        self.openapi_loader = OpenApiLoader()
        openapi_operations = None
        try:
            spec_url = await self.openapi_loader.discover_spec_url(
                swagger_ui_url=self.config.api_client.swagger_ui_url,
                explicit_spec_url=self.config.api_client.openapi_spec_url,
                timeout=float(self.config.api_client.timeout_seconds),
            )
            await self.openapi_loader.load_spec(
                timeout=float(self.config.api_client.timeout_seconds),
            )
            openapi_operations = self.openapi_loader.parse_operations()
            counts = self.openapi_loader.get_operation_count()
            _logger.info_event(
                "OpenAPI specification loaded",
                details={"spec_url": spec_url, "operation_counts": counts},
            )
        except Exception as e:
            _logger.warning_event(
                "Could not load OpenAPI specification; continuing with catalog metadata only",
                details={"error": str(e)},
            )

        # 4. Load domain-based YAML catalog
        try:
            catalog = load_yaml_catalog()
            _logger.info_event(
                "YAML catalog loaded successfully",
                candidate_count=len(catalog.apis),
                details={"version": catalog.catalog_version, "domain_files": catalog.domain_files},
            )
        except Exception as e:
            _logger.error_event("Failed to load YAML catalog", details={"error": str(e)})
            raise

        # 5. Validate catalog integrity
        if self.config.startup_checks.validate_catalog:
            validation = validate_catalog(catalog, openapi_operations or None)
            if not validation.is_valid:
                _logger.error_event(
                    "Catalog validation failed",
                    details={"errors": validation.errors, "warnings": validation.warnings},
                )
                raise McpToolError.from_code(
                    ErrorCode.CATALOG_VALIDATION_ERROR,
                    f"Catalog validation failed with {len(validation.errors)} error(s):\n{validation.summary()}",
                )
            if validation.warnings:
                _logger.warning_event(
                    "Catalog validation passed with warnings",
                    details={"warnings": validation.warnings},
                )
            else:
                _logger.info_event("Catalog integrity validation passed with zero errors")

        # 6. Build runtime registry
        self.registry = ApiRegistry()
        self.registry.register_catalog(catalog)
        if openapi_operations:
            self.registry.register_operations(openapi_operations)
        _logger.info_event(
            "Runtime registry populated",
            candidate_count=self.registry.get_entry_count(),
            details={"domains": self.registry.get_domains()},
        )

        # 7. Initialize target API HTTP adapter
        self.api_client = ApiClient(
            base_url=self.config.api_client.base_url,
            timeout_seconds=self.config.api_client.timeout_seconds,
            max_response_bytes=self.config.api_client.max_response_bytes,
            max_redirects=self.config.api_client.max_redirects,
        )
        await self.api_client.start()
        _logger.info_event("API client initialized")

        # 8. Initialize core services
        self.dependency_service = DependencyService(self.registry)
        self.schema_service = ApiSchemaService(
            registry=self.registry,
            dependency_service=self.dependency_service,
        )
        self.execution_service = ApiExecutionService(
            registry=self.registry,
            api_client=self.api_client,
        )

        # 9. Initialize Multilingual Semantic Search & Reranking
        self.embedding_cache = EmbeddingCache(
            cache_dir=self.config.cache.directory,
            enabled=self.config.cache.enabled,
        )
        self.vector_index = VectorIndex()

        # Instantiate embedding provider (Ollama or Remote)
        emb_cfg = self.config.search.embedding
        if emb_cfg.provider == "ollama":
            embedding_provider = OllamaEmbeddingProvider(
                base_url=self.config.ollama.base_url,
                model_name=emb_cfg.model or "bge-m3:latest",
                timeout_seconds=emb_cfg.timeout_seconds,
                batch_size=emb_cfg.batch_size,
                dimensions=emb_cfg.dimensions or 1024,
            )
        else:
            embedding_provider = RemoteEmbeddingProvider(
                base_url=emb_cfg.base_url or "",
                model_name=emb_cfg.model,
                endpoint_path=emb_cfg.endpoint_path,
                api_key=emb_cfg.api_key,
                api_key_env_var=emb_cfg.api_key_env_var,
                timeout_seconds=emb_cfg.timeout_seconds,
                batch_size=emb_cfg.batch_size,
                dimensions=emb_cfg.dimensions,
            )

        # Instantiate reranker provider (Ollama or Remote)
        rerank_cfg = self.config.search.reranking
        reranker_provider = None
        if rerank_cfg.enabled:
            if rerank_cfg.provider == "ollama":
                reranker_provider = OllamaRerankerProvider(
                    base_url=self.config.ollama.base_url,
                    model_name=rerank_cfg.model or "qwen:1.8b",
                    timeout_seconds=rerank_cfg.timeout_seconds,
                )
            else:
                reranker_provider = RemoteRerankerProvider(
                    base_url=rerank_cfg.base_url or "",
                    model_name=rerank_cfg.model,
                    endpoint_path=rerank_cfg.endpoint_path,
                    api_key=rerank_cfg.api_key,
                    api_key_env_var=rerank_cfg.api_key_env_var,
                    timeout_seconds=rerank_cfg.timeout_seconds,
                )

        # Instantiate query enrichment service (when enabled)
        enrich_cfg = self.config.search.query_enrichment
        if enrich_cfg.enabled:
            if enrich_cfg.provider == "ollama":
                enrich_base_url = enrich_cfg.ollama.base_url or self.config.ollama.base_url
                enrichment_provider = OllamaQueryEnrichmentProvider(
                    base_url=enrich_base_url,
                    model_name=enrich_cfg.model or "qwen:1.8b",
                    endpoint_path=enrich_cfg.ollama.endpoint_path,
                    timeout_seconds=enrich_cfg.timeout_seconds,
                )
            else:
                enrichment_provider = RemoteApiQueryEnrichmentProvider(
                    base_url=enrich_cfg.remote_api.base_url or "",
                    model_name=enrich_cfg.remote_api.model or enrich_cfg.model,
                    endpoint_path=enrich_cfg.remote_api.endpoint_path,
                    api_key=enrich_cfg.remote_api.api_key,
                    api_key_env_var=enrich_cfg.remote_api.api_key_env_var,
                    timeout_seconds=enrich_cfg.remote_api.timeout_seconds,
                )

            # Check query enrichment model readiness
            if self.config.startup_checks.check_enrichment_model:
                enrich_ready = await enrichment_provider.check_readiness()
                if not enrich_ready:
                    _logger.warning_event(
                        "Query enrichment readiness probe failed",
                        details={
                            "provider": enrichment_provider.provider_name,
                            "model": enrichment_provider.model_name,
                        },
                    )
                    if self.config.startup_checks.fail_on_service_unavailable and not enrich_cfg.fail_open:
                        raise McpToolError.from_code(
                            ErrorCode.MODEL_SERVICE_UNAVAILABLE,
                            f"Query enrichment model '{enrichment_provider.model_name}' is not reachable.",
                        )

            self.query_enrichment_service = QueryEnrichmentService(
                provider=enrichment_provider,
                enabled=True,
                fail_open=enrich_cfg.fail_open,
                max_query_length=enrich_cfg.max_query_length,
                max_alternative_queries=enrich_cfg.max_alternative_queries,
            )
            _logger.info_event(
                "Bilingual query enrichment service active",
                details={
                    "provider": enrichment_provider.provider_name,
                    "model": enrichment_provider.model_name,
                    "fail_open": enrich_cfg.fail_open,
                    "max_alternatives": enrich_cfg.max_alternative_queries,
                },
            )
        else:
            self.query_enrichment_service = QueryEnrichmentService(enabled=False)

        # Startup readiness checks for model services
        model_services_healthy = True
        service_unavail_reason = None

        # Check embedding model availability
        if self.config.startup_checks.check_embedding_model or self.config.startup_checks.check_ollama_service:
            emb_ready = await embedding_provider.check_readiness()
            if not emb_ready:
                model_services_healthy = False
                service_unavail_reason = (
                    f"Embedding service/model ('{embedding_provider.provider_name}': '{embedding_provider.model_name}') is not reachable or not installed."
                )
                if self.config.startup_checks.fail_on_service_unavailable:
                    _logger.error_event("Embedding service/model check failed", error_code="EMBEDDING_SERVICE_UNAVAILABLE")
                    raise McpToolError.from_code(
                        ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                        f"{service_unavail_reason} Server startup aborted.",
                    )
                else:
                    _logger.warning_event(
                        "Embedding service check failed; server will continue in catalog-only mode",
                        details={"provider": embedding_provider.provider_name, "model": embedding_provider.model_name},
                    )

        # Check reranker model availability
        if rerank_cfg.enabled and self.config.startup_checks.check_reranking_model and reranker_provider:
            rerank_ready = await reranker_provider.check_readiness()
            if not rerank_ready:
                if rerank_cfg.required:
                    model_services_healthy = False
                    service_unavail_reason = (
                        service_unavail_reason or f"Reranker service/model ('{reranker_provider.provider_name}': '{reranker_provider.model_name}') is not reachable or not installed."
                    )
                    if self.config.startup_checks.fail_on_service_unavailable:
                        _logger.error_event("Reranker service/model check failed", error_code="RERANKER_SERVICE_UNAVAILABLE")
                        raise McpToolError.from_code(
                            ErrorCode.RERANKER_SERVICE_UNAVAILABLE,
                            f"{service_unavail_reason} Server startup aborted.",
                        )
                    else:
                        _logger.warning_event(
                            "Required reranker service check failed; server will continue in catalog-only mode",
                            details={"provider": reranker_provider.provider_name, "model": reranker_provider.model_name},
                        )
                else:
                    _logger.warning_event(
                        "Optional reranker service check failed; search will proceed with semantic vector ordering only"
                    )

        # Initialize SemanticSearchService
        self.search_service = SemanticSearchService(
            registry=self.registry,
            embedding_provider=embedding_provider,
            reranker_provider=reranker_provider,
            vector_index=self.vector_index,
            embedding_cache=self.embedding_cache,
            query_enrichment_service=self.query_enrichment_service,
            default_limit=self.config.search.max_results,
            candidate_limit=self.config.search.candidate_limit,
            minimum_score=self.config.search.minimum_score,
            reranking_enabled=self.config.search.reranking.enabled,
            reranking_required=self.config.search.reranking.required,
        )

        if not model_services_healthy and self.config.startup_checks.allow_catalog_only_startup:
            self.search_service._semantic_search_ready = False
            self.search_service._unavailability_reason = service_unavail_reason
            _logger.warning_event(
                "Started in catalog-only mode: semantic search is marked unavailable",
                details={"reason": service_unavail_reason},
            )
        else:
            await self.search_service.initialize_vectors(
                allow_catalog_only_startup=self.config.startup_checks.allow_catalog_only_startup,
            )

        # 10. Load complete instructions and descriptions from dedicated file
        instructions = self._load_server_instructions()

        # 11. Instantiate FastMCP server with instructions and register the 4 generic tools
        self.mcp = FastMCP(
            name=self.config.application.name,
            instructions=instructions,
        )

        register_search_apis(self.mcp, self.search_service)
        register_get_api_schema(self.mcp, self.schema_service)
        register_execute_api(self.mcp, self.execution_service, self.config.authentication)
        register_list_all_apis(self.mcp, self.registry)

        total_duration_ms = (time.perf_counter() - init_start) * 1000.0
        _logger.info_event(
            "mcp_server initialization complete",
            duration_ms=total_duration_ms,
            outcome="ready",
            details={
                "tools_registered": ["search_apis", "get_api_schema", "execute_api", "list_all_apis"],
                "semantic_search_ready": self.search_service.is_ready,
                "search_mode": self.search_service.search_mode,
                "query_enrichment_enabled": self.config.search.query_enrichment.enabled,
            },
        )

        return self.mcp

    def _load_server_instructions(self) -> str:
        """Load complete instructions and descriptions from the configured markdown file."""
        instructions_file = self.config.instructions_file if self.config else "config/server_instructions.md"
        instructions_path = Path(instructions_file)
        if not instructions_path.is_absolute():
            instructions_path = Path(__file__).resolve().parent.parent / instructions_file

        if instructions_path.exists():
            try:
                with open(instructions_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                _logger.info_event(
                    "Server instructions loaded successfully",
                    details={"path": str(instructions_path), "length": len(content)},
                )
                return content
            except Exception as e:
                _logger.warning_event(
                    "Failed to read instructions file; using default instructions",
                    details={"error": str(e), "path": str(instructions_path)},
                )

        return (
            "Generic metadata-driven MCP server providing API discovery, schema resolution, "
            "and secure execution for downstream business APIs."
        )

    async def shutdown(self) -> None:
        """Gracefully release all resources."""
        _logger.info_event("Application shutdown initiated")
        if self.api_client:
            await self.api_client.close()
            _logger.info_event("API client closed")
        _logger.info_event("Application shutdown complete")
