"""Mock reranker provider for local development and workflow verification.

Evaluates candidates using deterministic feature scoring over query tokens and candidate metadata.
Preserves exact (endpoint_name, method) identities.
"""

from __future__ import annotations

import re
from typing import Optional

from schemas.catalog import CatalogEntry
from search.reranking.base import BaseRerankerProvider


class MockRerankerProvider(BaseRerankerProvider):
    """Deterministic mock candidate reranker."""

    def __init__(
        self,
        model_name: Optional[str] = "mock-reranker-v1",
    ) -> None:
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> Optional[str]:
        return self._model_name

    @property
    def is_mock(self) -> bool:
        return True

    async def rerank(
        self,
        query: str,
        candidates: list[tuple[CatalogEntry, float]],
    ) -> list[tuple[CatalogEntry, float]]:
        """Rerank candidates deterministically using candidate semantic features."""
        if not candidates:
            return []

        query_terms = [t for t in re.split(r"\s+", query.strip().lower()) if len(t) > 1]
        scored_candidates: list[tuple[CatalogEntry, float]] = []

        for idx, (entry, semantic_score) in enumerate(candidates):
            # Compute a blended score combining initial vector rank, text match, and description depth
            feature_score = 0.0

            text_corpus = (
                f"{entry.endpoint_name} {entry.display_name} {entry.description} "
                f"{' '.join(entry.use_when or [])} {' '.join(entry.abbreviations or [])} {entry.domain or ''}"
            ).lower()

            # Overlap bonus
            for term in query_terms:
                if term in text_corpus:
                    feature_score += 0.2

            # Normalize blended score into [0.0, 1.0]
            blended = (semantic_score * 0.5) + (min(feature_score, 0.5))
            # Round score for clean output
            final_score = round(min(max(blended, 0.05), 0.99), 3)

            scored_candidates.append((entry, final_score))

        # Sort descending by rerank score
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        return scored_candidates

    async def check_readiness(self) -> bool:
        """Mock reranker is always ready locally."""
        return True

