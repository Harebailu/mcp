# Operations Guide: `pm_mcp_server`

## 1. Prerequisites and Installation

- Python 3.11+
- Downstream ASP.NET Core API running (e.g. `http://localhost:5273`)

### Installation
From the project root (`pm_mcp_server/`):
```bash
pip install -r requirements.txt
```

---

## 2. Running the Server

### Default Execution (Streamable HTTP)
Using `python`:
```bash
python -m server.app
```
Or directly:
```bash
python server/app.py
```
Or with custom config path:
```bash
python server/app.py /path/to/custom_config.yaml
```

The server listens on `http://127.0.0.1:8000/mcp` by default.

### Running with STDIO Transport
For local CLI or direct LLM tool calling via pipe:
```bash
PM_MCP_TRANSPORT=stdio python -m server.app
```

---

## 3. Catalog Synchronization & Bootstrapping

To bootstrap or refresh `catalog/api_catalog.yaml` from the live Swagger UI:
```bash
python catalog/sync_from_openapi.py
```
This discovers the actual OpenAPI JSON, parses all operations, updates paths, preserves manually curated descriptions/dependencies, and outputs a summary of added/updated/removed APIs.

---

## 4. Connecting MCP Clients

### Connecting via Streamable HTTP
Clients supporting the remote Model Context Protocol can connect to:
```
http://127.0.0.1:8000/mcp
```
All four tools will be advertised:
1. `search_apis`
2. `get_api_schema`
3. `execute_api`
4. `list_all_apis`

### Client Discovery Workflow
1. The AI Agent initiates discovery with `search_apis(query="find superusers")`.
2. The agent inspects candidates returned in JSON format.
3. If search results are ambiguous or insufficient, the agent calls `list_all_apis(page=1)`.
4. The agent retrieves the full technical contract with `get_api_schema(endpoint_name="GetApiSuperusers", method="GET")`.
5. The agent executes the approved operation with `execute_api(endpoint_name="GetApiSuperusers", method="GET")`.

---

## 5. Troubleshooting and Diagnostics

| Symptom | Cause | Solution |
|---|---|---|
| `OPENAPI_UNREACHABLE` | Downstream Swagger UI URL cannot be reached | Check that the ASP.NET Core service is running and accessible at `dotnet_api.swagger_ui_url`. Verify Docker network or host routing. |
| `READ_ONLY_VIOLATION` | Attempted execution of POST/PUT/DELETE, or endpoint marked `read_write` | Only explicitly approved read-only operations with `access_mode: "read_only"` can be executed. |
| `UNAPPROVED_ENDPOINT` | Endpoint has `approval_status: "pending_review"` | Inspect `catalog/api_catalog.yaml` and change `approval_status: "approved"` and `enabled: true` after safety review. |
| `TOKEN_EXPIRED` | Inbound MCP Bearer token has expired | Refresh the JWT. Check `authentication.clock_skew_seconds` if minor clock drift exists between systems. |
| `RESPONSE_TOO_LARGE` / Truncated | Downstream response exceeds `max_response_bytes` | Increase `dotnet_api.max_response_bytes` in `config.yaml` if larger payloads are expected. |
| `TIMEOUT` | Downstream API did not respond within `timeout_seconds` | Adjust `dotnet_api.timeout_seconds` or optimize downstream database queries. |

