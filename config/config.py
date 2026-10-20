"""Typed configuration management for pm_mcp_server.

Loads settings from config/config.yaml with documented environment-variable overrides.
Validates all settings at startup, enforcing semantic search readiness,
strict validation rules, and startup check constraints.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Configuration sub-models
# ---------------------------------------------------------------------------

class ApplicationConfig(BaseModel):
    """Top-level application identity."""
    name: str = "pm_mcp_server"
    environment: str = "development"


class DotNetApiConfig(BaseModel):
    """Configuration for the downstream .NET API."""
    base_url: str
    swagger_ui_url: str
    openapi_spec_url: Optional[str] = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_response_bytes: int = Field(default=1_048_576, ge=1024)
    max_redirects: int = Field(default=3, ge=0, le=10)

    @field_validator("base_url", "swagger_ui_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"URL must start with http:// or https://, got: {v}")
        return v

    @field_validator("openapi_spec_url", mode="before")
    @classmethod
    def _validate_optional_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"URL must start with http:// or https://, got: {v}")
        return v


class McpConfig(BaseModel):
    """MCP server transport configuration."""
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    transport: str = "streamable_http"

    @field_validator("transport")
    @classmethod
    def _validate_transport(cls, v: str) -> str:
        allowed = {"streamable_http", "streamable-http", "sse", "stdio"}
        if v not in allowed:
            raise ValueError(f"transport must be one of {allowed}, got: {v}")
        return v


class EmbeddingConfig(BaseModel):
    """Multilingual embedding service configuration."""
    provider: str = "mock"  # "mock" or "remote"
    base_url: Optional[str] = None
    endpoint_path: Optional[str] = None
    model: str = "REPLACE_WITH_CONFIGURED_MULTILINGUAL_MODEL"
    api_key_env_var: str = "EMBEDDING_API_KEY"
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    batch_size: int = Field(default=32, ge=1, le=256)
    dimensions: Optional[int] = Field(default=None, ge=1)

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        allowed = {"mock", "remote"}
        if v not in allowed:
            raise ValueError(f"embedding provider must be one of {allowed}, got: '{v}'")
        return v


class RerankingConfig(BaseModel):
    """Candidate reranking service configuration."""
    enabled: bool = True
    provider: str = "mock"  # "mock" or "remote"
    base_url: Optional[str] = None
    endpoint_path: Optional[str] = None
    model: Optional[str] = None
    api_key_env_var: str = "RERANKER_API_KEY"
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    candidate_limit: int = Field(default=20, ge=1, le=100)
    required: bool = True

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        allowed = {"mock", "remote"}
        if v not in allowed:
            raise ValueError(f"reranking provider must be one of {allowed}, got: '{v}'")
        return v


class LlmSearchConfig(BaseModel):
    """Optional future LLM query assistance configuration."""
    enabled: bool = False
    provider: Optional[str] = None
    base_url: Optional[str] = None
    endpoint_path: Optional[str] = None
    model: Optional[str] = None
    api_key_env_var: str = "LLM_API_KEY"
    timeout_seconds: int = Field(default=20, ge=1, le=120)

    @model_validator(mode="after")
    def _check_llm_state(self) -> "LlmSearchConfig":
        if self.enabled:
            # Future LLM features remain disabled in initial deployment
            raise ValueError(
                "LLM query assistance is not enabled in this deployment. "
                "Keep search.llm.enabled set to false."
            )
        return self


class QueryEnrichmentConfig(BaseModel):
    """Query enrichment flag."""
    enabled: bool = False


class SearchConfig(BaseModel):
    """Search pipeline configuration (multilingual semantic retrieval & reranking)."""
    backend: str = "semantic"
    max_results: int = Field(default=5, ge=1, le=50)
    candidate_limit: int = Field(default=20, ge=1, le=100)
    minimum_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    reranking: RerankingConfig = Field(default_factory=RerankingConfig)
    llm: LlmSearchConfig = Field(default_factory=LlmSearchConfig)
    query_enrichment: QueryEnrichmentConfig = Field(default_factory=QueryEnrichmentConfig)

    @field_validator("backend")
    @classmethod
    def _validate_backend(cls, v: str) -> str:
        if v != "semantic":
            raise ValueError(
                f"Keyword search has been removed. Search backend must be 'semantic', got: '{v}'"
            )
        return v


class CacheConfig(BaseModel):
    """Local vector embedding cache configuration."""
    enabled: bool = True
    directory: str = "cache/api_embeddings"


class StartupChecksConfig(BaseModel):
    """Startup readiness and validation controls."""
    validate_catalog: bool = True
    check_embedding_service: bool = True
    check_reranker_service: bool = True
    check_llm_service_when_enabled: bool = True
    fail_on_service_unavailable: bool = True
    allow_catalog_only_startup: bool = False

    @model_validator(mode="after")
    def _validate_startup_mode_consistency(self) -> "StartupChecksConfig":
        # Mandatory catalog validation must NEVER be disabled
        if not self.validate_catalog:
            raise ValueError("Catalog validation is mandatory and cannot be disabled.")

        # Reject contradictory mode configuration
        if self.allow_catalog_only_startup and self.fail_on_service_unavailable:
            raise ValueError(
                "Contradictory configuration: when allow_catalog_only_startup is true, "
                "fail_on_service_unavailable must be false."
            )
        return self


class LoggingConfig(BaseModel):
    """Structured JSON stdout logging configuration."""
    level: str = "INFO"
    format: str = "json"
    output: str = "stdout"

    @field_validator("level")
    @classmethod
    def _validate_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"logging level must be one of {allowed}, got: '{v}'")
        return v_upper

    @field_validator("format")
    @classmethod
    def _validate_format(cls, v: str) -> str:
        if v.lower() != "json":
            raise ValueError(f"logging format must be 'json', got: '{v}'")
        return "json"


class AuthenticationConfig(BaseModel):
    """Inbound JWT expiration-check configuration."""
    enabled: bool = True
    expiration_claim: str = "exp"
    clock_skew_seconds: int = Field(default=0, ge=0, le=300)


# ---------------------------------------------------------------------------
# Root configuration model
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    """Root configuration for pm_mcp_server."""
    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    dotnet_api: DotNetApiConfig
    mcp: McpConfig = Field(default_factory=McpConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    startup_checks: StartupChecksConfig = Field(default_factory=StartupChecksConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    authentication: AuthenticationConfig = Field(default_factory=AuthenticationConfig)


# ---------------------------------------------------------------------------
# Resolve project root
# ---------------------------------------------------------------------------

def _get_project_root() -> Path:
    """Return the project root directory (parent of config/)."""
    return Path(__file__).resolve().parent.parent


def _get_config_path() -> Path:
    """Return the path to the default config.yaml."""
    return _get_project_root() / "config" / "config.yaml"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """Load and validate application configuration with environment overrides."""
    path = Path(config_path) if config_path else _get_config_path()

    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {path}. "
            f"Create config/config.yaml or specify a path."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Configuration file must be a YAML mapping, got: {type(raw).__name__}")

    # Apply environment overrides
    _apply_env_overrides(raw)

    return AppConfig.model_validate(raw)


def _apply_env_overrides(raw: dict) -> None:
    """Apply documented environment-variable overrides to raw config dict."""
    env_map = [
        ("PM_MCP_DOTNET_BASE_URL", ["dotnet_api", "base_url"]),
        ("PM_MCP_DOTNET_SWAGGER_URL", ["dotnet_api", "swagger_ui_url"]),
        ("PM_MCP_DOTNET_OPENAPI_URL", ["dotnet_api", "openapi_spec_url"]),
        ("PM_MCP_DOTNET_TIMEOUT", ["dotnet_api", "timeout_seconds"]),
        ("PM_MCP_HOST", ["mcp", "host"]),
        ("PM_MCP_PORT", ["mcp", "port"]),
        ("PM_MCP_TRANSPORT", ["mcp", "transport"]),
        ("PM_MCP_SEARCH_BACKEND", ["search", "backend"]),
        ("PM_MCP_EMBEDDING_PROVIDER", ["search", "embedding", "provider"]),
        ("PM_MCP_EMBEDDING_BASE_URL", ["search", "embedding", "base_url"]),
        ("PM_MCP_EMBEDDING_MODEL", ["search", "embedding", "model"]),
        ("PM_MCP_RERANKER_PROVIDER", ["search", "reranking", "provider"]),
        ("PM_MCP_RERANKER_BASE_URL", ["search", "reranking", "base_url"]),
        ("PM_MCP_RERANKER_MODEL", ["search", "reranking", "model"]),
        ("PM_MCP_ALLOW_CATALOG_ONLY", ["startup_checks", "allow_catalog_only_startup"]),
        ("PM_MCP_FAIL_ON_UNAVAILABLE", ["startup_checks", "fail_on_service_unavailable"]),
        ("PM_MCP_LOG_LEVEL", ["logging", "level"]),
        ("PM_MCP_AUTH_ENABLED", ["authentication", "enabled"]),
        ("PM_MCP_CLOCK_SKEW", ["authentication", "clock_skew_seconds"]),
    ]

    for env_var, keys in env_map:
        value = os.environ.get(env_var)
        if value is not None:
            target = raw
            for key in keys[:-1]:
                if key not in target:
                    target[key] = {}
                target = target[key]

            final_key = keys[-1]
            if final_key in ("timeout_seconds", "port", "clock_skew_seconds", "dimensions", "batch_size", "candidate_limit", "max_results"):
                try:
                    value = int(value)
                except ValueError:
                    raise ValueError(
                        f"Environment variable {env_var} must be an integer, got: {value}"
                    )
            elif final_key in ("enabled", "allow_catalog_only_startup", "fail_on_service_unavailable", "required", "validate_catalog"):
                value = value.lower() in ("true", "1", "yes")

            target[final_key] = value
