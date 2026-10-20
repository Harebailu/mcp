# Architecture Documentation: `pm_mcp_server`

## 1. Overview

`pm_mcp_server` is a metadata-driven Python Model Context Protocol (MCP) server designed to integrate an AI agent with an existing ASP.NET Core/.NET application.

Instead of registering hundreds of static, individual MCP tools (one per endpoint), `pm_mcp_server` provides four generic, metadata-driven tools backed by a dynamic runtime registry:
1. `search_apis`: The primary discovery tool for finding candidates using business terms.
2. `get_api_schema`: Retrieves technical contracts and business descriptions for a specific operation.
3. `execute_api`: Validates inputs and safely executes an approved read-only operation.
4. `list_all_apis`: A secondary, paginated fallback catalog browser for when search is insufficient.

```
                      +-----------------------------+
                      |          AI Agent           |
                      +-----------------------------+
                                     |
                                     | MCP Transport (Streamable HTTP / SSE)
                                     v
+-------------------------------------------------------------------------+
|                              pm_mcp_server                              |
|                                                                         |
|  +--------------------+   +--------------------+   +-----------------+  |
|  |    search_apis     |   |   get_api_schema   |   |  list_all_apis  |  |
|  +--------------------+   +--------------------+   +-----------------+  |
|            |                        |                       |           |
|            v                        v                       v           |
|  +--------------------+   +--------------------+   +-----------------+  |
|  |  ApiSearchService  |   |  ApiSchemaService  |   |   ApiRegistry   |  |
|  +--------------------+   +--------------------+   +-----------------+  |
|            \                        |                       /           |
|             \                       |                      /            |
|              v                      v                     v             |
|  +-------------------------------------------------------------------+  |
|  |                  Validated Runtime ApiRegistry                    |  |
|  |  Composite Key: (endpoint_name, METHOD)                           |  |
|  |  - YAML Catalog (Business metadata, dependencies, approvals)       |  |
|  |  - OpenAPI Contract (Parameters, request/response schemas)        |  |
|  +-------------------------------------------------------------------+  |
|                                     ^                                   |
|                                     |                                   |
|  +-------------------------------------------------------------------+  |
|  |                           execute_api                             |  |
|  |  1. Registry resolution (endpoint_name, method)                   |  |
|  |  2. Read-Only Policy enforcement (GET, approved, read_only)       |  |
|  |  3. OpenAPI contract argument validation (types, required, enum)   |  |
|  |  4. Inbound JWT Expiration Check (exp claim only)                 |  |
|  |  5. Trusted URL path construction (from YAML path)                |  |
|  +-------------------------------------------------------------------+  |
|                                     |                                   |
|                                     v                                   |
|  +-------------------------------------------------------------------+  |
|  |                 DotNetApiClient (HTTP Adapter)                    |  |
|  |  - Connection pooling, timeout, response byte cap, safe headers    |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
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
| `catalog/` | YAML catalog loader (`yaml_loader.py`), OpenAPI specification discovery/loader (`openapi_loader.py`), validation engine (`catalog_validator.py`), runtime registry (`registry.py`), and synchronization logic (`sync_from_openapi.py`). |
| `security/` | Token expiration claim verification (`token_expiry.py`) and non-sensitive request context tracking (`request_context.py`). |
| `policies/` | Strict read-only policy enforcement (`read_only.py`). Requires explicit operation approval and read-only access mode. |
| `adapters/` | Reusable asynchronous HTTP adapter (`dotnet_api_client.py`) managing downstream communication, URL construction, timeouts, and response limits. |
| `services/` | Decoupled business logic: API search abstraction (`api_search_service.py`), schema resolution (`api_schema_service.py`), execution orchestration (`api_execution_service.py`), and dependency metadata resolution (`dependency_service.py`). |
| `tools/` | Generic MCP tool definitions (`search_apis`, `get_api_schema`, `execute_api`, `list_all_apis`). |
| `server/` | Application assembly, lifecycle coordinator (`lifecycle.py`), transport runner (`transport.py`), and entrypoint (`app.py`). |

---

## 3. API Identity: Composite Key `(endpoint_name, method)`

In strict adherence to requirements, `pm_mcp_server` **does not generate synthetic API IDs, UUIDs, or slug identifiers**.
Every operation is uniquely addressed by its tuple:
```python
(endpoint_name, method)
```
- `endpoint_name`: A stable name derived either from OpenAPI `operationId` or from the HTTP method and path segments (e.g., `GetApiSuperusers`).
- `method`: Normalized uppercase HTTP method (e.g., `GET`, `POST`).

This composite key is used uniformly across the catalog, search results, schema queries, execution commands, dependency links, and validation logs.

---

## 4. Contract Ownership: OpenAPI vs. YAML

`pm_mcp_server` maintains a strict separation of concerns between technical contracts and business metadata:

1. **OpenAPI owns the technical contract**:
   - Operation paths and supported HTTP verbs.
   - Parameter names, locations (`path`, `query`), types, formats, defaults, and enums.
   - Request body schemas and required JSON fields.
   - Response status codes and payload schemas.
   - Schema dereferencing (`$ref`).

2. **YAML owns the business integration metadata**:
   - Canonical `endpoint_name` and display name.
   - Domain categorization.
   - Natural language business descriptions, `use_when`, and `avoid_when`.
   - Synonyms, keywords, and abbreviations for discovery.
   - Parameter and response field explanations.
   - Upstream API relationships (`dependent_apis`).
   - Operational enablement (`enabled: true/false`), approval status (`approved`, `pending_review`), and access mode (`read_only`).

---

## 5. Request Lifecycle

1. **Discovery (`search_apis`)**:
   - Agent submits natural language query.
   - `ApiSearchService` delegates to `YamlKeywordSearchBackend` (or future RAG).
   - Candidate endpoints with relevance scores, summaries, and dependency flags are returned.

2. **Schema Inspection (`get_api_schema`)**:
   - Agent passes `(endpoint_name, method)`.
   - `ApiSchemaService` retrieves the technical OpenAPI schema merged with YAML business documentation.
   - If `dependent_apis` are declared, input/output mappings are returned.

3. **Execution (`execute_api`)**:
   - Agent passes `(endpoint_name, method)` along with `path_params`, `query_params`, and optional `body`.
   - The execution service executes the validation pipeline:
     1. Verifies entry exists in `ApiRegistry`.
     2. Enforces `read_only_policy` (checks HTTP verb, `access_mode == 'read_only'`, `enabled == True`, `approval_status == 'approved'`).
     3. Validates parameters against OpenAPI contract (missing required arguments, unexpected arguments, type/enum mismatches).
     4. Validates inbound JWT expiration.
     5. Builds safe path and query string using trusted catalog paths and parameterized encoding.
     6. Delegates execution to `DotNetApiClient`.
     7. Enforces timeout, max response size, and parses structured response.

