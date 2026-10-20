# Configuration Reference: `pm_mcp_server`

`pm_mcp_server` loads non-secret application settings from `config/config.yaml` using Pydantic v2 schemas defined in `config/config.py`. Documented environment variables can override configuration values at runtime.

---

## 1. `config.yaml` Specification

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
  backend: "yaml_keyword"
  max_results: 5
  max_results_limit: 20

rag:
  enabled: false
  llm:
    provider: null
    base_url: null
    model: null
    api_key_env_var: "LLM_API_KEY"
    timeout_seconds: 20
  embeddings:
    provider: null
    base_url: null
    model: null
    dimensions: null
    api_key_env_var: "EMBEDDING_API_KEY"
    timeout_seconds: 20
  vector_store:
    provider: null
    collection_name: null
  retrieval:
    top_k: 5
    similarity_threshold: null

authentication:
  enabled: true
  expiration_claim: "exp"
  clock_skew_seconds: 0
```

---

## 2. Setting Details

### `application`
- `name` (str): Identifier for the server instance and MCP FastMCP service name.
- `environment` (str): Execution tier (`development`, `staging`, `production`).

### `dotnet_api`
- `base_url` (str): Downstream ASP.NET Core base URL. All outgoing requests are sent here.
- `swagger_ui_url` (str): Location of Swagger UI. Used to dynamically discover the actual OpenAPI JSON document URL.
- `openapi_spec_url` (str | null): Explicit override for the OpenAPI specification JSON URL. When set, bypasses Swagger UI discovery.
- `timeout_seconds` (int, default: 30): HTTP request timeout for calls to .NET.
- `max_response_bytes` (int, default: 1,048,576 [1MB]): Hard cap on downstream response payload to protect memory and client context.
- `max_redirects` (int, default: 3): Maximum HTTP redirects followed.

### `mcp`
- `host` (str): IP address for the remote HTTP server (`127.0.0.1` or `0.0.0.0`).
- `port` (int): Port for the remote HTTP MCP server (default: `8000`).
- `transport` (str): Remote transport mechanism (`streamable_http` or `stdio`).

### `search`
- `backend` (str): Search implementation to use. Currently supports `yaml_keyword`.
- `max_results` (int, default: 5): Default candidate count returned by `search_apis`.
- `max_results_limit` (int, default: 20): Maximum allowable limit for client query requests.

### `rag` (Future Extension - Currently Disabled)
- `enabled` (bool, must be `false` in initial version): If set to `true`, startup validation fails because RAG is not implemented in the initial release.
- Sub-sections `llm`, `embeddings`, `vector_store`, `retrieval`: Pre-defined configuration schema for seamless future RAG integration.

### `authentication`
- `enabled` (bool): Whether inbound JWT expiration checks are active.
- `expiration_claim` (str, default: `"exp"`): Claim name to inspect in the JWT payload.
- `clock_skew_seconds` (int, default: 0): Allowed time discrepancy in seconds when evaluating expiration.

---

## 3. Environment Variable Overrides

The following environment variables override settings in `config.yaml`:

| Environment Variable | Config Target | Type | Description |
|---|---|---|---|
| `PM_MCP_DOTNET_BASE_URL` | `dotnet_api.base_url` | String | Downstream API root |
| `PM_MCP_DOTNET_SWAGGER_URL` | `dotnet_api.swagger_ui_url` | String | Swagger UI HTML location |
| `PM_MCP_DOTNET_OPENAPI_URL` | `dotnet_api.openapi_spec_url` | String | Explicit OpenAPI JSON location |
| `PM_MCP_DOTNET_TIMEOUT` | `dotnet_api.timeout_seconds` | Integer | HTTP timeout |
| `PM_MCP_HOST` | `mcp.host` | String | MCP listen host |
| `PM_MCP_PORT` | `mcp.port` | Integer | MCP listen port |
| `PM_MCP_TRANSPORT` | `mcp.transport` | String | Transport mode |
| `PM_MCP_SEARCH_BACKEND` | `search.backend` | String | Search backend |
| `PM_MCP_AUTH_ENABLED` | `authentication.enabled` | Boolean | Enable/disable expiration check |
| `PM_MCP_CLOCK_SKEW` | `authentication.clock_skew_seconds` | Integer | Clock skew tolerance |

