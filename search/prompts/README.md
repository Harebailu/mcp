# Prompt Templates Directory

This directory is designated for future model prompt templates, including:
- Query expansion / rewriting prompts for cross-domain search.
- Hypothetical Document Embeddings (HyDE) generation prompts.
- LLM-assisted schema summarization prompts.

In the current implementation, query enrichment and generative LLM calls are disabled (`search.llm.enabled: false`, `search.query_enrichment.enabled: false`) to keep the initial deployment lightweight, secure, and purely semantic embedding-driven.

