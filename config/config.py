"""Typed configuration management for mcp_server.

Loads non-sensitive application settings from config/config.yaml.
Environment variables are strictly reserved for tokens and sensitive credentials.
All non-sensitive settings (URLs, ports, hosts, timeouts, transports, limits)
are defined and managed in config/config.yaml.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Configuration sub-models
# ---------------------------------------------------------------------------

class ApplicationConfig(BaseModel):
    """Top-level application identity."""
    name: str = "mcp_server"
    environment: str = "development"


class ApiClientConfig(BaseModel):
    """Configuration for the downstream API client."""
    base_url: str
    swagger_ui_url: str
    openapi_spec_url: Optional[str] = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_response_bytes: int = Field(default=1_048_576, ge=1024)
    max_redirects: int = Field(default=3, ge=0, le=10)
    api_key: Optional[str] = None

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
        allowed = {"streamable_http", "stdio"}
        if v not in allowed:
            raise ValueError(f"transport must be one of {allowed}, got: '{v}'")
        return v


class OllamaConfig(BaseModel):
    """Ollama local service connection configuration."""
    base_url: str = "http://localhost:11434"
    timeout_seconds: int = Field(default=60, ge=1, le=300)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"Ollama base_url must start with http:// or https://, got: {v}")
        return v


class EmbeddingConfig(BaseModel):
    """Multilingual embedding service configuration."""
    provider: str = "ollama"  # "ollama" or "remote"
    base_url: Optional[str] = None
    endpoint_path: Optional[str] = None
    model: str = "bge-m3:latest"
    api_key: Optional[str] = None
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    batch_size: int = Field(default=32, ge=1, le=256)
    dimensions: Optional[int] = Field(default=1024, ge=1)

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        allowed = {"ollama", "remote"}
        if v not in allowed:
            raise ValueError(f"embedding provider must be one of {allowed}, got: '{v}'")
        return v


class RerankingConfig(BaseModel):
    """Candidate reranking service configuration."""
    enabled: bool = True
    provider: str = "ollama"  # "ollama" or "remote"
    base_url: Optional[str] = None
    endpoint_path: Optional[str] = None
    model: str = "qwen:1.8b"
    api_key: Optional[str] = None
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    candidate_limit: int = Field(default=20, ge=1, le=100)
    required: bool = True

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        allowed = {"ollama", "remote"}
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
    api_key: Optional[str] = None
    timeout_seconds: int = Field(default=20, ge=1, le=120)

    @model_validator(mode="after")
    def _check_llm_state(self) -> "LlmSearchConfig":
        if self.enabled:
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
                f"Search backend must be 'semantic', got: '{v}'"
            )
        return v


class CacheConfig(BaseModel):
    """Local vector embedding cache configuration."""
    enabled: bool = True
    directory: str = "cache/api_embeddings"


class StartupChecksConfig(BaseModel):
    """Startup readiness and validation controls."""
    validate_catalog: bool = True
    check_ollama_service: bool = True
    check_embedding_model: bool = True
    check_reranking_model: bool = True
    fail_on_service_unavailable: bool = True
    allow_catalog_only_startup: bool = False

    @model_validator(mode="after")
    def _validate_startup_mode_consistency(self) -> "StartupChecksConfig":
        if not self.validate_catalog:
            raise ValueError("Catalog validation is mandatory and cannot be disabled.")

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
            raise ValueError(f"Logging format must be 'json', got: '{v}'")
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
    """Root configuration for mcp_server."""
    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    api_client: ApiClientConfig
    mcp: McpConfig = Field(default_factory=McpConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    startup_checks: StartupChecksConfig = Field(default_factory=StartupChecksConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    authentication: AuthenticationConfig = Field(default_factory=AuthenticationConfig)
    instructions_file: str = "config/server_instructions.md"


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
    """Load and validate application configuration.

    Reads all structural and operational configuration from config/config.yaml.
    Applies sensitive token/credential overrides from environment variables.
    """
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

    # Apply sensitive token/credential overrides from environment variables only
    _apply_env_overrides(raw)

    return AppConfig.model_validate(raw)


def _apply_env_overrides(raw: dict) -> None:
    """Apply sensitive token and credential overrides from environment variables.

    Strict rule: All non-sensitive configuration values reside strictly in config.yaml.
    Only authentication tokens, API keys, and sensitive secrets may be provided via environment variables.
    """
    sensitive_env_map = [
        ("EMBEDDING_API_KEY", ["search", "embedding", "api_key"]),
        ("MCP_EMBEDDING_API_KEY", ["search", "embedding", "api_key"]),
        ("RERANKER_API_KEY", ["search", "reranking", "api_key"]),
        ("MCP_RERANKER_API_KEY", ["search", "reranking", "api_key"]),
        ("API_BEARER_TOKEN", ["api_client", "api_key"]),
        ("MCP_API_KEY", ["api_client", "api_key"]),
    ]

    for env_var, keys in sensitive_env_map:
        value = os.environ.get(env_var)
        if value is not None and value.strip():
            target = raw
            for key in keys[:-1]:
                if key not in target:
                    target[key] = {}
                target = target[key]
            target[keys[-1]] = value.strip()
