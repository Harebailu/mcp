"""Ollama embedding provider for local multilingual model services (bge-m3:latest).

Connects to the local Ollama instance over HTTP to generate 1024-dimensional dense
embeddings for catalog document indexing and user search queries.
Supports cross-lingual retrieval (e.g., Korean queries matching English API business metadata).
"""

from __future__ import annotations

import math
from typing import Any, Optional

import httpx

from observability.json_logging import get_logger
from schemas.errors import ErrorCode, McpToolError
from search.embeddings.base import BaseEmbeddingProvider

_logger = get_logger("OllamaEmbeddingProvider")


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """Generates embeddings using a local Ollama service and bge-m3."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_name: str = "bge-m3:latest",
        timeout_seconds: int = 60,
        batch_size: int = 32,
        dimensions: Optional[int] = 1024,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._model_name = model_name.strip()
        self._timeout = float(timeout_seconds)
        self._batch_size = max(1, batch_size)
        self._dimensions = dimensions or 1024

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def check_readiness(self) -> bool:
        """Verify that Ollama is reachable and the configured embedding model is installed."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code != 200:
                    _logger.warning_event(
                        "Ollama readiness probe returned non-200 status",
                        upstream_status=resp.status_code,
                    )
                    return False

                data = resp.json()
                models = data.get("models", [])
                installed_names = []
                for m in models:
                    if isinstance(m, dict):
                        name = m.get("name", "")
                        model_id = m.get("model", "")
                        if name:
                            installed_names.append(name.lower())
                        if model_id:
                            installed_names.append(model_id.lower())

                target = self._model_name.lower()
                target_base = target.split(":")[0]

                # Match full name (e.g. bge-m3:latest) or base name (bge-m3)
                found = any(target == name or target_base == name.split(":")[0] for name in installed_names)
                if not found:
                    _logger.warning_event(
                        "Embedding model not found in Ollama installed models",
                        details={"required_model": self._model_name, "installed_models": installed_names},
                    )
                    return False

                return True

        except Exception as e:
            _logger.warning_event(
                "Ollama readiness check failed with exception",
                details={"error": str(e), "base_url": self._base_url},
            )
            return False

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Batch generate embeddings for multiple catalog document texts."""
        if not texts:
            return []

        all_vectors: list[list[float]] = []

        # Process in batches
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]

            # Try /api/embed first (modern Ollama batch endpoint)
            batch_vectors = await self._embed_batch_via_embed_api(batch)
            if batch_vectors is None:
                # Fallback to single-prompt /api/embeddings endpoint
                batch_vectors = await self._embed_batch_via_embeddings_api(batch)

            all_vectors.extend(batch_vectors)

        return all_vectors

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""
        results = await self.embed_documents([text])
        if not results:
            raise McpToolError.from_code(
                ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                "Ollama embedding service returned empty response for query.",
            )
        return results[0]

    async def _embed_batch_via_embed_api(self, batch: list[str]) -> Optional[list[list[float]]]:
        """Attempt embedding generation using Ollama's /api/embed endpoint."""
        url = f"{self._base_url}/api/embed"
        payload: dict[str, Any] = {
            "model": self._model_name,
            "input": batch,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)

                if resp.status_code == 404:
                    # Endpoint not supported on this Ollama version, fallback to /api/embeddings
                    return None

                resp.raise_for_status()
                data = resp.json()

        except httpx.ConnectError as e:
            raise McpToolError.from_code(
                ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                f"Cannot connect to Ollama embedding service at {self._base_url}: {e}",
            ) from e
        except httpx.TimeoutException as e:
            raise McpToolError.from_code(
                ErrorCode.TIMEOUT,
                f"Ollama embedding request timed out after {self._timeout}s.",
            ) from e
        except httpx.HTTPStatusError as e:
            raise McpToolError.from_code(
                ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                f"Ollama embedding service returned HTTP {e.response.status_code}: {e.response.text}",
                details={"status_code": e.response.status_code},
            ) from e
        except Exception as e:
            raise McpToolError.from_code(
                ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                f"Ollama embedding call failed: {e}",
            ) from e

        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(batch):
            raise McpToolError.from_code(
                ErrorCode.INVALID_RESPONSE,
                f"Ollama /api/embed returned unexpected embedding count. Expected {len(batch)}, got {len(embeddings) if isinstance(embeddings, list) else 'non-list'}.",
            )

        validated_vectors: list[list[float]] = []
        for vec in embeddings:
            if not isinstance(vec, list):
                raise McpToolError.from_code(
                    ErrorCode.INVALID_RESPONSE,
                    "Malformed vector element in Ollama /api/embed response.",
                )
            # Update dimension dynamically if observed
            self._dimensions = len(vec)
            # Unit normalize vector for cosine similarity
            norm_vec = self._normalize_vector(vec)
            validated_vectors.append(norm_vec)

        return validated_vectors

    async def _embed_batch_via_embeddings_api(self, batch: list[str]) -> list[list[float]]:
        """Fallback embedding generation using Ollama's /api/embeddings endpoint (per-prompt)."""
        url = f"{self._base_url}/api/embeddings"
        vectors: list[list[float]] = []

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for text in batch:
                payload = {
                    "model": self._model_name,
                    "prompt": text,
                }
                try:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.ConnectError as e:
                    raise McpToolError.from_code(
                        ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                        f"Cannot connect to Ollama embedding service at {self._base_url}: {e}",
                    ) from e
                except httpx.TimeoutException as e:
                    raise McpToolError.from_code(
                        ErrorCode.TIMEOUT,
                        f"Ollama embedding request timed out after {self._timeout}s.",
                    ) from e
                except Exception as e:
                    raise McpToolError.from_code(
                        ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                        f"Ollama /api/embeddings request failed: {e}",
                    ) from e

                vec = data.get("embedding")
                if not isinstance(vec, list):
                    raise McpToolError.from_code(
                        ErrorCode.INVALID_RESPONSE,
                        "Missing 'embedding' list in Ollama response.",
                    )
                self._dimensions = len(vec)
                vectors.append(self._normalize_vector(vec))

        return vectors

    def _normalize_vector(self, vec: list[float]) -> list[float]:
        """Normalize vector to unit length for fast cosine similarity dot-product."""
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            return [x / norm for x in vec]
        return vec
