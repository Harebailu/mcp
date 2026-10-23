"""Protocols and interfaces for the semantic search subsystem."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from schemas.catalog import CatalogEntry


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for generating document and query embedding vectors."""

    @property
    def provider_name(self) -> str:
        """Name of the embedding provider (e.g. 'ollama', 'remote')."""
        ...

    @property
    def model_name(self) -> str:
        """Configured multilingual embedding model identifier."""
        ...

    @property
    def dimensions(self) -> int:
        """Dimensionality of the embedding vectors."""
        ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a list of document texts."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Generate an embedding vector for a single search query."""
        ...

    async def check_readiness(self) -> bool:
        """Probe the embedding service to verify availability."""
        ...


@runtime_checkable
class RerankerProvider(Protocol):
    """Protocol for reranking candidate API results against the search query."""

    @property
    def provider_name(self) -> str:
        """Name of the reranker provider (e.g. 'ollama', 'remote')."""
        ...

    @property
    def model_name(self) -> str | None:
        """Model identifier for the reranker service."""
        ...

    async def rerank(
        self,
        query: str,
        candidates: list[tuple[CatalogEntry, float]],
    ) -> list[tuple[CatalogEntry, float]]:
        """Reorder and score the candidate set according to query relevance.

        Returns a list of (CatalogEntry, rerank_score) tuples sorted in descending order.
        """
        ...

    async def check_readiness(self) -> bool:
        """Probe the reranking service to verify availability."""
        ...


@runtime_checkable
class QueryEnrichmentProvider(Protocol):
    """Protocol for bilingual query enrichment providers."""

    @property
    def provider_name(self) -> str:
        """Name of the query enrichment provider (e.g. 'ollama', 'remote_api')."""
        ...

    @property
    def model_name(self) -> str | None:
        """Configured model identifier for query enrichment."""
        ...

    async def enrich(
        self,
        query: str,
        max_alternatives: int = 2,
    ) -> Any:
        """Refine and enrich a user search query.

        Args:
            query: User's original search query.
            max_alternatives: Maximum number of alternative queries to return.

        Returns:
            QueryEnrichmentResult containing original query, language,
            enriched query, and optional alternative queries.
        """
        ...

    async def check_readiness(self) -> bool:
        """Probe the model service to verify availability."""
        ...
