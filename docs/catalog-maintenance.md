# Catalog Maintenance Guide: `pm_mcp_server`

## 1. Catalog Architecture

The API inventory is maintained in `catalog/api_catalog.yaml`. It represents the curated business metadata, execution enablement status, and inter-API dependency graph.

### Key Principles
1. **Uniqueness**: Every entry is uniquely identified by the composite key `(endpoint_name, method)`. No numeric or UUID identifiers are generated or accepted.
2. **OpenAPI as Technical Authority**: Parameter types, locations, and schemas come from the discovered OpenAPI JSON document.
3. **YAML as Business & Policy Authority**: Business descriptions, use cases, domain categorization, dependencies, and approval states are maintained in YAML.
4. **Safety by Default**: Newly synchronized operations default to `enabled: false` and `approval_status: "pending_review"`. They cannot be executed until reviewed and approved.

---

## 2. Structure of a Catalog Entry

```yaml
catalog_version: "1.0"

apis:
  - endpoint_name: "GetApiSuperusers"
    method: "GET"
    path: "/api/superusers"
    domain: "superuser"
    display_name: "Get Superusers List"

    description: >
      Retrieves the list of registered superusers from AgriTracker.

    use_when:
      - "The agent or user needs to verify administrative privileges or list superusers."

    avoid_when:
      - "Normal user account inquiries."

    keywords:
      - "superusers"
      - "administrators"
      - "admin list"

    synonyms:
      - "admins"

    abbreviations:
      - "su"

    output_description: >
      Returns a list of superuser objects with their usernames and roles.

    dependent_apis: []

    enabled: true
    approval_status: "approved"
    access_mode: "read_only"
```

---

## 3. Catalog Synchronization & Refresh

`pm_mcp_server` includes an automated synchronization tool (`catalog/sync_from_openapi.py`) that syncs the YAML catalog against the live OpenAPI specification.

### Running Synchronization

From project root:
```bash
python catalog/sync_from_openapi.py
```

### Sync Rules:
1. **New Endpoints**: Added with `enabled: false` and `approval_status: "pending_review"`.
2. **Existing Endpoints**:
   - Manually curated business descriptions, `use_when`, `keywords`, and `dependent_apis` are **preserved**.
   - Changes to endpoint paths in OpenAPI are updated and flagged in the sync report.
3. **Removed Endpoints**: Endpoints present in YAML but absent in OpenAPI are preserved and highlighted in the sync report for human review.
4. **Endpoint Name Derivation**:
   - Uses `operationId` if present and unique across the specification.
   - If `operationId` is missing, generates a deterministic PascalCase name from HTTP method and path segments (e.g. `GET /api/superusers` -> `GetApiSuperusers`).
   - If an `operationId` is duplicated across distinct paths, disambiguates using path-derived names.

---

## 4. Modeling API Dependencies (`dependent_apis`)

When an endpoint requires a value produced by another endpoint (for example, a `projectId` or `jobId`), define this relationship in `dependent_apis`:

```yaml
dependent_apis:
  - endpoint_name: "SearchProjects"
    method: "GET"
    purpose: >
      Retrieve the project identifier required by this endpoint.
    output_to_input:
      "response.projectId": "path_params.projectId"
```

### Important Execution Rules:
- The server **does not automatically execute chains of dependent APIs**.
- The dependency graph is exposed via `search_apis` (hints) and `get_api_schema` (detailed guidance).
- The AI agent discovers the dependency, calls the upstream endpoint using `execute_api`, extracts the value, and subsequently calls the downstream target endpoint.
- Cycles in `dependent_apis` are detected during startup validation and prevent the server from starting.

---

## 5. Future Catalog Splitting

While the initial implementation uses a single canonical file `catalog/api_catalog.yaml`, the loader abstraction in `catalog/yaml_loader.py` is isolated so that domain splitting can be added seamlessly:
```
catalog/
├── api_catalog.yaml
└── domains/
    ├── projects.yaml
    ├── superusers.yaml
    └── jobs.yaml
```
The runtime `ApiRegistry` and MCP tools will continue using the identical composite key `(endpoint_name, method)` regardless of how YAML files are organized on disk.

