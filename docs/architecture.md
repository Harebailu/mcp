# Architecture Documentation: `mcp_server`

## 1. System Overview

`mcp_server` (production service: `pm-mcp-server`) is a metadata-driven Python Model Context Protocol (MCP) server designed to integrate an AI agent with downstream application APIs.

Instead of registering hundreds of static, individual MCP tools (one per endpoint), `mcp_server` provides four generic, metadata-driven tools backed by a dynamic runtime registry and a two-stage local Ollama retrieval engine:

1. `search_apis`: The primary discovery tool for finding candidates using multilingual semantic retrieval (`bge-m3:latest`) and candidate reranking (`qwen:1.8b`).
2. `get_api_schema`: Retrieves technical contracts and business descriptions for a specific operation.
3. `execute_api`: Validates inputs server-side and safely executes an approved read-only operation.
4. `list_all_apis`: A secondary, paginated fallback catalog browser for when search is insufficient.

```
                      +-----------------------------+
                      |          AI Agent           |
                      +-----------------------------+
                                     |
                                     | MCP Transport (Streamable HTTP / SSE)
                                     v
+---------------------------------------------------------------------------------+
|                                  mcp_server                                     |
|                                                                                 |
|  +--------------------+   +--------------------+   +-------------------------+  |
|  |    search_apis     |   |   get_api_schema   |   |      list_all_apis      |  |
|  +--------------------+   +--------------------+   +-------------------------+  |
|            |                        |                           |               |
|            v                        v                           v               |
|  +--------------------+   +--------------------+   +-------------------------+  |
|  | SemanticSearchSvc  |   |  ApiSchemaService  |   |       ApiRegistry       |  |
|  +--------------------+   +--------------------+   +-------------------------+  |
|      /             \                |                           /               |
|  [VectorIndex]   [Ollama Reranker]  |                          /                |
|  (bge-m3:latest)    (qwen:1.8b)     v                         v                 |
|   +-------------------------------------------------------------------------+   |
|   |                       Validated Runtime ApiRegistry                     |   |
|   |   Composite Key: (endpoint_name, METHOD)                                |   |
|   |   - YAML Domain Manifest & Domain Files (Business metadata, approvals)  |   |
|   |   - OpenAPI Contract (Parameters, request/response schemas)             |   |
|   +-------------------------------------------------------------------------+   |
|                                     ^                                           |
|                                     |                                           |
|   +-------------------------------------------------------------------------+   |
|   |                               execute_api                               |   |
|   |   1. Registry lookup via composite key (endpoint_name, method)          |   |
|   |   2. Read-Only Policy enforcement (GET, approved, read_only, enabled)   |   |
|   |   3. OpenAPI contract argument validation (types, required, enum)       |   |
|   |   4. Inbound JWT Expiration Check (exp claim only)                      |   |
|   |   5. Trusted URL path construction (from YAML path)                     |   |
|   +-------------------------------------------------------------------------+   |
|                                     |                                           |
|                                     v                                           |
|   +-------------------------------------------------------------------------+   |
|   |                        ApiClient (HTTP Adapter)                         |   |
|   |   - Managed connection pooling, timeout, response byte cap, safe headers|   |
|   +-------------------------------------------------------------------------+   |
+---------------------------------------------------------------------------------+
                                     |
                                     | HTTP Requests (Downstream Auth enforced by target API)
                                     v
                      +-----------------------------+
                      |    Downstream API Service   |
                      +-----------------------------+
```

---

## 2. Component Structure and Responsibilities

| Component | Responsibility |
|---|---|
| `config/` | Strongly typed configuration loaded via Pydantic v2 from `config.yaml`. Sensitive credentials (`EMBEDDING_API_KEY`, `RERANKER_API_KEY`, `API_BEARER_TOKEN`) reside exclusively in `.env`. Server instructions are loaded from `server_instructions.md`. |
| `schemas/` | Typed models for catalog entries, OpenAPI parameters/operations, tool inputs, structured tool results, and machine-readable error codes. |
| `catalog/` | Manifest and domain file loader (`yaml_loader.py`), OpenAPI specification discovery/loader (`openapi_loader.py`), validation engine (`catalog_validator.py`), runtime registry (`registry.py`), read-only drift auditor (`compare_catalog_with_openapi.py`), and sync utility (`sync_from_openapi.py`). |
| `search/` | Multilingual semantic search pipeline: normalized document generation (`document_builder.py`), Ollama embedding provider (`embeddings/ollama_provider.py`), prompt-driven reranker (`reranking/ollama_provider.py` & `prompts/rerank_prompt.py`), in-memory vector store (`retrieval/vector_index.py`), persistent cache (`retrieval/embedding_cache.py`), and search service facade (`service.py`). |
| `observability/`| Structured single-line JSON logging to stdout (`json_logging.py`) with sensitive token and secret redaction. |
| `security/` | Inbound JWT expiration check (`token_expiry.py`) and request context propagation (`request_context.py`). |
| `policies/` | Strict read-only policy enforcement (`read_only.py`). Requires explicit operation approval, enabled status, and read-only access mode. |
| `adapters/` | Reusable asynchronous HTTP adapter (`api_client.py`) managing downstream communication, URL construction, timeouts, and response limits. |
| `services/` | Decoupled business logic: schema resolution (`api_schema_service.py`), execution orchestration (`api_execution_service.py`), and dependency metadata resolution (`dependency_service.py`). |
| `tools/` | Generic MCP tool definitions (`search_apis`, `get_api_schema`, `execute_api`, `list_all_apis`). |
| `server/` | Application assembly, lifecycle coordinator (`lifecycle.py`), transport runner (`transport.py`), and CLI entrypoint (`app.py`). Injects system instructions into `FastMCP` from `config/server_instructions.md`. |

---

## 3. Server Instructions & Catalog Decoupling

To preserve the stability and integrity of the catalog YAML files:
- **Catalog YAMLs**: Focus strictly on API metadata, route paths, HTTP methods, business descriptions, input/output overviews, and dependency relationships. They do not store global agent system prompts or execution instructions.
- **Server Instructions (`config/server_instructions.md`)**: A dedicated markdown file containing detailed business domain overviews, capability descriptions, and the four-step execution workflow (`search_apis` -> `get_api_schema` -> dependency resolution -> `execute_api`).
- **Dynamic FastMCP Injection**: During server startup in `server/lifecycle.py`, the contents of `server_instructions.md` are read and passed directly into the `FastMCP` constructor as the server instructions.

---

## 4. Multilingual Semantic Search & Reranking Architecture

### 4.1 Document Construction & Fingerprinting
Each catalog entry is converted to a normalized text representation for embedding via `SearchDocumentBuilder`.
Included fields:
- `endpoint_name`, `method`, `display_name`, `domain`
- `description`, `use_when`, `avoid_when`
- `input_descriptions`, `output_description`, `response_field_descriptions`
- `abbreviations`
- `dependent_apis` (purposes and endpoints)

**Cache Invalidation Boundary**:
Operational flags (`enabled`, `approval_status`, `access_mode`) are **strictly excluded** from document text and fingerprints. Toggling an endpoint's status takes effect immediately at runtime in the registry and vector index without invalidating the vector cache.

### 4.2 Two-Stage Retrieval Pipeline
1. **Stage 1: Dense Vector Retrieval with `bge-m3:latest`**:
   - Query is embedded into 1024-dimensional dense vector space via Ollama.
   - VectorIndex computes unit-normalized cosine similarity against candidate vectors.
   - In-memory runtime eligibility filter filters out unapproved, disabled, non-read-only, or non-GET endpoints.
   - Top candidates up to `candidate_limit` (default 20) are retrieved.
2. **Stage 2: Contextual Reranking with `qwen:1.8b`**:
   - Retrieved candidates are sent with the search query to local Ollama `qwen:1.8b` using `search/prompts/rerank_template.txt`.
   - The model produces a structured JSON ranking.
   - Returned items are strictly validated against the original candidate set: no new APIs can be invented, and endpoint names / methods cannot be altered.
   - Returned candidates include `relevance_score`, `semantic_score`, and `rerank_score`.

---

## 5. API Identity: Strict Composite Key `(endpoint_name, method)`

In accordance with system design requirements:
- No artificial numeric IDs, UUIDs, or slug identifiers are created.
- The composite key `(endpoint_name, method)` is used everywhere:
  - In YAML domain files.
  - In the runtime registry `ApiRegistry`.
  - In embedding cache files (`cache/api_embeddings/vectors.json`).
  - In MCP tool inputs and outputs.
