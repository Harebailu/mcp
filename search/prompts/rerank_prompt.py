"""Reranking prompt builder and candidate ranking parser for Ollama Qwen models.

Separates prompt formatting and structured output parsing from the HTTP transport layer.
Strictly validates returned items against the original candidate set to ensure the LLM
never invents APIs, modifies endpoint names, or alters HTTP methods.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from schemas.catalog import CatalogEntry


def _get_template_path() -> Path:
    """Return the absolute path to rerank_template.txt."""
    return Path(__file__).resolve().parent / "rerank_template.txt"


def format_reranking_prompt(
    query: str,
    candidates: list[tuple[CatalogEntry, float]],
) -> str:
    """Construct the reranking prompt for Ollama."""
    template_path = _get_template_path()
    if template_path.exists():
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        template = (
            'You are an expert API discovery reranker.\n'
            'A user submitted the following search query:\n"{query}"\n\n'
            'Below are the candidate APIs retrieved from the system catalog:\n{candidates_text}\n\n'
            'Instructions:\n'
            '1. Carefully evaluate how well each candidate API fulfills the user\'s intent.\n'
            '2. Rank the candidates from most relevant to least relevant.\n'
            '3. You must ONLY rank the candidates listed above. Do not invent new APIs, change endpoint names, or alter HTTP methods.\n'
            '4. Output a single JSON object with the ranked list of candidates using this exact schema:\n'
            '{{\n  "ranking": [\n    {{"index": 0, "endpoint_name": "<endpoint_name>", "method": "<method>"}}\n  ]\n}}\n'
        )

    lines: list[str] = []
    for idx, (entry, score) in enumerate(candidates):
        desc = entry.description or "No description provided."
        use_when = f" Use when: {'; '.join(entry.use_when)}" if entry.use_when else ""
        lines.append(
            f'Candidate {idx}: endpoint_name="{entry.endpoint_name}", method="{entry.method}", '
            f'display_name="{entry.display_name or entry.endpoint_name}", domain="{entry.domain or "general"}", '
            f'description="{desc}".{use_when}'
        )

    candidates_text = "\n".join(lines)
    return template.format(query=query.strip(), candidates_text=candidates_text)


def parse_and_validate_ranking(
    response_text: str,
    candidates: list[tuple[CatalogEntry, float]],
) -> list[tuple[CatalogEntry, float]]:
    """Parse structured JSON ranking and validate candidates against the input set.

    Guarantees:
    - Only candidates from the input candidate set are included.
    - No hallucinated APIs or modified names/methods are admitted.
    - Missing candidates are appended at the end preserving vector similarity order.
    - Rerank scores are monotonic position-based ordinal scores in [0.10, 0.95].
      Arbitrary LLM output numbers are NEVER presented as calibrated probabilities.
    """
    if not candidates:
        return []

    # Map candidate keys to their original entry and initial vector score
    candidate_by_key: dict[tuple[str, str], tuple[CatalogEntry, float]] = {
        entry.composite_key: (entry, sim) for entry, sim in candidates
    }
    candidate_by_idx: dict[int, tuple[CatalogEntry, float]] = {
        idx: (entry, sim) for idx, (entry, sim) in enumerate(candidates)
    }

    ranked_keys: list[tuple[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()

    try:
        # Extract JSON object even if enclosed in markdown code blocks
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
            clean_text = re.sub(r"\s*```$", "", clean_text)

        data = json.loads(clean_text)

        # Look for ranking array under common keys: "ranking", "ranked_results", "candidates"
        items = None
        if isinstance(data, dict):
            for k in ("ranking", "ranked_results", "candidates", "results"):
                if k in data and isinstance(data[k], list):
                    items = data[k]
                    break
        elif isinstance(data, list):
            items = data

        if items and isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue

                matched_entry: Optional[CatalogEntry] = None

                # 1. Match by endpoint_name and method if present
                ep_name = item.get("endpoint_name")
                method = item.get("method")
                if ep_name and method:
                    key = (str(ep_name).strip(), str(method).strip().upper())
                    if key in candidate_by_key:
                        matched_entry = candidate_by_key[key][0]

                # 2. Match by index if name matching did not hit
                if matched_entry is None and "index" in item:
                    try:
                        idx = int(item["index"])
                        if idx in candidate_by_idx:
                            matched_entry = candidate_by_idx[idx][0]
                    except (ValueError, TypeError):
                        pass

                # If validated against candidate set and not already ranked
                if matched_entry:
                    m_key = matched_entry.composite_key
                    if m_key not in seen_keys:
                        seen_keys.add(m_key)
                        ranked_keys.append(m_key)

    except Exception:
        # If parsing completely fails, fall back to initial vector similarity order
        pass

    # Append any remaining candidates that were not mentioned by the LLM
    for entry, _ in candidates:
        if entry.composite_key not in seen_keys:
            seen_keys.add(entry.composite_key)
            ranked_keys.append(entry.composite_key)

    # Compute monotonic ordinal rerank scores (0.95 down to 0.10)
    result: list[tuple[CatalogEntry, float]] = []
    total = len(ranked_keys)
    step = 0.05 if total <= 17 else (0.85 / max(1, total - 1))

    for rank_idx, key in enumerate(ranked_keys):
        entry = candidate_by_key[key][0]
        # Ordinal score: rank 0 -> 0.95, rank 1 -> 0.90, etc.
        score = round(max(0.10, 0.95 - (rank_idx * step)), 3)
        result.append((entry, score))

    return result

