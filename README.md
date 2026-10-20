# `mcp_server` — Generic Metadata-Driven Python MCP Server

A generic, metadata-driven Model Context Protocol (MCP) server written in Python to integrate AI agents with an existing ASP.NET Core/.NET application.

`mcp_server` eliminates endpoint-specific tool sprawl by exposing four generic MCP tools operating against a dynamic runtime registry combining OpenAPI technical specifications with domain-partitioned YAML business metadata, local Ollama-powered multilingual semantic retrieval (`bge-m3:latest`), structured candidate reranking (`qwen:1.8b`), persistent vector caching, and structured JSON observability.

> **Production Deployment Identifier**: In production environments, the service/display identifier is **`pm-mcp-server`**, while the Python package and code-level project name remains **`mcp_server`**.

---

## 1. Core Architecture and Responsibilities

Instead of generating separate MCP tools for 70+ to 300+ APIs, `mcp_server` exposes four generic tools:

| MCP Tool | Primary Responsibility | Agent Usage Policy |
|---|---|---|
| `search_apis` | Multilingual semantic retrieval (vector similarity) via `bge-m3:latest` + contextual candidate reranking via `qwen:1.8b`. | **First Choice / Preferred**: Agents must ALWAYS try search first. |
| `get_api_schema` | Combines technical OpenAPI contract with YAML business documentation and dependency mappings. | Used after finding an API candidate to inspect required inputs. |
| `execute_api` | Enforces read-only policy, validates arguments server-side, checks JWT expiration, and executes the call. | Used to invoke an approved operation with validated arguments. |
| `list_all_apis` | Full-catalog paginated browser including unapproved and disabled endpoints. | **Fallback Only**: Used ONLY when search fails or is insufficient. |

```
AI Agent -> [search_apis] -> [get_api_schema] -> [execute_api] -> .NET API
                 |
                 +-> (if search insufficient) -> [list_all_apis]
```

---

## 2. API Identity: Composite Key `(endpoint_name, method)`

In accordance with strict system invariants:
- **No synthetic IDs, numeric IDs, or UUIDs are generated or used.**
- Every API is uniquely identified across the entire system by the composite tuple:
  ```python
  (endpoint_name, method)
  ```
- `endpoint_name`: Either the OpenAPI `operationId` or a deterministic PascalCase name derived from HTTP method and path segments (e.g. `GetApiSuperusers`).
- `method`: Normalized uppercase HTTP verb (e.g. `GET`, `POST`).

---

## 3. Local Ollama Integration (`bge-m3:latest` & `qwen:1.8b`)

API search uses a two-stage local retrieval and reranking pipeline with Ollama:

1. **Stage 1 (Vector Similarity via `bge-m3:latest`)**:
   - Computes 1024-dimensional dense vectors for catalog entries and user queries.
   - Enables cross-lingual matching (e.g., Korean user queries discovering English API business descriptions).
   - In-memory vector store performs unit-normalized cosine similarity ranking.
2. **Stage 2 (Candidate Reranking via `qwen:1.8b`)**:
   - Passes user queries and retrieved candidates to local `qwen:1.8b` using a structured reranking prompt template (`search/prompts/rerank_template.txt`).
   - Requires structured JSON output and strictly validates returned candidates against the original candidate set.
   - Prevents hallucinated APIs, modifications to endpoint names, or alterations to HTTP verbs.
3. **Operational Eligibility Boundary**:
   - Embeddings are computed strictly over business metadata (`endpoint_name`, `display_name`, `description`, `use_when`, `avoid_when`, `input_descriptions`, `output_description`, `abbreviations`, `dependent_apis`).
   - Operational status flags (`enabled`, `approval_status`, `access_mode`) are excluded from document text and fingerprints. Toggling status takes effect immediately at runtime without invalidating vector caches.
4. **No Mock Providers & No Keyword Search**:
   - All mock providers have been removed; retrieval connects to actual local Ollama models.
   - Keyword search and fields (`keywords`, `synonyms`) have been completely purged.

---

## 4. Persistent Embedding Cache

Embeddings are saved to disk under `cache/api_embeddings/` using safe atomic JSON serialization:
- Each catalog entry is fingerprinted via SHA-256 of its normalized searchable text.
- On startup, existing cached vectors with matching fingerprints and compatible model dimensions (1024 for `bge-m3:latest`) are reused instantly without re-embedding.
- Modified or new endpoints are incrementally embedded and updated atomically.

---

## 5. Domain-Based Catalog Organization

The catalog is split into modular domain files with a root manifest:
```
catalog/
├── api_catalog.yaml         # Manifest referencing domain files
├── domains/
│   ├── superuser.yaml       # Superuser management operations
│   └── auth.yaml            # Authentication endpoints
├── catalog_validator.py     # Integrity validation engine
├── compare_catalog_with_openapi.py  # Read-only contract comparison tool
└── sync_from_openapi.py     # Bootstrap / sync utility
```

- **Domain Inheritance**: Entries inherit the containing file's `domain` unless explicitly matching.
- **Status Invariant**: `enabled: true` is permitted **only** when `approval_status: "approved"`.
- **Directory Traversal Protection**: Domain file paths outside the catalog directory are rejected.

---

## 6. Startup Modes and Resilience

Configured in `config/config.yaml`:

- **Strict Mode** (`fail_on_service_unavailable: true`): Probes Ollama reachability and verifies that both `bge-m3:latest` and `qwen:1.8b` are installed; fails fast at startup if unavailable.
- **Catalog-Only Mode** (`allow_catalog_only_startup: true`, `fail_on_service_unavailable: false`): Server boots with valid catalog even if Ollama is offline. `search_apis` returns a descriptive `MODEL_SERVICE_UNAVAILABLE` error directing agents to `list_all_apis`, while `list_all_apis`, `get_api_schema`, and `execute_api` remain fully operational.

---

## 7. Structured JSON Observability

All operational logs are emitted to `stdout` as standardized, single-line JSON objects:
- Fields include `timestamp`, `level`, `component`, `event`, `tool_name`, `duration_ms`, `outcome`, `candidate_count`, and `details`.
- Sensitive tokens (`Authorization`, `token`, `password`, `secret`, `api_key`) and request bodies are strictly masked or redacted.

---

## 8. Quick Start

### Installation
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Ensure Ollama Models are Installed
```bash
ollama list
# Should display bge-m3:latest and qwen:1.8b
```

### Run Server (Streamable HTTP on port 8000)
```bash
python -m server.app
# Or via registered entrypoint:
mcp-server
```

### Inspect Catalog Drift against Live OpenAPI Spec
```bash
python catalog/compare_catalog_with_openapi.py
```

### Production Deployment
Refer to [`docs/production-deployment.md`](docs/production-deployment.md) for full production deployment instructions.
