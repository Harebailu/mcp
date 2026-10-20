"""Mock embedding provider for local development, control flow, and cache verification.

Produces deterministic unit-length vectors using content hashing.
CRITICAL LIMITATION: Mock vectors demonstrate lifecycle and API integration only;
they do NOT provide real semantic accuracy or true cross-lingual understanding.
All results generated through this provider are explicitly tagged with search_mode='mock'.
"""

from __future__ import annotations

import hashlib
import math
from typing import Optional

from search.embeddings.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic mock embedding provider."""

    def __init__(
        self,
        model_name: str = "mock-multilingual-embedding-v1",
        dimensions: int = 384,
    ) -> None:
        self._model_name = model_name
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def is_mock(self) -> bool:
        return True

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate deterministic unit-normalized pseudo-embeddings for documents."""
        return [self._generate_deterministic_vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        """Generate deterministic unit-normalized pseudo-embedding for query."""
        return self._generate_deterministic_vector(text)

    async def check_readiness(self) -> bool:
        """Mock provider is always available locally without remote network calls."""
        return True

    def _generate_deterministic_vector(self, text: str) -> list[float]:
        """Generate a deterministic unit-length vector derived from the input text."""
        # Use a combination of SHA-256 and MD5 seeds to produce predictable pseudo-random floats
        vector = []
        clean_text = text.strip().lower()
        if not clean_text:
            clean_text = "empty_document"

        # Expand text with character and token frequency hints
        tokens = clean_text.split()
        token_count = len(tokens)

        for i in range(self._dimensions):
            seed = f"{clean_text}:{i}:{token_count}".encode("utf-8")
            h = hashlib.sha256(seed).digest()
            # Convert first 4 bytes to an integer and map to [-1.0, 1.0]
            val = int.from_bytes(h[:4], "big", signed=True) / (2**31)
            vector.append(float(val))

        # Normalize to unit length for cosine similarity
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]
        else:
            vector[0] = 1.0

        return vector

