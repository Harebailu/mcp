# Security Documentation: `pm_mcp_server`

## 1. Security Architecture Principles

`pm_mcp_server` is designed around defense-in-depth, explicit privilege granting, and strict boundary controls:

1. **Zero Trust Towards Model Arguments**:
   - The AI agent is never permitted to specify target URLs, base URLs, or arbitrary HTTP headers.
   - All outgoing URLs are strictly constructed by combining the trusted base URL from configuration with validated path templates from `api_catalog.yaml`.
2. **Server-Side Enforcement**:
   - Client-side checks are never relied upon.
   - The server enforces argument type validation, required parameter checks, enum membership, unexpected argument rejection, and read-only policies at execution time.
3. **Downstream Authentication Remains in .NET**:
   - Downstream authentication and authorization are managed by the .NET API layer.
   - Inbound MCP credentials are **never forwarded** blindly to the .NET API.
4. **Information Leakage Prevention**:
   - Errors returned to tools contain safe machine-readable error codes (`schemas/errors.py`) without leaking internal stack traces, system paths, or credential strings.

---

## 2. Inbound JWT Expiration Check

### Scope and Exact Limitations
For the initial implementation, `pm_mcp_server` performs an **expiration-claim check only** (`security/token_expiry.py`):

> [!WARNING]
> **CRITICAL SECURITY DISTINCTION**:
> Checking the `exp` claim without cryptographic signature verification **does not authenticate the token's issuer, verify authenticity, or prove the token has not been forged or tampered with**.
> It is strictly an expiration-claim sanity check. The downstream ASP.NET Core API remains the sole authority for validating signatures, issuers, audiences, scopes, and user roles.

### Behavior:
1. Extracts Bearer token from the MCP transport / Authorization header.
2. Unpacks the JWT payload without verifying cryptographic signatures.
3. Checks for presence of the configured expiration claim (`exp`).
4. Rejects tokens where `exp < current_utc - clock_skew_seconds` with `TOKEN_EXPIRED`.
5. Rejects malformed, missing, or unparseable tokens (`TOKEN_MISSING`, `TOKEN_MALFORMED`, `TOKEN_UNPARSEABLE`).
6. Evaluates all timestamps in UTC.
7. Logs or returns no token secrets or sensitive claims.

---

## 3. Read-Only Policy Enforcement

The server enforces an independent, hard-coded read-only safety policy in `policies/read_only.py`.

Before any API request is dispatched:
1. **HTTP Method Filter**: The HTTP method must be in `{"GET", "HEAD", "OPTIONS"}`. Any `POST`, `PUT`, `DELETE`, or `PATCH` request is immediately rejected with `READ_ONLY_VIOLATION`.
2. **Catalog Access Mode Check**: The catalog entry's `access_mode` attribute must be `"read_only"`.
3. **Explicit Enablement Check**: The entry must have `enabled: true`.
4. **Explicit Approval Check**: The entry must have `approval_status: "approved"`.
5. **Body Prohibition**: Sending a JSON body to a read-only endpoint that does not specify a request body contract is rejected with `BODY_NOT_PERMITTED`.

These rules prevent unauthorized or legacy endpoints with side effects from being executed even if their HTTP verb is `GET`.

---

## 4. Downstream Credentials Handling

- Inbound MCP JWTs are **never forwarded** to the .NET application.
- If the downstream .NET API requires authentication, a dedicated, explicitly configured server-to-server credential (e.g., API key or mTLS) must be configured in `dotnet_api` settings.
- If downstream credentials are absent and required by an endpoint, the request fails safely with an explicit upstream 401 error message rather than attempting a bypass.

