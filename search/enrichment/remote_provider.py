"""Remote HTTP client for production query enrichment services.

Sends user queries to standard REST model endpoints (e.g. OpenAI-compatible /
vLLM / HuggingFace TGI / custom gateways) using structured JSON output.
"""

from __future__ import annotations

import os
from typing import Any, Optional

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

_logger = get_logger("RemoteApiQueryEnrichmentProvider")


class RemoteApiQueryEnrichmentProvider(BaseQueryEnrichmentProvider):
    """Remote query enrichment service communicating over HTTP."""

    def __init__(
        self,
        base_url: str,
        model_name: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env_var: str = "QUERY_ENRICHMENT_API_KEY",
        timeout_seconds: int = 30,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("base_url is required for RemoteApiQueryEnrichmentProvider")

        self._base_url = base_url.strip().rstrip("/")
        self._model_name = model_name or "default"
        self._endpoint_path = (endpoint_path or "/v1/chat/completions").strip()
        if not self._endpoint_path.startswith("/"):
            self._endpoint_path = "/" + self._endpoint_path
        self._api_key = api_key
        self._api_key_env_var = api_key_env_var
        self._timeout = float(timeout_seconds)

    @property
    def provider_name(self) -> str:
        return "remote_api"

    @property
    def model_name(self) -> Optional[str]:
        return self._model_name

    def _get_api_key(self) -> Optional[str]:
        """Read API token from explicit argument or configured environment variable."""
        return self._api_key or os.environ.get(self._api_key_env_var)

    def _get_headers(self) -> dict[str, str]:
        """Prepare outbound request headers without exposing tokens in logs."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        api_key = self._get_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key.strip()}"
        return headers

    def _get_url(self) -> str:
        return f"{self._base_url}{self._endpoint_path}"

    async def check_readiness(self) -> bool:
        """Verify reachability of the remote query enrichment service."""
        try:
            url = f"{self._base_url}/health"
            headers = self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code in (200, 204):
                        return True
                except Exception:
                    pass

                # Fallback: test base URL reachability
                resp = await client.get(self._base_url, headers=headers)
                return resp.status_code < 500

        except Exception as e:
            _logger.warning_event(
                "Remote query enrichment readiness check failed",
                details={"error": str(e), "base_url": self._base_url},
            )
            return False

    async def enrich(
        self,
        query: str,
        max_alternatives: int = 2,
    ) -> QueryEnrichmentResult:
        """Execute query enrichment via remote HTTP endpoint."""
        url = self._get_url()
        headers = self._get_headers()

        is_chat = "chat" in self._endpoint_path.lower()
        if is_chat:
            payload: dict[str, Any] = {
                "model": self._model_name,
                "messages": format_chat_messages(query, max_alternatives=max_alternatives),
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }
        else:
            payload = {
                "model": self._model_name,
                "prompt": format_generate_prompt(query, max_alternatives=max_alternatives),
                "temperature": 0.2,
            }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

        except httpx.ConnectError as e:
            raise McpToolError.from_code(
                ErrorCode.MODEL_SERVICE_UNAVAILABLE,
                f"Cannot connect to remote query enrichment service at {self._base_url}: {e}",
            ) from e
        except httpx.TimeoutException as e:
            raise McpToolError.from_code(
                ErrorCode.TIMEOUT,
                f"Remote query enrichment request timed out after {self._timeout}s.",
            ) from e
        except Exception as e:
            raise McpToolError.from_code(
                ErrorCode.MODEL_SERVICE_UNAVAILABLE,
                f"Remote query enrichment request failed: {e}",
            ) from e

        # Extract text response from standard schemas
        response_text = ""
        if isinstance(data, dict):
            if "choices" in data and isinstance(data["choices"], list) and data["choices"]:
                choice = data["choices"][0]
                if isinstance(choice, dict):
                    msg = choice.get("message", {})
                    if isinstance(msg, dict):
                        response_text = msg.get("content", "")
                    elif "text" in choice:
                        response_text = choice.get("text", "")
            elif "response" in data:
                response_text = data["response"]
            elif "generated_text" in data:
                response_text = data["generated_text"]
            else:
                # Direct JSON dictionary
                import json
                response_text = json.dumps(data)
        elif isinstance(data, str):
            response_text = data

        metadata = {
            "provider": "remote_api",
            "model": self._model_name,
        }

        return parse_and_validate_enrichment(
            raw_text=response_text,
            original_query=query,
            max_alternatives=max_alternatives,
            raw_metadata=metadata,
        )

