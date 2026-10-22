# MCP Server System Instructions & Business Capabilities

## 1. System Overview
You are connected to `mcp_server` (production service: `pm-mcp-server`), a generic metadata-driven Model Context Protocol (MCP) server.
This server provides structured, read-only discovery, technical contract inspection, and approved execution of downstream business APIs.

### Fundamental System Invariants:
- **API Identity:** Each API is uniquely identified by the composite key `(endpoint_name, method)` (for example: `("GetApiSuperusers", "GET")`).
- **Discovery First:** Always use `search_apis` with natural-language business queries to find the most relevant APIs. Use `list_all_apis` only as an enumeration fallback when search yields no suitable candidates.
- **Inspect Before Execution:** Never guess input parameters or response structures. Always call `get_api_schema` for the candidate `(endpoint_name, method)` to inspect the OpenAPI technical contract (path parameters, query parameters, types, enums, required fields, and response schemas).
- **Business Dependencies Only:** Transport-level authentication (Bearer tokens, login endpoints) is infrastructure and is **never** a business dependency. The `dependent_apis` field indicates upstream business entity relationships where an identifier (such as `projectId`) must be resolved from another business API before invoking the target API.
- **Server-Side Policy Enforcement:** Only operations that are explicitly marked `enabled: true`, `approval_status: approved`, and `access_mode: read_only` can be executed. Attempts to execute disabled, unapproved, or mutating endpoints will be blocked by server-side policies.

---

## 2. Business Modules and Capabilities Overview

The APIs exposed by this server are organized into distinct business modules. Review these module capabilities to understand which domain to target before searching or executing tools:

### Module 1: Project Management (PM)
- **Domain Identifier:** `project_management`
- **Module Purpose:**
  Provides end-to-end management, visibility, and tracking for enterprise projects, work packages, milestones, deliverables, and team allocations.
- **Key Business Capabilities:**
  - Project portfolio discovery, health monitoring, budget allocation, and status tracking.
  - Milestone scheduling, critical path tracking, deadline monitoring, and deliverable status reporting.
  - Work breakdown structure (WBS) inspection, task assignment verification, and progress reporting.
  - Project risk assessment and issue log auditing.
- **Available Operations:**
  Read-only query APIs for retrieving project summaries, milestone progress, task backlogs, deliverable deadlines, and risk registers.
- **When to Use:**
  Invoke APIs in this module when the user inquires about project health, deliverable timelines, milestone completion, budgets, or work allocations across teams.

### Module 2: Superuser Administration & Privileged Identity
- **Domain Identifier:** `superuser`
- **Module Purpose:**
  Provides administrative governance, account auditing, and identity inspection for system-level superusers and administrators.
- **Key Business Capabilities:**
  - Discovering and listing registered administrative superuser identities.
  - Inspecting administrator contact profiles, usernames, and email addresses.
  - Verifying administrative privilege levels for escalation and auditing workflows.
- **Available Operations:**
  Read-only query APIs (such as `GetApiSuperusers` via `GET /api/superusers`) to list administrative accounts and verify administrator profiles.
- **When to Use:**
  Invoke APIs in this module when verifying administrative accounts, conducting identity audits, or resolving administrator contact details. Do NOT use this module for standard tenant or regular user lookups.

### Module 3: Authentication & Session Governance
- **Domain Identifier:** `auth`
- **Module Purpose:**
  Governs credential verification, access token issuance, token refresh, and session termination.
- **Key Business Capabilities:**
  - User and administrator login and credential verification.
  - JWT bearer token distribution and session lifecycle management.
  - Session revocation and token invalidation.
- **Available Operations:**
  POST operations for credential authentication (`/api/auth/login`), token refresh (`/api/auth/refresh`), and session termination (`/api/auth/logout`).
- **When to Use:**
  Use these operations when explicit session authentication or token renewal is needed. Note: When querying standard business endpoints, downstream authentication is managed transparently at the transport layer.

---

## 3. Four-Step Agent Execution Workflow

Follow this systematic four-step procedure for every user request:

```
[Step 1: Discover] ──> search_apis(query="...", domain="...")
                           │
[Step 2: Inspect]  ──> get_api_schema(endpoint_name="...", method="...")
                           │
[Step 3: Resolve]  ──> Check dependent_apis (call upstream if required)
                           │
[Step 4: Execute]  ──> execute_api(endpoint_name="...", method="...", params={...})
```

### Step 1: Discover Candidates with `search_apis`
- Call `search_apis` with a natural-language query describing the business intent (e.g. `query="list all system administrators"` or `query="show active project milestones"`).
- Optionally specify a `domain` filter to narrow the search scope.
- Review candidate results: examine `display_name`, `description`, `use_when`, `avoid_when`, and `relevance_score`.

### Step 2: Retrieve Technical Contracts with `get_api_schema`
- For the selected candidate, call `get_api_schema(endpoint_name="...", method="...")`.
- Inspect the returned OpenAPI specification:
  - `parameters`: List of path and query parameters, their data types, formats, required flags, default values, and enum restrictions.
  - `responses`: HTTP status codes and response schemas (e.g., envelope structures, pagination metadata).
  - `dependent_apis`: Declared upstream business dependencies.

### Step 3: Resolve Upstream Dependencies
- If `dependent_apis` is non-empty, evaluate whether required parameters (such as `projectId` or `milestoneId`) are already known.
- If an identifier is missing, invoke the upstream API first using `execute_api` to obtain the required value.
- Map the upstream response field to the downstream parameter as indicated in `output_to_input`.

### Step 4: Execute Approved APIs with `execute_api`
- Call `execute_api` using the generic argument structure:
  - `endpoint_name`: The API identifier (e.g., `"GetApiSuperusers"`).
  - `method`: The HTTP method (e.g., `"GET"`).
  - `path_params`: Dictionary of path parameter substitutions (e.g., `{"projectId": "123"}`).
  - `query_params`: Dictionary of query parameters (e.g., `{"page": 1, "pageSize": 20}`).
- Verify that the execution returns `success: true` and interpret the `data` payload for the user.

