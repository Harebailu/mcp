# `pm_mcp_server` — Generic Metadata-Driven Python MCP Server

A generic, metadata-driven Model Context Protocol (MCP) server written in Python to seamlessly integrate an AI Agent with an existing ASP.NET Core/.NET application.

`pm_mcp_server` eliminates endpoint-specific tool sprawl by exposing four generic MCP tools operating against a dynamic runtime registry combining OpenAPI technical specifications with domain-partitioned YAML business metadata, multilingual semantic retrieval, candidate reranking, persistent vector caching, and structured JSON observability.

---

## 1. Core Architecture and Responsibilities

Instead of generating separate MCP tools for 70+ to 300+ APIs, `pm_mcp_server` exposes four generic tools:

| MCP Tool | Primary Responsibility | Agent Usage Policy |
|---|---|---|
| `search_apis` | Multilingual semantic retrieval (vector similarity) + contextual candidate reranking. | **First Choice / Preferred**: Agents must ALWAYS try search first. |
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

## 3. Multilingual Semantic Search & Reranking Architecture

API search uses a two-stage retrieval pipeline:
1. **Stage 1 (Vector Similarity)**: Multilingual embedding model converts queries into dense vectors and matches against searchable catalog documents using cosine similarity. Supports cross-lingual matching (e.g., Korean user queries discovering English API business descriptions).
2. **Stage 2 (Candidate Reranking)**: Reranker refines the top candidate ordering based on semantic relevance and deep business context.
3. **Operational Eligibility Boundary**: Embeddings are calculated over searchable business metadata (`endpoint_name`, `display_name`, `description`, `use_when`, `avoid_when`, `input_descriptions`, `output_description`, `abbreviations`, `dependent_apis`). Operational status flags (`enabled`, `approval_status`, `access_mode`) are **strictly excluded** from document text and fingerprints. Status changes take effect immediately at runtime via in-memory eligibility filters without invalidating vector caches.
4. **Keyword Search Removal**: Keyword-based search and fields (`keywords`, `synonyms`) have been completely purged.

---

## 4. Persistent Embedding Cache

Embeddings are saved to disk under `cache/api_embeddings/` using safe atomic JSON serialization:
- Each catalog entry is fingerprinted via SHA-256 of its normalized searchable text.
- On startup, existing cached vectors with matching fingerprints and compatible model dimensions are reused instantly without re-embedding.
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

The server supports three operational modes configured in `config/config.yaml`:

- **Mode A (Mock Development)**: Uses deterministic mock embedding and reranking providers. Enables end-to-end local development, tool execution, and cache lifecycle testing without external API credentials.
- **Mode B (Strict Remote)**: Health-checks remote model endpoints during startup and fails fast if providers are unreachable.
- **Mode C (Catalog-Only Startup)**: When `allow_catalog_only_startup: true` and `fail_on_service_unavailable: false`, the server starts even if external embedding services are offline. `search_apis` returns a descriptive `MODEL_SERVICE_UNAVAILABLE` error, while `list_all_apis`, `get_api_schema`, and `execute_api` remain fully operational.

---

## 7. Structured JSON Observability

All operational logs are emitted to `stdout` as standardized, single-line JSON objects:
- Fields include `timestamp`, `level`, `component`, `event`, `tool_name`, `duration_ms`, `outcome`, `candidate_count`, and `details`.
- Sensitive tokens (`Authorization`, `token`, `password`, `secret`, `api_key`) and request bodies are strictly masked or redacted.

---

## 8. Security & Policy Enforcement

- **Inbound JWT Check**: Validates token expiration (`exp` claim) only. Checking `exp` without cryptographic signature verification does not verify token authenticity or issuer trust; downstream .NET services remain responsible for downstream authentication and authorization.
- **Credential Isolation**: Inbound MCP tokens are never forwarded to downstream APIs.
- **Read-Only Enforcement**: Server-side policy enforces `GET`/`HEAD`/`OPTIONS` verbs, `access_mode: "read_only"`, `enabled: true`, and `approval_status: "approved"`. All mutating verbs are rejected.

---

## 9. Quick Start

### Installation
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Run Server (Streamable HTTP on port 8000)
```bash
python -m server.app
```

### Inspect Catalog Drift against Live OpenAPI Spec
```bash
python catalog/compare_catalog_with_openapi.py
```
