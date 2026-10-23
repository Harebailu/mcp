# Search, Reranking & Query Enrichment Prompts

This directory contains prompt templates and prompt builders used by the search, query enrichment, and reranking subsystems:

## 1. Candidate Reranking Prompt
- **`rerank_template.txt`**: Prompt template passed to the local Ollama `qwen:1.8b` model for candidate reranking. Instructs the model to evaluate how well each candidate API fulfills the search intent and output structured JSON rankings.
- **`rerank_prompt.py`**: Prompt formatter and output parser. Formats candidate representations and strictly validates LLM responses against the original candidate set, preventing hallucinated endpoints, altered HTTP methods, or modified endpoint names.

## 2. Bilingual Query Enrichment Prompt
- **`enrichment_template.txt`**: System prompt template for refining English, Korean, and mixed user queries before vector embedding. Instructs the model to clarify business intent, preserve technical identifiers, and generate concise English equivalents for Korean queries to ensure retrieval against English catalog descriptions.
- **`enrichment_prompt.py`**: Prompt formatter and response validator. Formats chat messages or generate prompts and strictly validates JSON output into `QueryEnrichmentResult`, inferring query language, sanitizing placeholders, and capping alternative queries.

## 3. Future Generative Templates
This directory is also structured to host future generative prompt templates if full LLM query rewriting or summarization is enabled:
- Hypothetical Document Embeddings (HyDE) generation prompts.
- LLM-assisted schema summarization prompts.
