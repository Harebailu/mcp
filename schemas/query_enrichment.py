"""Typed schemas and language inference for bilingual query enrichment."""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field


def infer_query_language(text: str) -> str:
    """Infer the primary language of a search query.

    Inspects Korean Hangul unicode blocks vs Latin alphabetic characters.

    Returns:
        "ko" if query is predominantly or entirely Korean.
        "en" if query is predominantly or entirely English (Latin).
        "mixed" if query contains both Korean and Latin alphabetic tokens.
        "unknown" if query contains neither (e.g. only numbers, punctuation).
    """
    if not text or not text.strip():
        return "unknown"

    # Hangul Syllables, Jamo, and Compatibility Jamo
    hangul_pattern = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
    latin_pattern = re.compile(r"[a-zA-Z]")

    has_hangul = bool(hangul_pattern.search(text))
    has_latin = bool(latin_pattern.search(text))

    if has_hangul and has_latin:
        return "mixed"
    if has_hangul:
        return "ko"
    if has_latin:
        return "en"
    return "unknown"


class QueryEnrichmentResult(BaseModel):
    """Structured result from the bilingual query enrichment service."""

    original_query: str = Field(..., description="The exact user query as originally submitted")
    language: str = Field(default="unknown", description="Detected or inferred language ('en', 'ko', 'mixed', 'unknown')")
    enriched_query: str = Field(..., description="Refined query clarifying business intent")
    alternative_queries: list[str] = Field(
        default_factory=list,
        description="Bounded list of useful semantic alternative queries or cross-lingual equivalents",
    )
    raw_response: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional raw provider response metadata (excluding credentials)",
    )

    @property
    def all_unique_queries(self) -> list[str]:
        """Return a deduplicated list of non-empty queries to search, preserving order."""
        queries: list[str] = []
        # Original query is always preserved as a primary retrieval signal
        orig_clean = self.original_query.strip()
        if orig_clean:
            queries.append(orig_clean)

        enriched_clean = self.enriched_query.strip()
        if enriched_clean and enriched_clean not in queries:
            queries.append(enriched_clean)

        for alt in self.alternative_queries:
            alt_clean = alt.strip()
            if alt_clean and alt_clean not in queries:
                queries.append(alt_clean)

        return queries

