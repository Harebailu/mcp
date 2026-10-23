# Configuration Reference: `mcp_server`

`mcp_server` uses strongly typed configuration via Pydantic v2. Non-sensitive settings are loaded from `config/config.yaml`. Environment variables are strictly reserved for sensitive tokens and credentials.

---

## 1. Configuration Structure (`config/config.yaml`)

```yaml
application:
  name: "mcp_server"              # Production service name: "pm-mcp-server"
  environment: "development"      # "development" or "production"

instructions_file: "config/server_instructions.md"  # Path to external markdown instructions

api_client:
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
    base_url: null
    endpoint_path: null

  reranking:
    enabled: true
    provider: "ollama"            # "ollama" or "remote"
    model: "qwen:1.8b"
    required: true
    candidate_limit: 20
    timeout_seconds: 60
    base_url: null
    endpoint_path: null

  llm:
    enabled: false
    provider: null
    base_url: null
    endpoint_path: null
    model: null
    timeout_seconds: 20

  query_enrichment:
    enabled: false
    provider: "ollama"            # "ollama" or "remote_api"
    model: "qwen:1.8b"
    timeout_seconds: 30
    max_query_length: 2000
    max_alternative_queries: 2
    fail_open: true
    prompt_template: "query_enrichment"
    ollama:
      base_url: null              # Fallback to root ollama.base_url if null
      endpoint_path: "/api/chat"
    remote_api:
      base_url: null
      endpoint_path: "/v1/chat/completions"
      api_key_env_var: "QUERY_ENRICHMENT_API_KEY"
      model: null
      timeout_seconds: 30

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

## 2. Environment Variables & Secret Isolation Policy

In accordance with strict security architecture, **environment variables (`.env`) are reserved exclusively for sensitive tokens and credentials**. All non-sensitive configuration values (such as URLs, timeouts, transport types, model names, and ports) reside directly in `config/config.yaml`.

### Permitted Sensitive Environment Variables

| Environment Variable | Target Configuration Key | Purpose |
|---|---|---|
| `EMBEDDING_API_KEY` (or `MCP_EMBEDDING_API_KEY`) | `search.embedding.api_key` | Secret API key for remote embedding provider (production) |
| `RERANKER_API_KEY` (or `MCP_RERANKER_API_KEY`) | `search.reranking.api_key` | Secret API key for remote reranker provider (production) |
| `QUERY_ENRICHMENT_API_KEY` (or `MCP_QUERY_ENRICHMENT_API_KEY`) | `search.query_enrichment.remote_api.api_key` | Secret API key for remote query enrichment provider (production) |
| `API_BEARER_TOKEN` (or `MCP_API_KEY`) | `api_client.api_key` | Authorization token for downstream API communication |

> **No Backward Compatibility Layer**:
> All legacy prefixes (`PM_MCP_*`, `MCP_DOTNET_*`, `DotNetApiClient`) and backward compatibility translation layers have been removed. Configuration follows the clean, unified `mcp_server` structure.

---

## 3. Server Instructions (`instructions_file`)

The `instructions_file` setting specifies a markdown document (default: `config/server_instructions.md`) containing:
- High-level business module capabilities (e.g. Project Management, Administration, Authentication).
- Clear rules on when to search vs. list APIs.
- The four-step execution workflow (`search_apis` -> `get_api_schema` -> upstream dependency resolution -> `execute_api`).

At application startup, `mcp_server` reads this file and passes its contents directly to the `FastMCP` constructor. This cleanly decouples global agent instructions from individual catalog YAML files.

---

## 4. Operational Modes & Startup Invariants

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
