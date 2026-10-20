# Catalog Maintenance Guide: `pm_mcp_server`

## 1. Directory Structure

The API catalog is organized into domain-specific files referenced by a root manifest:

```
catalog/
├── api_catalog.yaml         # Root manifest
├── domains/
│   ├── superuser.yaml       # Superuser management operations
│   └── auth.yaml            # Authentication endpoints
├── catalog_validator.py     # Integrity validation engine
├── compare_catalog_with_openapi.py  # Read-only drift report tool
└── sync_from_openapi.py     # Bootstrap / sync utility
```

### Manifest Format (`catalog/api_catalog.yaml`)
```yaml
catalog_version: "1.0"
domain_files:
  - "domains/superuser.yaml"
  - "domains/auth.yaml"
```

### Domain File Format (`catalog/domains/<domain>.yaml`)
```yaml
domain: "superuser"
apis:
  - endpoint_name: "GetApiSuperusers"
    method: "GET"
    path: "/api/superusers"
    operation_id: null
    display_name: "Get Superusers"
    description: "Retrieve list of superuser accounts in the system."
    use_when:
      - "Admin requests information about superusers"
    avoid_when:
      - "Routine unprivileged user queries"
    abbreviations:
      - "su"
      - "admin"
    enabled: true
    approval_status: "approved"
    access_mode: "read_only"
```

---

## 2. Catalog Invariants & Validation Rules

1. **Composite Key Uniqueness**: `(endpoint_name, method)` must be unique across all domain files.
2. **Domain Inheritance**: Entries inherit the containing file's `domain` unless matching explicitly.
3. **Approval and Enablement**:
   - `enabled: true` is strictly permitted **only** when `approval_status: "approved"`.
   - `enabled: false` is required when `approval_status` is `pending_review` or `rejected`.
4. **Allowed Methods**: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, `OPTIONS`.
5. **Allowed Access Modes**: `read_only`, `read_write`.
6. **No Keywords/Synonyms**: Legacy `keywords` and `synonyms` fields are forbidden and rejected by the loader. Search is strictly multilingual semantic retrieval.

---

## 3. Drift Analysis (`compare_catalog_with_openapi.py`)

Run this read-only utility to compare the catalog against the live OpenAPI specification without making any file modifications:

```bash
python catalog/compare_catalog_with_openapi.py
```

The script reports:
- Number of matched operations.
- Operations present in OpenAPI but missing from catalog.
- Operations present in catalog but removed from OpenAPI.
- Path or method discrepancies.

---

## 4. Bootstrapping / Refreshing (`sync_from_openapi.py`)

To bootstrap a new catalog or update an existing inventory from live OpenAPI:
```bash
python catalog/sync_from_openapi.py
```
- Preserves all curated descriptions, use cases, and dependencies.
- Discovered endpoints default to `enabled: false`, `approval_status: "pending_review"`, and `access_mode: "read_only"`.
