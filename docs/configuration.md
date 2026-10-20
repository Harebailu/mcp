# Configuration Reference: `pm_mcp_server`

`pm_mcp_server` uses strongly typed configuration via Pydantic v2. Settings are loaded from `config/config.yaml` and can be overridden by environment variables.

---

## 1. Configuration Structure

```yaml
application:
  name: "pm_mcp_server"
  environment: "development"

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

search:
  backend: "semantic"
  max_results: 5
  candidate_limit: 20
  minimum_score: null

  embedding:
    provider: "mock"              # "mock" or "remote"
    base_url: null
    endpoint_path: null
    model: "REPLACE_WITH_CONFIGURED_MULTILINGUAL_MODEL"
    api_key_env_var: "EMBEDDING_API_KEY"
    timeout_seconds: 20
    batch_size: 32
    dimensions: null

  reranking:
    enabled: true
    provider: "mock"              # "mock" or "remote"
    base_url: null
    endpoint_path: null
    model: null
    api_key_env_var: "RERANKER_API_KEY"
    timeout_seconds: 20
    candidate_limit: 20
    required: true

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
  check_embedding_service: true
  check_reranker_service: true
  check_llm_service_when_enabled: true
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
| `PM_MCP_DOTNET_BASE_URL` | `dotnet_api.base_url` | Base URL of the downstream .NET API |
| `PM_MCP_DOTNET_SWAGGER_URL` | `dotnet_api.swagger_ui_url` | Swagger UI page URL |
| `PM_MCP_DOTNET_OPENAPI_URL` | `dotnet_api.openapi_spec_url` | Explicit OpenAPI JSON specification URL |
| `PM_MCP_DOTNET_TIMEOUT` | `dotnet_api.timeout_seconds` | Request timeout in seconds |
| `PM_MCP_HOST` | `mcp.host` | Host address to bind |
| `PM_MCP_PORT` | `mcp.port` | Port number to bind |
| `PM_MCP_TRANSPORT` | `mcp.transport` | `streamable_http`, `sse`, or `stdio` |
| `PM_MCP_SEARCH_BACKEND` | `search.backend` | Must be `semantic` |
| `PM_MCP_AUTH_ENABLED` | `authentication.enabled` | Inbound JWT expiration check |
| `PM_MCP_CLOCK_SKEW` | `authentication.clock_skew_seconds` | Allowed JWT clock skew in seconds |
| `EMBEDDING_API_KEY` | (read by provider) | Bearer token for remote embedding service |
| `RERANKER_API_KEY` | (read by provider) | Bearer token for remote reranker service |
| `LLM_API_KEY` | (read by provider) | Bearer token for remote LLM service |

---

## 3. Operational Modes & Startup Invariants

1. **Mode A (Mock Mode)**:
   - `search.embedding.provider: "mock"`
   - `search.reranking.provider: "mock"`
   - Always passes readiness checks locally.
2. **Mode B (Strict Remote)**:
   - `search.embedding.provider: "remote"`
   - `startup_checks.fail_on_service_unavailable: true`
   - `startup_checks.allow_catalog_only_startup: false`
   - Unreachable remote model service immediately aborts startup.
3. **Mode C (Catalog-Only Mode)**:
   - `startup_checks.allow_catalog_only_startup: true`
   - `startup_checks.fail_on_service_unavailable: false`
   - Server boots with valid catalog even if external models are down.
   - MCP `search_apis` returns `MODEL_SERVICE_UNAVAILABLE` error, while other tools remain active.
   - **Validation Invariant**: Setting `allow_catalog_only_startup: true` with `fail_on_service_unavailable: true` is an invalid configuration state rejected by Pydantic validators.
