"""Base embedding provider abstract class."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """Abstract base class for all embedding providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider name."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Embedding vector dimensions."""
        ...

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        """Whether this provider produces mock data."""
        ...

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Generate embedding for query string."""
        ...

    @abstractmethod
    async def check_readiness(self) -> bool:
        """Verify provider availability."""
        ...

