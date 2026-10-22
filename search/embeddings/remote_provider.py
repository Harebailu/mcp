"""Remote HTTP client for real multilingual embedding model services.

Communicates with standard REST embedding services (e.g. OpenAI / TEI / vLLM / HuggingFace).
Configurable endpoint, timeout, headers, and batching.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from schemas.errors import ErrorCode, McpToolError
from search.embeddings.base import BaseEmbeddingProvider


class RemoteEmbeddingProvider(BaseEmbeddingProvider):
    """Remote embedding provider communicating over HTTP."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        endpoint_path: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env_var: str = "EMBEDDING_API_KEY",
        timeout_seconds: int = 20,
        batch_size: int = 32,
        dimensions: Optional[int] = None,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("base_url is required for RemoteEmbeddingProvider")

        self._base_url = base_url.strip().rstrip("/")
        self._model_name = model_name
        self._endpoint_path = (endpoint_path or "/v1/embeddings").strip().lstrip("/")
        self._api_key = api_key
        self._api_key_env_var = api_key_env_var
        self._timeout = float(timeout_seconds)
        self._batch_size = max(1, batch_size)
        self._dimensions = dimensions or 1536  # Default fallback if unknown

    @property
    def provider_name(self) -> str:
        return "remote"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _get_api_key(self) -> Optional[str]:
        """Read API token from explicit argument or configured environment variable."""
        return self._api_key or os.environ.get(self._api_key_env_var)

    def _get_headers(self) -> dict[str, str]:
        """Prepare request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        api_key = self._get_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _get_url(self) -> str:
        return f"{self._base_url}/{self._endpoint_path}"

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Batch embed multiple document strings."""
        if not texts:
            return []

        all_vectors: list[list[float]] = []

        # Process in batches
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            payload: dict[str, Any] = {
                "input": batch,
                "model": self._model_name,
            }

            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        self._get_url(),
                        json=payload,
                        headers=self._get_headers(),
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.ConnectError as e:
                raise McpToolError.from_code(
                    ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                    f"Cannot connect to remote embedding service at {self._base_url}: {e}",
                ) from e
            except httpx.TimeoutException as e:
                raise McpToolError.from_code(
                    ErrorCode.TIMEOUT,
                    f"Remote embedding request timed out after {self._timeout}s.",
                ) from e
            except httpx.HTTPStatusError as e:
                raise McpToolError.from_code(
                    ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                    f"Remote embedding service returned HTTP {e.response.status_code}.",
                    details={"status_code": e.response.status_code},
                ) from e
            except Exception as e:
                raise McpToolError.from_code(
                    ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                    f"Remote embedding call failed: {e}",
                ) from e

            # Parse standard OpenAI/TEI format: {"data": [{"embedding": [...]}, ...]}
            data_items = data.get("data", [])
            if not isinstance(data_items, list):
                raise McpToolError.from_code(
                    ErrorCode.INVALID_RESPONSE,
                    "Remote embedding service returned unexpected payload structure.",
                )

            for item in data_items:
                vec = item.get("embedding")
                if not isinstance(vec, list):
                    raise McpToolError.from_code(
                        ErrorCode.INVALID_RESPONSE,
                        "Missing 'embedding' array in service response.",
                    )
                all_vectors.append(vec)
                self._dimensions = len(vec)

        return all_vectors

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""
        results = await self.embed_documents([text])
        if not results:
            raise McpToolError.from_code(
                ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                "Embedding service returned empty response for query.",
            )
        return results[0]

    async def check_readiness(self) -> bool:
        """Verify reachability and readiness of the remote embedding service."""
        try:
            # Lightweight probe with a single test token
            async with httpx.AsyncClient(timeout=min(self._timeout, 5.0)) as client:
                resp = await client.post(
                    self._get_url(),
                    json={"input": "healthcheck", "model": self._model_name},
                    headers=self._get_headers(),
                )
                return resp.status_code in (200, 201)
        except Exception:
            return False

