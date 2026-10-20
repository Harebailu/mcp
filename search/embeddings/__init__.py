"""Embedding provider package."""

from search.embeddings.base import BaseEmbeddingProvider
from search.embeddings.ollama_provider import OllamaEmbeddingProvider
from search.embeddings.remote_provider import RemoteEmbeddingProvider

__all__ = ["BaseEmbeddingProvider", "OllamaEmbeddingProvider", "RemoteEmbeddingProvider"]
