"""Typed configuration management for pm_mcp_server.

Loads settings from config/config.yaml with documented environment-variable overrides.
Validates all settings at startup and fails clearly for invalid required values.
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
        allowed = {"streamable_http", "stdio"}
        if v not in allowed:
            raise ValueError(f"transport must be one of {allowed}, got: {v}")
        return v


class SearchConfig(BaseModel):
    """Search backend configuration."""
    backend: str = "yaml_keyword"
    max_results: int = Field(default=5, ge=1, le=100)
    max_results_limit: int = Field(default=20, ge=1, le=100)

    @field_validator("backend")
    @classmethod
    def _validate_backend(cls, v: str) -> str:
        supported = {"yaml_keyword"}
        if v not in supported:
            raise ValueError(
                f"Search backend '{v}' is not implemented. "
                f"Supported backends: {supported}"
            )
        return v


class LlmConfig(BaseModel):
    """Future LLM provider configuration."""
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key_env_var: str = "LLM_API_KEY"
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class EmbeddingsConfig(BaseModel):
    """Future embedding provider configuration."""
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    dimensions: Optional[int] = Field(default=None, ge=1)
    api_key_env_var: str = "EMBEDDING_API_KEY"
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class VectorStoreConfig(BaseModel):
    """Future vector store configuration."""
    provider: Optional[str] = None
    collection_name: Optional[str] = None


class RetrievalConfig(BaseModel):
    """Future retrieval settings."""
    top_k: int = Field(default=5, ge=1, le=100)
    similarity_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class RagConfig(BaseModel):
    """RAG configuration (disabled for initial implementation)."""
    enabled: bool = False
    llm: LlmConfig = Field(default_factory=LlmConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)

    @model_validator(mode="after")
    def _check_rag_disabled(self) -> "RagConfig":
        if self.enabled:
            raise ValueError(
                "RAG is not implemented in the initial version. "
                "Set rag.enabled to false."
            )
        return self


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
    rag: RagConfig = Field(default_factory=RagConfig)
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
    """Load and validate application configuration.

    Load order:
    1. Read config/config.yaml (or a specified path).
    2. Apply documented environment-variable overrides.
    3. Validate all settings through Pydantic models.
    4. Fail clearly for any invalid or missing required values.

    Environment overrides:
        PM_MCP_DOTNET_BASE_URL       -> dotnet_api.base_url
        PM_MCP_DOTNET_SWAGGER_URL    -> dotnet_api.swagger_ui_url
        PM_MCP_DOTNET_OPENAPI_URL    -> dotnet_api.openapi_spec_url
        PM_MCP_DOTNET_TIMEOUT        -> dotnet_api.timeout_seconds
        PM_MCP_HOST                  -> mcp.host
        PM_MCP_PORT                  -> mcp.port
        PM_MCP_TRANSPORT             -> mcp.transport
        PM_MCP_SEARCH_BACKEND        -> search.backend
        PM_MCP_AUTH_ENABLED          -> authentication.enabled
        PM_MCP_CLOCK_SKEW            -> authentication.clock_skew_seconds
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
            # Convert types for integer/boolean fields
            final_key = keys[-1]
            if final_key in ("timeout_seconds", "port", "clock_skew_seconds"):
                try:
                    value = int(value)
                except ValueError:
                    raise ValueError(
                        f"Environment variable {env_var} must be an integer, got: {value}"
                    )
            elif final_key == "enabled":
                value = value.lower() in ("true", "1", "yes")
            target[final_key] = value
