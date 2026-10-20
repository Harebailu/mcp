# Security Architecture & Policies: `mcp_server`

## 1. Security Overview

`mcp_server` (production service: `pm-mcp-server`) sits between an AI Agent and an existing ASP.NET Core/.NET backend. Its primary security responsibilities are:
- Server-side read-only policy enforcement.
- Inbound MCP JWT expiration-claim verification.
- Sensitive credential isolation.
- Structured JSON logging with strict secret and token masking.
- Prevention of arbitrary path traversal and injection.

---

## 2. Inbound MCP JWT Validation

### 2.1 Scope & Security Limitation
The inbound MCP JWT validation checks **only the `exp` claim** to verify that the token has not expired.
- **Critical Limitation**: It does **not** verify the cryptographic signature, issuer (`iss`), audience (`aud`), or subject roles.
- Checking `exp` without cryptographic signature verification does not prove authenticity or authenticity of the issuer. It is solely a freshness sanity check.
- The downstream ASP.NET Core API layer remains the sole and final authority for downstream authentication, authorization, and permission enforcement.

### 2.2 Token Handling
- Inbound MCP bearer tokens are parsed to extract claims for the request context.
- Inbound tokens are **never forwarded** blindly to downstream APIs.
- Tokens are never logged in plain text.

---

## 3. Server-Side Read-Only Policy

To prevent unauthorized mutating operations from executing:
1. **Allowed Methods**: Only `GET`, `HEAD`, and `OPTIONS` are allowed. Mutating methods (`POST`, `PUT`, `DELETE`, `PATCH`) are rejected before execution.
2. **Access Mode**: Catalog entry must have `access_mode: "read_only"`.
3. **Approval Status**: Catalog entry must have `approval_status: "approved"`.
4. **Enablement**: Catalog entry must have `enabled: true`.
5. **No Blind Execution**: All arguments are validated against the OpenAPI contract parameters (location, type, required fields, and enums).

---

## 4. Observability & Redaction Standards

All logs are emitted as single-line JSON to `stdout`. The logging subsystem automatically filters and redacts:
- Authorization headers (`Bearer [REDACTED]`).
- Fields named `token`, `secret`, `password`, `api_key`, `access_token`, `refresh_token`.
- Full request bodies are omitted from logs.
