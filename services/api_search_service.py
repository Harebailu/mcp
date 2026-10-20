"""API search service with pluggable backend architecture.

The search service provides an abstraction layer between the search_apis
MCP tool and the actual retrieval implementation.

Current implementation: YamlKeywordSearchBackend
- Exact, case-insensitive, and token-based matching
- Ranks results by relevance across multiple metadata fields
- Searches: endpoint names, display names, descriptions, use_when,
  avoid_when, keywords, synonyms, abbreviations, input/output descriptions,
  dependency descriptions

Future implementation: RAGSearchBackend (not implemented)
- Would use embeddings and vector retrieval
- Same interface, no tool changes needed
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Optional

from catalog.registry import ApiRegistry
from schemas.catalog import CatalogEntry
from schemas.tool_results import SearchResultEntry, SearchApisResult
from schemas.errors import ErrorCode, McpToolError


# ---------------------------------------------------------------------------
# Search backend protocol / interface
# ---------------------------------------------------------------------------

class SearchBackend(ABC):
    """Abstract interface for search backends."""

    @abstractmethod
    def search(
        self,
        query: str,
        registry: ApiRegistry,
        domain: Optional[str] = None,
        limit: int = 5,
    ) -> list[tuple[CatalogEntry, float]]:
        """Search the catalog and return scored results.

        Args:
            query: Natural-language search query.
            registry: The runtime API registry.
            domain: Optional domain filter.
            limit: Maximum number of results.

        Returns:
            List of (CatalogEntry, score) tuples, sorted by relevance.
        """
        ...


# ---------------------------------------------------------------------------
# YAML keyword search backend
# ---------------------------------------------------------------------------

class YamlKeywordSearchBackend(SearchBackend):
    """Simple keyword-based search over YAML catalog metadata.

    Scoring approach:
    - Exact match on endpoint_name: highest weight
    - Exact match on display_name: high weight
    - Token matches in description, keywords, synonyms: medium weight
    - Token matches in use_when, avoid_when: lower weight
    - Token matches in input/output descriptions: lower weight
    - Token matches in abbreviations: medium weight
    - Token matches in dependency purposes: low weight
    """

    def search(
        self,
        query: str,
        registry: ApiRegistry,
        domain: Optional[str] = None,
        limit: int = 5,
    ) -> list[tuple[CatalogEntry, float]]:
        if not query or not query.strip():
            return []

        query_lower = query.lower().strip()
        query_tokens = self._tokenize(query_lower)

        entries = registry.get_all_entries()

        # Apply domain filter if specified
        if domain:
            domain_lower = domain.lower()
            entries = [
                e for e in entries
                if e.domain and e.domain.lower() == domain_lower
            ]

        scored: list[tuple[CatalogEntry, float]] = []

        for entry in entries:
            score = self._score_entry(entry, query_lower, query_tokens)
            if score > 0:
                scored.append((entry, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[:limit]

    def _score_entry(
        self,
        entry: CatalogEntry,
        query_lower: str,
        query_tokens: list[str],
    ) -> float:
        """Score a single entry against the query."""
        score = 0.0

        # Exact match on endpoint_name (highest)
        if entry.endpoint_name.lower() == query_lower:
            score += 100.0
        elif query_lower in entry.endpoint_name.lower():
            score += 50.0

        # Exact match on display_name
        if entry.display_name:
            if entry.display_name.lower() == query_lower:
                score += 90.0
            elif query_lower in entry.display_name.lower():
                score += 45.0

        # Token matching across fields
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "endpoint_name"), 20.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "display_name"), 18.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "description"), 15.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "keywords"), 15.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "synonyms"), 12.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "abbreviations"), 12.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "use_when"), 8.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "avoid_when"), 5.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "input_descriptions"), 8.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "output_description"), 8.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "domain"), 10.0
        )
        score += self._token_score(
            query_tokens, self._get_searchable_text(entry, "dependencies"), 5.0
        )

        return score

    def _get_searchable_text(self, entry: CatalogEntry, field: str) -> str:
        """Extract searchable text from a catalog entry field."""
        if field == "endpoint_name":
            # Split camelCase/PascalCase into words
            return self._split_camel_case(entry.endpoint_name)
        elif field == "display_name":
            return (entry.display_name or "").lower()
        elif field == "description":
            return (entry.description or "").lower()
        elif field == "keywords":
            return " ".join(entry.keywords or []).lower()
        elif field == "synonyms":
            return " ".join(entry.synonyms or []).lower()
        elif field == "abbreviations":
            return " ".join(entry.abbreviations or []).lower()
        elif field == "use_when":
            return " ".join(entry.use_when or []).lower()
        elif field == "avoid_when":
            return " ".join(entry.avoid_when or []).lower()
        elif field == "input_descriptions":
            if entry.input_descriptions:
                return " ".join(entry.input_descriptions.values()).lower()
            return ""
        elif field == "output_description":
            return (entry.output_description or "").lower()
        elif field == "domain":
            return (entry.domain or "").lower()
        elif field == "dependencies":
            if entry.dependent_apis:
                parts = []
                for dep in entry.dependent_apis:
                    parts.append(dep.endpoint_name.lower())
                    if dep.purpose:
                        parts.append(dep.purpose.lower())
                return " ".join(parts)
            return ""
        return ""

    def _split_camel_case(self, name: str) -> str:
        """Split camelCase/PascalCase into lowercase words."""
        words = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
        words = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", words)
        return words.lower()

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into individual words."""
        return [t for t in re.split(r"[\s,;.!?_-]+", text.lower()) if t and len(t) > 1]

    def _token_score(
        self, query_tokens: list[str], text: str, weight: float
    ) -> float:
        """Score based on how many query tokens appear in the text."""
        if not text or not query_tokens:
            return 0.0

        matched = sum(1 for token in query_tokens if token in text)
        if matched == 0:
            return 0.0

        # Score based on proportion of query tokens matched
        ratio = matched / len(query_tokens)
        return weight * ratio


# ---------------------------------------------------------------------------
# Search service (facade)
# ---------------------------------------------------------------------------

class ApiSearchService:
    """Facade for API search that delegates to the configured backend."""

    def __init__(
        self,
        registry: ApiRegistry,
        backend_name: str = "yaml_keyword",
        default_limit: int = 5,
        max_limit: int = 20,
    ) -> None:
        self._registry = registry
        self._default_limit = default_limit
        self._max_limit = max_limit
        self._backend = self._create_backend(backend_name)
        self._backend_name = backend_name

    def _create_backend(self, name: str) -> SearchBackend:
        """Create the appropriate search backend."""
        if name == "yaml_keyword":
            return YamlKeywordSearchBackend()
        else:
            raise McpToolError.from_code(
                ErrorCode.UNSUPPORTED_SEARCH_BACKEND,
                f"Search backend '{name}' is not implemented. "
                f"Supported backends: yaml_keyword",
            )

    def search(
        self,
        query: str,
        domain: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> SearchApisResult:
        """Search for APIs matching the query.

        Args:
            query: Natural-language search query.
            domain: Optional domain filter.
            limit: Maximum results (capped at max_limit).

        Returns:
            SearchApisResult with matching candidates.
        """
        effective_limit = min(
            limit or self._default_limit,
            self._max_limit,
        )

        results = self._backend.search(
            query=query,
            registry=self._registry,
            domain=domain,
            limit=effective_limit,
        )

        entries: list[SearchResultEntry] = []
        for entry, score in results:
            dep_summaries = None
            if entry.dependent_apis:
                dep_summaries = []
                for dep in entry.dependent_apis:
                    summary = f"{dep.endpoint_name} ({dep.method})"
                    if dep.purpose:
                        summary += f": {dep.purpose.strip()}"
                    dep_summaries.append(summary)

            entries.append(
                SearchResultEntry(
                    endpoint_name=entry.endpoint_name,
                    method=entry.method,
                    path=entry.path,
                    display_name=entry.display_name,
                    description=entry.description,
                    domain=entry.domain,
                    use_when=entry.use_when,
                    avoid_when=entry.avoid_when,
                    input_summary=entry.input_descriptions,
                    output_summary=entry.output_description,
                    has_dependencies=bool(entry.dependent_apis),
                    dependency_summary=dep_summaries,
                    enabled=entry.enabled,
                    approval_status=entry.approval_status,
                    relevance_score=round(score, 2),
                )
            )

        message = None
        if not entries:
            message = (
                f"No APIs found matching '{query}'. "
                f"Try different terms or use list_all_apis to browse the catalog."
            )

        return SearchApisResult(
            query=query,
            total_matches=len(entries),
            results=entries,
            search_backend=self._backend_name,
            message=message,
        )

