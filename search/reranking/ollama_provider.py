"""Ollama candidate reranker provider using local Qwen models (qwen:1.8b).

Sends search queries and candidate API summaries to Ollama for structured JSON
reranking. Strictly validates the output against the original candidate set so
the LLM cannot invent APIs or alter endpoint identities.
"""

from __future__ import annotations

import httpx

from observability.json_logging import get_logger
from schemas.catalog import CatalogEntry
from schemas.errors import ErrorCode, McpToolError
from search.prompts.rerank_prompt import format_reranking_prompt, parse_and_validate_ranking
from search.reranking.base import BaseRerankerProvider

_logger = get_logger("OllamaRerankerProvider")


class OllamaRerankerProvider(BaseRerankerProvider):
    """Reranks candidate APIs using Ollama and qwen:1.8b."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_name: str = "qwen:1.8b",
        timeout_seconds: int = 60,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._model_name = model_name.strip()
        self._timeout = float(timeout_seconds)

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def check_readiness(self) -> bool:
        """Verify reachability of Ollama and installation of the configured reranker model."""
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

                found = any(target == name or target_base == name.split(":")[0] for name in installed_names)
                if not found:
                    _logger.warning_event(
                        "Reranker model not found in Ollama installed models",
                        details={"required_model": self._model_name, "installed_models": installed_names},
                    )
                    return False

                return True

        except Exception as e:
            _logger.warning_event(
                "Ollama reranker readiness check failed",
                details={"error": str(e), "base_url": self._base_url},
            )
            return False

    async def rerank(
        self,
        query: str,
        candidates: list[tuple[CatalogEntry, float]],
    ) -> list[tuple[CatalogEntry, float]]:
        """Rerank candidates using Ollama qwen:1.8b and validate output."""
        if not candidates:
            return []

        # If only 1 candidate, it is unconditionally the top candidate
        if len(candidates) == 1:
            return [(candidates[0][0], 0.95)]

        prompt = format_reranking_prompt(query, candidates)
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model_name,
            "prompt": prompt,
            "format": "json",
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()

        except httpx.ConnectError as e:
            raise McpToolError.from_code(
                ErrorCode.RERANKER_SERVICE_UNAVAILABLE,
                f"Cannot connect to Ollama reranker service at {self._base_url}: {e}",
            ) from e
        except httpx.TimeoutException as e:
            raise McpToolError.from_code(
                ErrorCode.TIMEOUT,
                f"Ollama reranker request timed out after {self._timeout}s.",
            ) from e
        except Exception as e:
            raise McpToolError.from_code(
                ErrorCode.RERANKER_SERVICE_UNAVAILABLE,
                f"Ollama reranker request failed: {e}",
            ) from e

        response_text = data.get("response", "")
        # Parse and strictly validate ranking against original candidates
        reranked = parse_and_validate_ranking(response_text, candidates)
        return reranked
