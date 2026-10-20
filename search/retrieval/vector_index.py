"""In-memory vector index for cosine similarity candidate retrieval.

Indexes catalog entries with their embedding vectors and performs fast vector
similarity search with runtime eligibility filtering.
"""

from __future__ import annotations

import math
from typing import Optional

from schemas.catalog import CatalogEntry


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Calculate cosine similarity between two float vectors."""
    if len(vec_a) != len(vec_b):
        return 0.0

    dot_product = 0.0
    norm_a = 0.0
    norm_b = 0.0

    for a, b in zip(vec_a, vec_b):
        dot_product += a * b
        norm_a += a * a
        norm_b += b * b

    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0

    return dot_product / (math.sqrt(norm_a) * math.sqrt(norm_b))


class VectorIndex:
    """In-memory vector index for API document retrieval."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], CatalogEntry] = {}
        self._vectors: dict[tuple[str, str], list[float]] = {}

    def build_index(
        self,
        entries: list[CatalogEntry],
        vectors: dict[tuple[str, str], list[float]],
    ) -> None:
        """Populate the in-memory index with validated entries and vectors."""
        self._entries.clear()
        self._vectors.clear()

        for entry in entries:
            key = entry.composite_key
            if key in vectors:
                self._entries[key] = entry
                self._vectors[key] = vectors[key]

    def count(self) -> int:
        """Return total indexed vectors."""
        return len(self._vectors)

    def search(
        self,
        query_vector: list[float],
        candidate_limit: int = 20,
        domain_filter: Optional[str] = None,
        filter_eligible: bool = True,
    ) -> list[tuple[CatalogEntry, float]]:
        """Retrieve top API candidates matching the query vector.

        CRITICAL FILTERING RULE:
        Only entries eligible for search under current policy (enabled: true,
        approval_status: approved, access_mode: read_only, method: GET)
        are ranked. Disabled, pending-review, and non-GET entries are excluded
        and DO NOT consume candidate_limit.

        Args:
            query_vector: The embedding vector for the search query.
            candidate_limit: Maximum number of candidates to retrieve.
            domain_filter: Optional domain constraint.
            filter_eligible: Whether to enforce search eligibility filtering.

        Returns:
            List of (CatalogEntry, similarity_score) sorted descending by similarity.
        """
        if not self._vectors or not query_vector:
            return []

        scored_candidates: list[tuple[CatalogEntry, float]] = []

        for key, entry in self._entries.items():
            # Domain filter check
            if domain_filter:
                entry_domain = (entry.domain or "").lower()
                if entry_domain != domain_filter.lower():
                    continue

            # Strict runtime eligibility check: must be approved, enabled, read_only, and GET
            if filter_eligible and not entry.is_searchable:
                continue

            vector = self._vectors[key]
            sim = _cosine_similarity(query_vector, vector)
            # Bound similarity to [-1.0, 1.0] and round to 4 decimals
            score = round(max(-1.0, min(1.0, sim)), 4)
            scored_candidates.append((entry, score))

        # Sort descending by cosine similarity
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        return scored_candidates[:candidate_limit]

