# Architecture Documentation: `pm_mcp_server`

## 1. System Overview

`pm_mcp_server` is a metadata-driven Python Model Context Protocol (MCP) server designed to integrate an AI agent with an existing ASP.NET Core/.NET application.

Instead of registering hundreds of static, individual MCP tools (one per endpoint), `pm_mcp_server` provides four generic, metadata-driven tools backed by a dynamic runtime registry and a two-stage multilingual retrieval engine:

1. `search_apis`: The primary discovery tool for finding candidates using multilingual semantic retrieval and reranking.
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
|                                 pm_mcp_server                                   |
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
|  [VectorIndex]   [Reranker]         |                          /                |
|      \             /                v                         v                 |
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
|   |                      DotNetApiClient (HTTP Adapter)                     |   |
|   |   - Managed connection pooling, timeout, response byte cap, safe headers|   |
|   +-------------------------------------------------------------------------+   |
+---------------------------------------------------------------------------------+
                                     |
                                     | HTTP Requests (Downstream Auth enforced by .NET)
                                     v
                      +-----------------------------+
                      |   ASP.NET Core / .NET API   |
                      +-----------------------------+
```

---

## 2. Component Structure and Responsibilities

| Component | Responsibility |
|---|---|
| `config/` | Strongly typed configuration loaded via Pydantic v2 from `config.yaml` with environment variable overrides. |
| `schemas/` | Typed models for catalog entries, OpenAPI parameters/operations, tool inputs, structured tool results, and machine-readable error codes. |
| `catalog/` | Manifest and domain file loader (`yaml_loader.py`), OpenAPI specification discovery/loader (`openapi_loader.py`), validation engine (`catalog_validator.py`), runtime registry (`registry.py`), read-only drift analyzer (`compare_catalog_with_openapi.py`), and sync utility (`sync_from_openapi.py`). |
| `search/` | Multilingual semantic search pipeline: normalized document generation (`document_builder.py`), embedding providers (`embeddings/`), rerankers (`reranking/`), vector indexing (`retrieval/vector_index.py`), persistent cache (`retrieval/embedding_cache.py`), and search service facade (`service.py`). |
| `observability/`| Structured single-line JSON logging to stdout (`json_logging.py`) with sensitive token and secret redaction. |
| `security/` | Inbound JWT expiration check (`token_expiry.py`) and request context propagation (`request_context.py`). |
| `policies/` | Strict read-only policy enforcement (`read_only.py`). Requires explicit operation approval, enabled status, and read-only access mode. |
| `adapters/` | Reusable asynchronous HTTP adapter (`dotnet_api_client.py`) managing downstream communication, URL construction, timeouts, and response limits. |
| `services/` | Decoupled business logic: schema resolution (`api_schema_service.py`), execution orchestration (`api_execution_service.py`), and dependency metadata resolution (`dependency_service.py`). |
| `tools/` | Generic MCP tool definitions (`search_apis`, `get_api_schema`, `execute_api`, `list_all_apis`). |
| `server/` | Application assembly, lifecycle coordinator (`lifecycle.py`), transport runner (`transport.py`), and CLI entrypoint (`app.py`). |

---

## 3. Multilingual Semantic Search & Reranking Architecture

### 3.1 Document Construction & Fingerprinting
Each catalog entry is converted to a normalized text representation for embedding via `SearchDocumentBuilder`.
Included fields:
- `endpoint_name`, `method`, `display_name`, `domain`
- `description`, `use_when`, `avoid_when`
- `input_descriptions`, `output_description`, `response_field_descriptions`
- `abbreviations`
- `dependent_apis` (purposes and endpoints)

**Cache Invalidation Boundary**:
Operational flags (`enabled`, `approval_status`, `access_mode`) are **strictly excluded** from document text and fingerprints. Toggling an endpoint's status takes effect immediately at runtime in the registry and vector index without invalidating the vector cache.

### 3.2 Two-Stage Retrieval Pipeline
1. **Stage 1: Dense Vector Retrieval**:
   - Query is embedded into dense vector space.
   - VectorIndex computes cosine similarity against candidate vectors.
   - In-memory runtime eligibility filter filters out unapproved, disabled, non-read-only, or non-GET endpoints.
   - Top candidates up to `candidate_limit` (default 20) are retrieved.
2. **Stage 2: Contextual Reranking**:
   - Retrieved candidates are reranked based on cross-encoder relevance scores.
   - Reranked candidates are returned with `relevance_score`, `semantic_score`, and `rerank_score`.

---

## 4. API Identity: Strict Composite Key `(endpoint_name, method)`

In accordance with system design requirements:
- No artificial numeric IDs, UUIDs, or slug identifiers are created.
- The composite key `(endpoint_name, method)` is used everywhere:
  - In YAML domain files.
  - In the runtime registry `ApiRegistry`.
  - In embedding cache files (`cache/api_embeddings/vectors.json`).
  - In MCP tool inputs and outputs.
