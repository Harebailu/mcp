# Production Deployment Guide: `mcp_server` (Service: `pm-mcp-server`)

This document outlines configuration requirements, networking architecture, secret management, and operational best practices for deploying `mcp_server` to production environments.

---

## 1. Naming & Packaging Architecture

- **Code-level Package & Module Name**: `mcp_server` (retained across all code, imports, and package configuration).
- **Production Application / Service Display Name**: `pm-mcp-server` (used for deployment units, Kubernetes manifests, systemd service units, and monitoring dashboards).

---

## 2. Production Configuration Matrix

| Configuration Key | Local Development | Production Requirement | Description |
|---|---|---|---|
| `application.name` | `"mcp_server"` | `"pm-mcp-server"` | Production service/display identifier |
| `application.environment` | `"development"` | `"production"` | Enables production-grade policies and logs |
| `dotnet_api.base_url` | `http://localhost:5273` | `https://api.internal.domain` | Internal base URL of the deployed ASP.NET Core API |
| `dotnet_api.swagger_ui_url` | `http://localhost:5273/swagger/index.html` | `https://api.internal.domain/swagger/index.html` | Swagger UI location for contract verification |
| `dotnet_api.openapi_spec_url` | `null` | `https://api.internal.domain/swagger/v1/swagger.json` | Explicit verified OpenAPI specification URL |
| `dotnet_api.timeout_seconds` | `30` | `30` - `60` | Tuned to production network SLAs |
| `ollama.base_url` | `http://localhost:11434` | `http://ollama-service.internal:11434` | Accessible internal Ollama service hostname |
| `ollama.timeout_seconds` | `60` | `60` - `120` | Timeout accommodating model load and queue times |
| `search.embedding.model` | `"bge-m3:latest"` | `"bge-m3:latest"` | Must be pre-pulled in production Ollama instance |
| `search.reranking.model` | `"qwen:1.8b"` | `"qwen:1.8b"` | Must be pre-pulled in production Ollama instance |
| `startup_checks.fail_on_service_unavailable` | `true` | `true` (strict) / `false` (resilient) | Strict fail-fast when models are mandatory |
| `startup_checks.allow_catalog_only_startup` | `false` | `false` (strict) / `true` (resilient) | Allows catalog browsing when model service is down |
| `mcp.host` | `127.0.0.1` | `0.0.0.0` or container IP | Bind interface inside container / pod |
| `mcp.port` | `8000` | `8000` or per ingress spec | Internal container listening port |
| `mcp.transport` | `streamable_http` | `streamable_http` | Remote HTTP transport behind reverse proxy |
| `cache.directory` | `"cache/api_embeddings"` | `/var/cache/mcp_server/embeddings` | Persistent, writable volume mounted to container |
| `logging.level` | `"INFO"` | `"INFO"` or `"WARNING"` | Structured single-line JSON to stdout |

---

## 3. Network Topology & Container Networking

### Single-Host vs. Multi-Host Deployment
- **Same Host / Pod**: If `mcp_server` and Ollama run in the same pod (e.g., Kubernetes pod sidecar), `http://127.0.0.1:11434` can be used.
- **Separate Containers (Docker Compose)**: When running in separate Docker containers on a user-defined network, `localhost` inside the `mcp_server` container refers to that container itself, **not the host machine or the Ollama container**. Configure `ollama.base_url: "http://ollama:11434"`.
- **Kubernetes Separate Deployments**: Use Kubernetes cluster DNS: `http://ollama-service.mcp.svc.cluster.local:11434`.

### Ingress, TLS Termination & Perimeter Security
- **Never expose Ollama directly to untrusted public networks**. Ollama does not include authentication by default. Restrict Ollama network ingress exclusively to authorized application pods via Kubernetes NetworkPolicies or security groups.
- **MCP Server TLS**: Terminate HTTPS / TLS at the API Gateway or Ingress controller (e.g. NGINX, Traefik, AWS ALB) before forwarding traffic to `mcp_server` on port 8000.

---

## 4. Secret & Credential Management

- **No Inbound Secret Storage in Repository**: `.env` and configuration files in source control must contain zero secrets.
- **Environment Variable Ingestion**: Production secrets must be injected at runtime via environment variables or a secrets manager (e.g., Kubernetes Secrets, HashiCorp Vault, AWS Secrets Manager):
  - `MCP_DOTNET_API_KEY`: S2S token for downstream .NET API calls (if required).
  - `MCP_DOTNET_API_TOKEN`: Downstream authorization token (if required).
- **Inbound JWT Handling**: The MCP server inspects the `exp` claim of inbound tokens for freshness; downstream credentials remain isolated and managed by the .NET API layer.

---

## 5. Cache Persistence & Model Lifecycle

- **Persistent Volume Requirement**: Mount a persistent volume at `cache.directory` (`/var/cache/mcp_server/embeddings`). This prevents cold startup delays and re-embedding the entire catalog every time a container restarts.
- **Model Upgrades**: Updating `bge-m3:latest` to a different model or changing vector dimensions will automatically invalidate cached vectors and generate fresh embeddings using SHA-256 fingerprint verification.
- **Zero-Downtime Cache Warmup**: When performing significant catalog changes, pre-warm the cache during CI/CD staging before promoting images to production.

