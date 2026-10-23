"""Query enrichment service facade.

Orchestrates bilingual query refinement with provider invocation, input
validation, fail-open/fail-closed error handling, and structured JSON logging.
"""

from __future__ import annotations

import time
from typing import Optional

from observability.json_logging import get_logger
from schemas.errors import ErrorCode, McpToolError
from schemas.query_enrichment import QueryEnrichmentResult, infer_query_language
from search.protocols import QueryEnrichmentProvider

_logger = get_logger("QueryEnrichmentService")


class QueryEnrichmentService:
    """Service facade for bilingual query enrichment."""

    def __init__(
        self,
        provider: Optional[QueryEnrichmentProvider] = None,
        enabled: bool = False,
        fail_open: bool = True,
        max_query_length: int = 2000,
        max_alternative_queries: int = 2,
    ) -> None:
        self._provider = provider
        self._enabled = enabled
        self._fail_open = fail_open
        self._max_query_length = max_query_length
        self._max_alternative_queries = max_alternative_queries

    @property
    def is_enabled(self) -> bool:
        """Whether query enrichment is enabled."""
        return self._enabled

    @property
    def provider(self) -> Optional[QueryEnrichmentProvider]:
        """Underlying query enrichment provider."""
        return self._provider

    async def enrich_query(self, query: str) -> QueryEnrichmentResult:
        """Enrich and refine a user search query.

        Args:
            query: The user's input search query.

        Returns:
            QueryEnrichmentResult containing original query, detected language,
            enriched query, and optional alternative queries.

        Raises:
            McpToolError: If enrichment fails and fail_open is False.
        """
        clean_query = (query or "").strip()
        inferred_lang = infer_query_language(clean_query)

        # 1. Bypass when disabled, query is empty, or provider is missing
        if not self._enabled or not clean_query or self._provider is None:
            return QueryEnrichmentResult(
                original_query=clean_query,
                language=inferred_lang,
                enriched_query=clean_query,
                alternative_queries=[],
            )

        # 2. Enforce maximum query length limit
        if len(clean_query) > self._max_query_length:
            _logger.warning_event(
                "Query exceeds max_query_length; truncating for enrichment",
                details={
                    "original_length": len(clean_query),
                    "max_allowed": self._max_query_length,
                },
            )
            clean_query = clean_query[: self._max_query_length]

        start_time = time.perf_counter()

        _logger.info_event(
            "Query enrichment started",
            details={
                "provider": self._provider.provider_name,
                "model": self._provider.model_name,
                "inferred_language": inferred_lang,
            },
        )

        try:
            result = await self._provider.enrich(
                clean_query,
                max_alternatives=self._max_alternative_queries,
            )

            duration_ms = (time.perf_counter() - start_time) * 1000.0

            _logger.info_event(
                "Query enrichment completed",
                duration_ms=duration_ms,
                details={
                    "provider": self._provider.provider_name,
                    "model": self._provider.model_name,
                    "detected_language": result.language,
                    "variant_count": len(result.alternative_queries),
                    "enriched_modified": result.enriched_query != result.original_query,
                },
            )

            return result

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            _logger.error_event(
                "Query enrichment failed",
                duration_ms=duration_ms,
                details={
                    "provider": self._provider.provider_name,
                    "model": self._provider.model_name,
                    "error": str(e),
                    "fail_open": self._fail_open,
                },
            )

            if self._fail_open:
                _logger.warning_event(
                    "Fail-open policy active: proceeding with original query",
                    details={"original_query_length": len(clean_query)},
                )
                return QueryEnrichmentResult(
                    original_query=clean_query,
                    language=inferred_lang,
                    enriched_query=clean_query,
                    alternative_queries=[],
                )
            else:
                if isinstance(e, McpToolError):
                    raise
                raise McpToolError.from_code(
                    ErrorCode.MODEL_SERVICE_UNAVAILABLE,
                    f"Query enrichment failed and fail_open is disabled: {e}",
                ) from e

