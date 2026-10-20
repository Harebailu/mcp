# Operational Runbook: `pm_mcp_server`

## 1. Starting the Server

The server runs on Python 3.11+ using the MCP protocol over Streamable HTTP or SSE.

```bash
# Activate virtual environment
.venv\Scripts\activate

# Run with default config/config.yaml
python -m server.app

# Or specify a custom config file
python -m server.app path/to/custom_config.yaml
```

Default HTTP endpoints:
- Host: `http://127.0.0.1:8000`
- Transport endpoint: `http://127.0.0.1:8000/mcp` (Streamable HTTP)

---

## 2. Operational Startup Modes

### Mode A: Mock Development
- Suitable for local development and workflow verification without real model APIs.
- Configuration:
  ```yaml
  search:
    embedding:
      provider: "mock"
    reranking:
      provider: "mock"
  ```
- Output tag: Results from `search_apis` include `"search_mode": "mock"` and a clear warning banner.

### Mode B: Strict Remote
- Intended for production deployments with real multilingual embedding and reranking services.
- Configuration:
  ```yaml
  search:
    embedding:
      provider: "remote"
      base_url: "https://api.openai.com"
      model: "text-embedding-3-small"
  startup_checks:
    check_embedding_service: true
    fail_on_service_unavailable: true
    allow_catalog_only_startup: false
  ```
- Startup will fail fast if the embedding endpoint is unreachable.

### Mode C: Catalog-Only Resilience
- Intended for degraded scenarios where the downstream .NET API should remain accessible even if embedding services are temporarily down.
- Configuration:
  ```yaml
  startup_checks:
    fail_on_service_unavailable: false
    allow_catalog_only_startup: true
  ```
- The server starts normally. `search_apis` responds with `MODEL_SERVICE_UNAVAILABLE` guiding the agent to use `list_all_apis`. `get_api_schema` and `execute_api` operate normally.

---

## 3. Persistent Vector Cache Operations

- Directory: `cache/api_embeddings/`
- Manifest: `cache/api_embeddings/manifest.json`
- Vectors: `cache/api_embeddings/vectors.json`

### Cache Invalidation:
- Changing model name, provider, or vector dimensions automatically triggers cache invalidation and re-embedding.
- Modifying business descriptions or searchable text in a domain YAML file updates only the affected endpoint's vector.
- Toggling `enabled` or `approval_status` **does not** regenerate embeddings.

### Manual Cache Reset:
To force full re-vectorization, delete the files in `cache/api_embeddings/`:
```bash
Remove-Item -Path "cache/api_embeddings/*" -Force
```

---

## 4. Structured JSON Log Monitoring

Logs are written to `stdout` in JSON format. Example line:
```json
{"timestamp": "2026-10-20T09:31:54.654290+00:00", "level": "INFO", "component": "SemanticSearchService", "event": "Vector index successfully built and ready", "duration_ms": 30.07, "search_mode": "mock", "candidate_count": 4}
```

Key fields to monitor:
- `outcome`: `"success"`, `"tool_error"`, `"internal_error"`, `"cache_hit"`, `"cache_miss"`.
- `error_code`: Machine-readable error code if a failure occurred.
- `duration_ms`: Execution latency for tool operations.
