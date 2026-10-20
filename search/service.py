"""Multistage semantic search and candidate reranking service.

Replaces keyword search with:
- Stage 1: Vector cosine similarity retrieval over multilingual embeddings.
- Stage 2: Contextual candidate reranking over retrieved candidates.

Enforces runtime operational eligibility filtering: only enabled, approved,
read_only GET endpoints are returned in candidate sets.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from catalog.registry import ApiRegistry
from observability.json_logging import get_logger
from schemas.catalog import CatalogEntry
from schemas.errors import ErrorCode, McpToolError
from schemas.tool_results import SearchApisResult, SearchResultEntry
from search.document_builder import SearchDocumentBuilder
from search.protocols import EmbeddingProvider, RerankerProvider
from search.retrieval.embedding_cache import EmbeddingCache
from search.retrieval.vector_index import VectorIndex

_logger = get_logger("SemanticSearchService")


class SemanticSearchService:
    """Orchestrates embedding generation, vector retrieval, and candidate reranking."""

    def __init__(
        self,
        registry: ApiRegistry,
        embedding_provider: EmbeddingProvider,
        reranker_provider: Optional[RerankerProvider],
        vector_index: VectorIndex,
        embedding_cache: EmbeddingCache,
        default_limit: int = 5,
        candidate_limit: int = 20,
        minimum_score: Optional[float] = None,
        reranking_enabled: bool = True,
        reranking_required: bool = True,
    ) -> None:
        self._registry = registry
        self._embedding_provider = embedding_provider
        self._reranker_provider = reranker_provider
        self._vector_index = vector_index
        self._embedding_cache = embedding_cache
        self._default_limit = default_limit
        self._candidate_limit = candidate_limit
        self._minimum_score = minimum_score
        self._reranking_enabled = reranking_enabled
        self._reranking_required = reranking_required

        # Operational status flag (can be disabled in catalog-only mode if provider unavailable)
        self._semantic_search_ready: bool = False
        self._unavailability_reason: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        """Whether semantic search is operational."""
        return self._semantic_search_ready

    @property
    def search_mode(self) -> str:
        """Active search provider mode ('ollama' or 'remote')."""
        return self._embedding_provider.provider_name

    async def initialize_vectors(
        self,
        allow_catalog_only_startup: bool = False,
    ) -> None:
        """Vectorize catalog entries using local cache and build in-memory index."""
        start_time = time.perf_counter()
        entries = self._registry.get_all_entries()

        _logger.info_event(
            "Initializing semantic catalog vectors",
            candidate_count=len(entries),
            search_mode=self.search_mode,
        )

        # 1. Load compatible vectors and fingerprints from cache
        cached_vectors, cached_fingerprints = self._embedding_cache.load_cache(
            current_provider=self._embedding_provider.provider_name,
            current_model=self._embedding_provider.model_name,
            current_dimensions=self._embedding_provider.dimensions,
        )

        # 2. Check each entry against cache
        final_vectors: dict[tuple[str, str], list[float]] = {}
        final_fingerprints: dict[tuple[str, str], str] = {}

        entries_needing_embedding: list[CatalogEntry] = []
        texts_to_embed: list[str] = []

        for entry in entries:
            key = entry.composite_key
            doc_text = SearchDocumentBuilder.build_document_text(entry)
            fingerprint = SearchDocumentBuilder.compute_fingerprint(doc_text)

            # Check if cached vector exists and fingerprint matches
            if key in cached_vectors and cached_fingerprints.get(key) == fingerprint:
                final_vectors[key] = cached_vectors[key]
                final_fingerprints[key] = fingerprint
            else:
                entries_needing_embedding.append(entry)
                texts_to_embed.append(doc_text)

        _logger.info_event(
            "Embedding cache evaluation complete",
            details={
                "total_entries": len(entries),
                "reused_from_cache": len(final_vectors),
                "needing_generation": len(entries_needing_embedding),
            },
        )

        # 3. Generate vectors for missing or modified entries
        if entries_needing_embedding:
            try:
                new_vectors = await self._embedding_provider.embed_documents(texts_to_embed)
                for entry, vec, text in zip(entries_needing_embedding, new_vectors, texts_to_embed):
                    key = entry.composite_key
                    final_vectors[key] = vec
                    final_fingerprints[key] = SearchDocumentBuilder.compute_fingerprint(text)

                # Persist updated cache to disk
                self._embedding_cache.save_cache(
                    provider=self._embedding_provider.provider_name,
                    model=self._embedding_provider.model_name,
                    dimensions=self._embedding_provider.dimensions,
                    vectors=final_vectors,
                    fingerprints=final_fingerprints,
                )

            except Exception as e:
                if allow_catalog_only_startup:
                    self._semantic_search_ready = False
                    self._unavailability_reason = (
                        f"Embedding provider unavailable during startup: {e}. "
                        "Server started in catalog-only mode. Semantic search is disabled."
                    )
                    _logger.warning_event(
                        "Catalog-only mode: vector generation skipped due to unavailable provider",
                        details={"error": str(e)},
                    )
                    # Populate index with whatever cached vectors are available
                    self._vector_index.build_index(entries, final_vectors)
                    return
                else:
                    _logger.error_event(
                        "Failed to generate catalog embeddings during startup",
                        details={"error": str(e)},
                    )
                    raise

        # 4. Build in-memory index
        self._vector_index.build_index(entries, final_vectors)
        self._semantic_search_ready = True
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        _logger.info_event(
            "Vector index successfully built and ready",
            duration_ms=duration_ms,
            candidate_count=self._vector_index.count(),
            search_mode=self.search_mode,
        )

    async def search(
        self,
        query: str,
        domain: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> SearchApisResult:
        """Execute multilingual semantic retrieval and candidate reranking.

        Args:
            query: Natural language query (in English, Korean, etc.).
            domain: Optional domain filter.
            limit: Maximum candidates to return in final result.

        Returns:
            SearchApisResult with scored candidates.
        """
        start_time = time.perf_counter()
        effective_limit = min(limit or self._default_limit, 50)

        # Fail fast if search is not ready (e.g. started in catalog-only mode)
        if not self._semantic_search_ready:
            err_msg = self._unavailability_reason or "Semantic search service is currently unavailable."
            _logger.error_event("search_apis called while search is unavailable", error_code="MODEL_SERVICE_UNAVAILABLE")
            raise McpToolError.from_code(
                ErrorCode.MODEL_SERVICE_UNAVAILABLE,
                f"{err_msg} Please use list_all_apis as fallback.",
            )

        if not query or not query.strip():
            return SearchApisResult(
                query=query,
                total_matches=0,
                results=[],
                search_backend="semantic",
                search_mode=self.search_mode,
                message="Search query is empty. Provide a natural language description.",
            )

        # 1. Embed query
        try:
            query_vector = await self._embedding_provider.embed_query(query.strip())
        except Exception as e:
            _logger.error_event("Query embedding failed", details={"error": str(e)})
            raise McpToolError.from_code(
                ErrorCode.EMBEDDING_SERVICE_UNAVAILABLE,
                f"Query embedding failed: {e}. Please use list_all_apis as fallback.",
            ) from e

        # 2. Stage 1: Vector similarity retrieval
        # Retrieves only eligible (approved, enabled, read_only, GET) candidates up to candidate_limit
        stage1_candidates = self._vector_index.search(
            query_vector=query_vector,
            candidate_limit=self._candidate_limit,
            domain_filter=domain,
            filter_eligible=True,
        )

        _logger.info_event(
            "Stage 1 semantic retrieval completed",
            candidate_count=len(stage1_candidates),
            search_mode=self.search_mode,
        )

        if not stage1_candidates:
            return SearchApisResult(
                query=query,
                total_matches=0,
                results=[],
                search_backend="semantic",
                search_mode=self.search_mode,
                message=(
                    f"No eligible APIs found matching query '{query}'. "
                    f"Use list_all_apis to inspect available endpoints."
                ),
            )

        # 3. Stage 2: Reranking (if enabled and provider present)
        ranked_candidates: list[tuple[CatalogEntry, float, Optional[float]]] = []

        if self._reranking_enabled and self._reranker_provider:
            try:
                reranked = await self._reranker_provider.rerank(query, stage1_candidates)
                # Map back to tuple (entry, rerank_score, semantic_score)
                semantic_map = {entry.composite_key: sim for entry, sim in stage1_candidates}
                for entry, r_score in reranked:
                    ranked_candidates.append((entry, r_score, semantic_map.get(entry.composite_key)))
                _logger.info_event("Stage 2 candidate reranking completed", candidate_count=len(ranked_candidates))

            except Exception as e:
                if self._reranking_required:
                    _logger.error_event("Reranker required but failed", details={"error": str(e)})
                    raise McpToolError.from_code(
                        ErrorCode.RERANKER_SERVICE_UNAVAILABLE,
                        f"Reranking service failed: {e}. Please use list_all_apis as fallback.",
                    ) from e
                else:
                    _logger.warning_event("Optional reranker failed; falling back to semantic vector order", details={"error": str(e)})
                    for entry, sim in stage1_candidates:
                        ranked_candidates.append((entry, sim, sim))
        else:
            for entry, sim in stage1_candidates:
                ranked_candidates.append((entry, sim, sim))

        # 4. Apply minimum score threshold and limit
        final_entries: list[SearchResultEntry] = []

        for entry, score, sem_score in ranked_candidates:
            if self._minimum_score is not None and score < self._minimum_score:
                continue

            dep_summaries = None
            if entry.dependent_apis:
                dep_summaries = []
                for dep in entry.dependent_apis:
                    line = f"{dep.endpoint_name} ({dep.method})"
                    if dep.purpose:
                        line += f": {dep.purpose.strip()}"
                    dep_summaries.append(line)

            final_entries.append(
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
                    relevance_score=score,
                    semantic_score=sem_score,
                    rerank_score=score if self._reranking_enabled else None,
                )
            )

            if len(final_entries) >= effective_limit:
                break

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        warning = None
        message = None
        if not final_entries:
            message = (
                f"No APIs satisfied relevance criteria for '{query}'. "
                f"Try alternative terms or use list_all_apis to view the full catalog."
            )

        _logger.info_event(
            "Search completed",
            duration_ms=duration_ms,
            candidate_count=len(final_entries),
            search_mode=self.search_mode,
        )

        return SearchApisResult(
            query=query,
            total_matches=len(final_entries),
            results=final_entries,
            search_backend="semantic",
            search_mode=self.search_mode,
            message=message,
            warning=warning,
        )

