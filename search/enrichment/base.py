"""Base class for query enrichment providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from schemas.query_enrichment import QueryEnrichmentResult


class BaseQueryEnrichmentProvider(ABC):
    """Abstract base class for query enrichment providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the enrichment provider (e.g. 'ollama', 'remote_api')."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str | None:
        """Model identifier used for enrichment."""
        ...

    @abstractmethod
    async def enrich(
        self,
        query: str,
        max_alternatives: int = 2,
    ) -> QueryEnrichmentResult:
        """Refine and enrich a search query."""
        ...

    @abstractmethod
    async def check_readiness(self) -> bool:
        """Verify reachability and readiness of the provider."""
        ...

