"""Base reranker provider abstract class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from schemas.catalog import CatalogEntry


class BaseRerankerProvider(ABC):
    """Abstract base class for all candidate reranker providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider name."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> Optional[str]:
        """Model identifier."""
        ...

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[tuple[CatalogEntry, float]],
    ) -> list[tuple[CatalogEntry, float]]:
        """Rerank candidates based on semantic relevance to query.

        Args:
            query: The original search query.
            candidates: List of (CatalogEntry, initial_semantic_score) tuples.

        Returns:
            Reordered list of (CatalogEntry, rerank_score) tuples.
        """
        ...

    @abstractmethod
    async def check_readiness(self) -> bool:
        """Verify provider availability."""
        ...
