"""Remote HTTP client for real candidate reranking services.

Sends candidates and search query to standard REST reranking services
(e.g. Cohere / HuggingFace TEI reranker / BGE reranker).
Preserves exact (endpoint_name, method) identities.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from schemas.catalog import CatalogEntry
from schemas.errors import ErrorCode, McpToolError
from search.reranking.base import BaseRerankerProvider


class RemoteRerankerProvider(BaseRerankerProvider):
    """Remote candidate reranker communicating over HTTP."""

    def __init__(
        self,
        base_url: str,
        model_name: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env_var: str = "RERANKER_API_KEY",
        timeout_seconds: int = 20,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("base_url is required for RemoteRerankerProvider")

        self._base_url = base_url.strip().rstrip("/")
        self._model_name = model_name
        self._endpoint_path = (endpoint_path or "/v1/rerank").strip().lstrip("/")
        self._api_key = api_key
        self._api_key_env_var = api_key_env_var
        self._timeout = float(timeout_seconds)

    @property
    def provider_name(self) -> str:
        return "remote"

    @property
    def model_name(self) -> Optional[str]:
        return self._model_name

    def _get_api_key(self) -> Optional[str]:
        """Read API token from explicit argument or configured environment variable."""
        return self._api_key or os.environ.get(self._api_key_env_var)

    def _get_headers(self) -> dict[str, str]:
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

    async def rerank(
        self,
        query: str,
        candidates: list[tuple[CatalogEntry, float]],
    ) -> list[tuple[CatalogEntry, float]]:
        """Send candidate summaries to remote reranker and reorder results."""
        if not candidates:
            return []

        # Build documents list for reranker
        documents: list[str] = []
        for entry, _ in candidates:
            doc_summary = (
                f"{entry.display_name} ({entry.endpoint_name}). {entry.description}. "
                f"Domain: {entry.domain or ''}. "
                f"Use when: {'; '.join(entry.use_when or [])}."
            )
            documents.append(doc_summary)

        payload: dict[str, Any] = {
            "query": query,
            "documents": documents,
        }
        if self._model_name:
            payload["model"] = self._model_name

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
                ErrorCode.RERANKER_SERVICE_UNAVAILABLE,
                f"Cannot connect to remote reranker service at {self._base_url}: {e}",
            ) from e
        except httpx.TimeoutException as e:
            raise McpToolError.from_code(
                ErrorCode.TIMEOUT,
                f"Remote reranker request timed out after {self._timeout}s.",
            ) from e
        except httpx.HTTPStatusError as e:
            raise McpToolError.from_code(
                ErrorCode.RERANKER_SERVICE_UNAVAILABLE,
                f"Remote reranker service returned HTTP {e.response.status_code}.",
                details={"status_code": e.response.status_code},
            ) from e
        except Exception as e:
            raise McpToolError.from_code(
                ErrorCode.RERANKER_SERVICE_UNAVAILABLE,
                f"Remote reranker call failed: {e}",
            ) from e

        # Expect response format: {"results": [{"index": int, "relevance_score": float}, ...]}
        results = data.get("results")
        if not isinstance(results, list):
            raise McpToolError.from_code(
                ErrorCode.INVALID_RESPONSE,
                "Remote reranker returned unexpected response structure (missing 'results').",
            )

        reranked_candidates: list[tuple[CatalogEntry, float]] = []
        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score", 0.0)
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                entry = candidates[idx][0]
                reranked_candidates.append((entry, float(score)))

        # Sort descending by rerank score
        reranked_candidates.sort(key=lambda x: x[1], reverse=True)
        return reranked_candidates

    async def check_readiness(self) -> bool:
        """Verify reachability and readiness of remote reranker service."""
        try:
            async with httpx.AsyncClient(timeout=min(self._timeout, 5.0)) as client:
                payload = {"query": "healthcheck", "documents": ["sample"]}
                if self._model_name:
                    payload["model"] = self._model_name
                resp = await client.post(
                    self._get_url(),
                    json=payload,
                    headers=self._get_headers(),
                )
                return resp.status_code in (200, 201)
        except Exception:
            return False

