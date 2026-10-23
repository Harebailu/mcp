# Search & Reranking Prompts

This directory contains prompt templates and prompt builders used by the search and reranking subsystem:

## 1. Candidate Reranking Prompt
- **`rerank_template.txt`**: Prompt template passed to the local Ollama `qwen:1.8b` model for candidate reranking. Instructs the model to evaluate how well each candidate API fulfills the search intent and output structured JSON rankings.
- **`rerank_prompt.py`**: Prompt formatter and output parser. Formats candidate representations and strictly validates LLM responses against the original candidate set, preventing hallucinated endpoints, altered HTTP methods, or modified endpoint names.

## 2. Future Generative Templates
This directory is also structured to host future generative prompt templates if query enrichment or LLM summarization is enabled:
- Query expansion / rewriting prompts for cross-domain search.
- Hypothetical Document Embeddings (HyDE) generation prompts.
- LLM-assisted schema summarization prompts.

In the current standard deployment, query enrichment and generative LLM calls are disabled (`search.llm.enabled: false`, `search.query_enrichment.enabled: false`) to keep execution fast, deterministic, lightweight, and purely semantic embedding-driven.
