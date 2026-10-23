"""Prompt formatting and response validation for bilingual query enrichment.

Formats query enrichment prompts for Ollama and remote LLM providers, and
strictly validates the structured JSON output against schema rules.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from schemas.query_enrichment import QueryEnrichmentResult, infer_query_language


def _get_template_path() -> Path:
    """Return the absolute path to enrichment_template.txt."""
    return Path(__file__).resolve().parent / "enrichment_template.txt"


def load_enrichment_template() -> str:
    """Load the enrichment prompt template from disk or use fallback."""
    path = _get_template_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    return (
        "You are an expert bilingual API search query refinement assistant supporting English and Korean.\n"
        "Your objective is to refine user queries for semantic API retrieval against a catalog of APIs.\n"
        "Instructions:\n"
        "1. Detect the language ('en', 'ko', 'mixed').\n"
        "2. Refine the query in 'enriched_query' preserving exact IDs and identifiers without inventing endpoints.\n"
        "3. Provide up to {max_alternatives} relevant alternative queries in 'alternative_queries'. For Korean, include an English equivalent.\n"
        "Output JSON only: {{\"language\": \"en\", \"enriched_query\": \"...\", \"alternative_queries\": []}}"
    )


def format_chat_messages(query: str, max_alternatives: int = 2) -> list[dict[str, str]]:
    """Format messages for chat-based LLM endpoints (e.g. /api/chat or OpenAI-compatible)."""
    system_text = load_enrichment_template().format(max_alternatives=max_alternatives)
    user_text = f'Refine this search query for API discovery: "{query}"'
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]


def format_generate_prompt(query: str, max_alternatives: int = 2) -> str:
    """Format a single prompt for generate-based endpoints."""
    template = load_enrichment_template().format(max_alternatives=max_alternatives)
    return (
        f"{template}\n\n"
        f'User Query: "{query}"\n'
        f"Response (JSON only):"
    )


def _find_key_value(d: dict[str, Any], candidates: list[str]) -> Any:
    """Search for a value in dictionary matching candidate key names flexibly."""
    for c in candidates:
        if c in d:
            return d[c]

    # Search ignoring spaces, underscores, and case
    norm_map = {re.sub(r"[\s_]+", "", k).lower(): v for k, v in d.items()}
    for c in candidates:
        norm_c = re.sub(r"[\s_]+", "", c).lower()
        if norm_c in norm_map:
            return norm_map[norm_c]

    return None


def parse_and_validate_enrichment(
    raw_text: str,
    original_query: str,
    max_alternatives: int = 2,
    raw_metadata: Optional[dict[str, Any]] = None,
) -> QueryEnrichmentResult:
    """Parse, clean, and validate raw LLM output into a QueryEnrichmentResult.

    Args:
        raw_text: The raw string response from the LLM.
        original_query: The user's original query.
        max_alternatives: Maximum number of alternative queries to retain.
        raw_metadata: Optional provider response metadata for diagnostics.

    Returns:
        Validated QueryEnrichmentResult.

    Raises:
        ValueError: If JSON is completely invalid or cannot be parsed.
    """
    cleaned = raw_text.strip()

    # Strip markdown code blocks if present
    if "```" in cleaned:
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

    # Parse JSON
    try:
        data = json.loads(cleaned)
    except Exception:
        # Fallback: extract substring between first { and last }
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
        else:
            raise ValueError(f"Model output does not contain valid JSON: '{raw_text[:200]}'")

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    # 1. Resolve Language with character-level ground truth
    inferred_lang = infer_query_language(original_query)
    raw_lang = _find_key_value(data, ["language", "lang"])

    # If the user query contains Korean characters, it is definitively "ko" or "mixed"
    if inferred_lang in ("ko", "mixed"):
        language = inferred_lang
    elif raw_lang and isinstance(raw_lang, str):
        cleaned_lang = raw_lang.strip().lower()
        if cleaned_lang in ("en", "ko", "mixed"):
            language = cleaned_lang
        elif "ko" in cleaned_lang:
            language = "ko"
        elif "en" in cleaned_lang:
            language = "en"
        else:
            language = inferred_lang
    else:
        language = inferred_lang

    # 2. Resolve Enriched Query
    raw_enriched = _find_key_value(data, ["enriched_query", "enriched query", "refined_query", "query"])
    if isinstance(raw_enriched, dict) and "query" in raw_enriched:
        raw_enriched = raw_enriched["query"]

    enriched_query = original_query
    if raw_enriched and isinstance(raw_enriched, str):
        candidate_enriched = raw_enriched.strip()
        # Filter out obvious template placeholders or empty text
        is_placeholder = (
            candidate_enriched in ("...", "<...>")
            or "<refined" in candidate_enriched
            or re.match(r"^\[?<[^>]+>\]?", candidate_enriched)
        )
        if candidate_enriched and not is_placeholder:
            enriched_query = candidate_enriched

    # 3. Resolve Alternative Queries
    raw_alts = _find_key_value(data, ["alternative_queries", "alternative queries", "alternatives"])
    alternative_queries: list[str] = []

    if isinstance(raw_alts, list):
        for item in raw_alts:
            if isinstance(item, str):
                s = item.strip()
                # Filter out placeholders, empty strings, and duplicates
                is_placeholder = bool(
                    not s
                    or s in ("...", "<...>")
                    or re.search(r"alternative_query_\d+|<.*>", s)
                    or re.match(r"^alternative\s*query\s*\d*$", s, re.IGNORECASE)
                    or s == original_query
                    or s == enriched_query
                )
                if not is_placeholder and s not in alternative_queries:
                    alternative_queries.append(s)

    # Restrict to configured limit
    alternative_queries = alternative_queries[:max_alternatives]

    return QueryEnrichmentResult(
        original_query=original_query,
        language=language,
        enriched_query=enriched_query,
        alternative_queries=alternative_queries,
        raw_response=raw_metadata,
    )

