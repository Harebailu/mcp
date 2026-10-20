# Configuration Reference: `mcp_server`

`mcp_server` uses strongly typed configuration via Pydantic v2. Settings are loaded from `config/config.yaml` and can be overridden by environment variables.

---

## 1. Configuration Structure

```yaml
application:
  name: "mcp_server"              # Production service name: "pm-mcp-server"
  environment: "development"      # "development" or "production"

dotnet_api:
  base_url: "http://localhost:5273"
  swagger_ui_url: "http://localhost:5273/swagger/index.html"
  openapi_spec_url: null
  timeout_seconds: 30
  max_response_bytes: 1048576
  max_redirects: 3

mcp:
  host: "127.0.0.1"
  port: 8000
  transport: "streamable_http"

ollama:
  base_url: "http://localhost:11434"
  timeout_seconds: 60

search:
  backend: "semantic"
  max_results: 5
  candidate_limit: 20
  minimum_score: null

  embedding:
    provider: "ollama"            # "ollama" or "remote"
    model: "bge-m3:latest"
    dimensions: 1024
    batch_size: 32
    timeout_seconds: 60

  reranking:
    enabled: true
    provider: "ollama"            # "ollama" or "remote"
    model: "qwen:1.8b"
    required: true
    candidate_limit: 20
    timeout_seconds: 60

  llm:
    enabled: false
    provider: null
    base_url: null
    endpoint_path: null
    model: null
    api_key_env_var: "LLM_API_KEY"
    timeout_seconds: 20

  query_enrichment:
    enabled: false

cache:
  enabled: true
  directory: "cache/api_embeddings"

startup_checks:
  validate_catalog: true
  check_ollama_service: true
  check_embedding_model: true
  check_reranking_model: true
  fail_on_service_unavailable: true
  allow_catalog_only_startup: false

logging:
  level: "INFO"
  format: "json"
  output: "stdout"

authentication:
  enabled: true
  expiration_claim: "exp"
  clock_skew_seconds: 0
```

---

## 2. Environment Variable Overrides

| Environment Variable | Target Configuration Key | Description |
|---|---|---|
| `MCP_OLLAMA_BASE_URL` | `ollama.base_url` | Host/service URL of the local or containerized Ollama instance |
| `MCP_OLLAMA_TIMEOUT` | `ollama.timeout_seconds` | Request timeout in seconds for Ollama calls |
| `MCP_DOTNET_BASE_URL` | `dotnet_api.base_url` | Base URL of the downstream .NET API |
| `MCP_DOTNET_SWAGGER_URL` | `dotnet_api.swagger_ui_url` | Swagger UI page URL |
| `MCP_DOTNET_OPENAPI_URL` | `dotnet_api.openapi_spec_url` | Explicit OpenAPI JSON specification URL |
| `MCP_DOTNET_TIMEOUT` | `dotnet_api.timeout_seconds` | Request timeout in seconds |
| `MCP_HOST` | `mcp.host` | Host address to bind |
| `MCP_PORT` | `mcp.port` | Port number to bind |
| `MCP_TRANSPORT` | `mcp.transport` | `streamable_http`, `sse`, or `stdio` |
| `MCP_SEARCH_BACKEND` | `search.backend` | Must be `semantic` |
| `MCP_EMBEDDING_PROVIDER` | `search.embedding.provider` | `ollama` or `remote` |
| `MCP_EMBEDDING_MODEL` | `search.embedding.model` | Embedding model identifier (`bge-m3:latest`) |
| `MCP_RERANKER_PROVIDER` | `search.reranking.provider` | `ollama` or `remote` |
| `MCP_RERANKER_MODEL` | `search.reranking.model` | Reranker model identifier (`qwen:1.8b`) |
| `MCP_ALLOW_CATALOG_ONLY` | `startup_checks.allow_catalog_only_startup` | Enable catalog-only degraded startup |
| `MCP_FAIL_ON_UNAVAILABLE` | `startup_checks.fail_on_service_unavailable` | Fail fast if model services are down |
| `MCP_LOG_LEVEL` | `logging.level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `MCP_AUTH_ENABLED` | `authentication.enabled` | Inbound JWT expiration check |
| `MCP_CLOCK_SKEW` | `authentication.clock_skew_seconds` | Allowed JWT clock skew in seconds |

*(Legacy `PM_` environment variables are also supported for backward compatibility).*

---

## 3. Operational Modes & Startup Invariants

1. **Standard Ollama Mode**:
   - `search.embedding.provider: "ollama"` (`bge-m3:latest`)
   - `search.reranking.provider: "ollama"` (`qwen:1.8b`)
   - Validates model installation via Ollama `/api/tags` on startup.
2. **Strict Mode**:
   - `startup_checks.fail_on_service_unavailable: true`
   - `startup_checks.allow_catalog_only_startup: false`
   - Unreachable Ollama service or missing model immediately aborts startup with an actionable error.
3. **Catalog-Only Mode**:
   - `startup_checks.allow_catalog_only_startup: true`
   - `startup_checks.fail_on_service_unavailable: false`
   - Server boots with valid catalog even if Ollama is offline.
   - MCP `search_apis` returns `MODEL_SERVICE_UNAVAILABLE` error directing agents to `list_all_apis`.
   - `list_all_apis`, `get_api_schema`, and `execute_api` operate normally.
   - **Validation Invariant**: Setting `allow_catalog_only_startup: true` with `fail_on_service_unavailable: true` is an invalid configuration state rejected by Pydantic validation.
