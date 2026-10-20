"""Search document builder for converting catalog entries to embedding text.

Constructs a canonical, normalized text representation of each API entry
for multilingual embedding.

CRITICAL: Operational eligibility flags (enabled, approval_status, access_mode)
are strictly EXCLUDED from the embedding text. This ensures that operational
state changes (such as approval or disabling) take effect immediately at query
time without invalidating or regenerating the cached embedding vectors.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from schemas.catalog import CatalogEntry


class SearchDocumentBuilder:
    """Builds normalized text representations and stable fingerprints from catalog entries."""

    @classmethod
    def build_document_text(cls, entry: CatalogEntry) -> str:
        """Construct a stable, normalized text document for an API entry.

        Includes semantic business information:
        - endpoint_name, method, display_name, domain
        - description, use_when, avoid_when
        - input_descriptions, output_description, response_field_descriptions
        - abbreviations
        - dependent_apis (endpoint_name, method, purpose)

        Strictly excludes operational flags:
        - enabled, approval_status, access_mode
        """
        parts: list[str] = []

        # 1. Identification & Names
        parts.append(f"API: {entry.endpoint_name}")
        parts.append(f"Method: {entry.method.upper()}")
        if entry.display_name:
            parts.append(f"Name: {entry.display_name}")
        if entry.domain:
            parts.append(f"Domain: {entry.domain}")
        parts.append(f"Path: {entry.path}")

        # 2. Abbreviations
        if entry.abbreviations:
            valid_abbrevs = [a.strip() for a in entry.abbreviations if a and a.strip()]
            if valid_abbrevs:
                parts.append(f"Abbreviations: {', '.join(valid_abbrevs)}")

        # 3. Core Business Description
        if entry.description:
            parts.append(f"Description: {cls._normalize_whitespace(entry.description)}")

        # 4. Use Cases and Limitations
        if entry.use_when:
            uses = [cls._normalize_whitespace(u) for u in entry.use_when if u.strip()]
            if uses:
                parts.append(f"Use when: {'; '.join(uses)}")

        if entry.avoid_when:
            avoids = [cls._normalize_whitespace(a) for a in entry.avoid_when if a.strip()]
            if avoids:
                parts.append(f"Avoid when: {'; '.join(avoids)}")

        # 5. Inputs & Parameters
        if entry.input_descriptions:
            param_lines = [
                f"{k}: {cls._normalize_whitespace(v)}"
                for k, v in sorted(entry.input_descriptions.items())
                if v and v.strip()
            ]
            if param_lines:
                parts.append(f"Inputs: {'; '.join(param_lines)}")

        # 6. Outputs & Response Fields
        if entry.output_description:
            parts.append(f"Output: {cls._normalize_whitespace(entry.output_description)}")

        if entry.response_field_descriptions:
            field_lines = [
                f"{k}: {cls._normalize_whitespace(v)}"
                for k, v in sorted(entry.response_field_descriptions.items())
                if v and v.strip()
            ]
            if field_lines:
                parts.append(f"Response Fields: {'; '.join(field_lines)}")

        # 7. Dependencies (endpoint names and purposes)
        if entry.dependent_apis:
            dep_lines = []
            for dep in entry.dependent_apis:
                line = f"{dep.endpoint_name} ({dep.method})"
                if dep.purpose:
                    line += f" - {cls._normalize_whitespace(dep.purpose)}"
                dep_lines.append(line)
            if dep_lines:
                parts.append(f"Dependencies: {'; '.join(dep_lines)}")

        # Join with consistent newline separator
        return "\n".join(parts)

    @classmethod
    def compute_fingerprint(cls, text: str) -> str:
        """Compute a deterministic SHA-256 fingerprint of the normalized text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """Normalize multiline strings and collapse excessive whitespace."""
        return re.sub(r"\s+", " ", text).strip()

