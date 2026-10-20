"""Persistent local embedding cache with safe atomic serialization.

Stores document vectors and metadata fingerprints on disk in cache/api_embeddings/.
Reuses compatible vectors across server restarts and regenerates only missing
or modified API documents.

CRITICAL SAFETY: Uses safe JSON serialization. No untrusted pickle serialization.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from observability.json_logging import get_logger

_logger = get_logger("EmbeddingCache")
_CACHE_VERSION = "1.0"


class EmbeddingCache:
    """Manages persistent caching of catalog document embeddings."""

    def __init__(
        self,
        cache_dir: str | Path = "cache/api_embeddings",
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.cache_dir = Path(cache_dir).resolve()
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_file = self.cache_dir / "manifest.json"
        self.vectors_file = self.cache_dir / "vectors.json"

    def _key_str(self, key: tuple[str, str]) -> str:
        """Convert (endpoint_name, METHOD) composite key to string."""
        return f"{key[0]}::{key[1].upper()}"

    def _parse_key(self, key_str: str) -> tuple[str, str]:
        """Convert string back to (endpoint_name, METHOD) composite key."""
        parts = key_str.split("::", 1)
        return (parts[0], parts[1].upper())

    def load_cache(
        self,
        current_provider: str,
        current_model: str,
        current_dimensions: Optional[int],
    ) -> tuple[dict[tuple[str, str], list[float]], dict[tuple[str, str], str]]:
        """Load cached vectors and fingerprints if compatible with current model settings.

        Returns:
            Tuple of (valid_cached_vectors, valid_cached_fingerprints).
            If cache is missing, corrupted, or model configuration changed incompatibly,
            returns empty dictionaries.
        """
        if not self.enabled:
            return {}, {}

        if not self.manifest_file.exists() or not self.vectors_file.exists():
            _logger.info_event(
                "Embedding cache empty or not initialized",
                outcome="cache_miss",
                details={"cache_dir": str(self.cache_dir)},
            )
            return {}, {}

        try:
            with open(self.manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Check cache compatibility
            if manifest.get("cache_version") != _CACHE_VERSION:
                _logger.warning_event(
                    "Cache version mismatch, invalidating cache",
                    details={"cached_version": manifest.get("cache_version"), "required": _CACHE_VERSION},
                )
                return {}, {}

            if manifest.get("provider") != current_provider:
                _logger.info_event(
                    "Provider changed, invalidating cached embeddings",
                    details={"cached_provider": manifest.get("provider"), "current": current_provider},
                )
                return {}, {}

            if manifest.get("model") != current_model:
                _logger.info_event(
                    "Model changed, invalidating cached embeddings",
                    details={"cached_model": manifest.get("model"), "current": current_model},
                )
                return {}, {}

            if current_dimensions is not None:
                cached_dim = manifest.get("dimensions")
                if cached_dim is not None and cached_dim != current_dimensions:
                    _logger.info_event(
                        "Embedding dimensions changed, invalidating cached embeddings",
                        details={"cached_dimensions": cached_dim, "current": current_dimensions},
                    )
                    return {}, {}

            with open(self.vectors_file, "r", encoding="utf-8") as f:
                raw_vectors: dict[str, list[float]] = json.load(f)

            cached_fingerprints_raw: dict[str, str] = manifest.get("fingerprints", {})

            # Reconstruct typed dictionary
            vectors: dict[tuple[str, str], list[float]] = {}
            fingerprints: dict[tuple[str, str], str] = {}

            for k_str, vec in raw_vectors.items():
                k = self._parse_key(k_str)
                vectors[k] = vec
                if k_str in cached_fingerprints_raw:
                    fingerprints[k] = cached_fingerprints_raw[k_str]

            _logger.info_event(
                "Loaded compatible embedding cache",
                outcome="cache_hit",
                candidate_count=len(vectors),
                details={"model": current_model, "provider": current_provider},
            )
            return vectors, fingerprints

        except Exception as e:
            _logger.warning_event(
                "Failed to read embedding cache, recovering by returning empty cache",
                outcome="cache_corrupted",
                details={"error": str(e)},
            )
            return {}, {}

    def save_cache(
        self,
        provider: str,
        model: str,
        dimensions: int,
        vectors: dict[tuple[str, str], list[float]],
        fingerprints: dict[tuple[str, str], str],
    ) -> None:
        """Atomically persist vectors and manifest to disk using safe JSON serialization."""
        if not self.enabled:
            return

        raw_vectors = {self._key_str(k): v for k, v in vectors.items()}
        raw_fingerprints = {self._key_str(k): v for k, v in fingerprints.items()}

        manifest_data = {
            "cache_version": _CACHE_VERSION,
            "provider": provider,
            "model": model,
            "dimensions": dimensions,
            "entry_count": len(vectors),
            "fingerprints": raw_fingerprints,
        }

        # Atomic write for vectors.json
        self._atomic_json_write(self.vectors_file, raw_vectors)
        # Atomic write for manifest.json
        self._atomic_json_write(self.manifest_file, manifest_data)

        _logger.info_event(
            "Persisted embedding cache to disk",
            candidate_count=len(vectors),
            details={"cache_dir": str(self.cache_dir), "model": model},
        )

    def clear(self) -> None:
        """Clear all cached vectors and manifest files."""
        if self.vectors_file.exists():
            self.vectors_file.unlink()
        if self.manifest_file.exists():
            self.manifest_file.unlink()
        _logger.info_event("Cleared local embedding cache", details={"cache_dir": str(self.cache_dir)})

    def _atomic_json_write(self, target_path: Path, data: Any) -> None:
        """Write JSON data to a temporary file in the same directory then atomically rename."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path_str = tempfile.mkstemp(
            dir=str(target_path.parent),
            prefix="tmp_emb_",
            suffix=".json",
        )
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            # Atomic rename (on Windows os.replace replaces existing file)
            os.replace(temp_path_str, str(target_path))
        except Exception:
            if os.path.exists(temp_path_str):
                os.remove(temp_path_str)
            raise
