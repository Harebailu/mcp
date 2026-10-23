# Operational Runbook: `mcp_server`

`mcp_server` (production service: `pm-mcp-server`) runs on Python 3.11+ using the Model Context Protocol over Streamable HTTP or SSE.

---

## 1. Starting the Server

```bash
# Activate virtual environment
.venv\Scripts\activate

# Run with default config/config.yaml
python -m server.app

# Or run via registered entrypoint
mcp-server

# Or specify a custom config file
python -m server.app path/to/custom_config.yaml
```

Default HTTP endpoints:
- Host: `http://127.0.0.1:8000`
- Transport endpoint: `http://127.0.0.1:8000/mcp` (Streamable HTTP)

---

## 2. Operational Startup Modes

### Mode 1: Local Ollama Standard Mode
- Connects to local Ollama instance at `http://localhost:11434`.
- Uses `bge-m3:latest` for 1024-dimensional dense semantic retrieval.
- Uses `qwen:1.8b` for structured candidate reranking.
- Configuration in `config/config.yaml`:
  ```yaml
  ollama:
    base_url: "http://localhost:11434"
    timeout_seconds: 60
  search:
    embedding:
      provider: "ollama"
      model: "bge-m3:latest"
    reranking:
      provider: "ollama"
      model: "qwen:1.8b"
  startup_checks:
    check_ollama_service: true
    check_embedding_model: true
    check_reranking_model: true
    fail_on_service_unavailable: true
  ```

### Mode 2: Strict Mode (Fail-Fast)
- Required when search and reranking are mandatory for serving agent queries.
- If Ollama is unreachable or either model is missing, the server aborts startup immediately with a structured error log.
- Configuration in `config/config.yaml`:
  ```yaml
  startup_checks:
    fail_on_service_unavailable: true
    allow_catalog_only_startup: false
  ```

### Mode 3: Catalog-Only Resilience
- Intended for degraded scenarios where the downstream target API should remain accessible through `list_all_apis`, `get_api_schema`, and `execute_api` even if Ollama is temporarily offline.
- Configuration in `config/config.yaml`:
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
To force full re-vectorization, delete the cache directory contents:
```bash
Remove-Item -Path "cache/api_embeddings/*" -Force
```

---

## 4. Structured JSON Log Monitoring

Logs are written to `stdout` in single-line JSON format. Example line:
```json
{"timestamp": "2026-10-20T17:12:56.644876+00:00", "level": "INFO", "component": "SemanticSearchService", "event": "Vector index successfully built and ready", "duration_ms": 12395.96, "search_mode": "ollama", "candidate_count": 4}
```
