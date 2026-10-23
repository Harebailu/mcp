"""Ollama query enrichment provider using local Qwen models (qwen:1.8b).

Refines search queries in English and Korean using local Ollama instances.
Supports both /api/chat and /api/generate endpoints with structured JSON responses.
"""

from __future__ import annotations

import httpx

from observability.json_logging import get_logger
from schemas.errors import ErrorCode, McpToolError
from schemas.query_enrichment import QueryEnrichmentResult
from search.enrichment.base import BaseQueryEnrichmentProvider
from search.prompts.enrichment_prompt import (
    format_chat_messages,
    format_generate_prompt,
    parse_and_validate_enrichment,
)

_logger = get_logger("OllamaQueryEnrichmentProvider")


class OllamaQueryEnrichmentProvider(BaseQueryEnrichmentProvider):
    """Refines search queries using local Ollama models."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_name: str = "qwen:1.8b",
        endpoint_path: str = "/api/chat",
        timeout_seconds: int = 30,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._model_name = model_name.strip()
        self._endpoint_path = endpoint_path.strip()
        self._timeout = float(timeout_seconds)

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def check_readiness(self) -> bool:
        """Verify reachability of Ollama and installation of the query-enrichment model."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code != 200:
                    _logger.warning_event(
                        "Ollama query enrichment readiness probe returned non-200 status",
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
                        "Query enrichment model not found in Ollama installed models",
                        details={"required_model": self._model_name, "installed_models": installed_names},
                    )
                    return False

                return True

        except Exception as e:
            _logger.warning_event(
                "Ollama query enrichment readiness check failed",
                details={"error": str(e), "base_url": self._base_url},
            )
            return False

    async def enrich(
        self,
        query: str,
        max_alternatives: int = 2,
    ) -> QueryEnrichmentResult:
        """Call Ollama to refine the query and parse structured response."""
        is_chat = "chat" in self._endpoint_path.lower()
        url = f"{self._base_url}{self._endpoint_path}"

        if is_chat:
            payload = {
                "model": self._model_name,
                "messages": format_chat_messages(query, max_alternatives=max_alternatives),
                "format": "json",
                "stream": False,
            }
        else:
            payload = {
                "model": self._model_name,
                "prompt": format_generate_prompt(query, max_alternatives=max_alternatives),
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
                ErrorCode.MODEL_SERVICE_UNAVAILABLE,
                f"Cannot connect to Ollama query enrichment service at {self._base_url}: {e}",
            ) from e
        except httpx.TimeoutException as e:
            raise McpToolError.from_code(
                ErrorCode.TIMEOUT,
                f"Ollama query enrichment request timed out after {self._timeout}s.",
            ) from e
        except Exception as e:
            raise McpToolError.from_code(
                ErrorCode.MODEL_SERVICE_UNAVAILABLE,
                f"Ollama query enrichment request failed: {e}",
            ) from e

        if is_chat:
            response_text = data.get("message", {}).get("content", "")
        else:
            response_text = data.get("response", "")

        metadata = {
            "provider": "ollama",
            "model": self._model_name,
            "done": data.get("done", False),
            "eval_count": data.get("eval_count"),
        }

        return parse_and_validate_enrichment(
            raw_text=response_text,
            original_query=query,
            max_alternatives=max_alternatives,
            raw_metadata=metadata,
        )

