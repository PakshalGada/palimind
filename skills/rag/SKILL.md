---
name: palimind-rag
description: >
  How Palimind's RAG pipeline works (ingest → chunk → embed → retrieve →
  rerank → respond). Use when changing retrieval quality, indexing, chunking,
  embeddings, or context assembly. Triggers: RAG, chunker, embedding,
  retrieval, rerank, vector store, TurboVec, FTS5.
---

# Palimind RAG Pipeline

## Flow

```
files → ingestion/ parsers (PDF/DOCX/PPTX/XLSX/images OCR/video Whisper)
      → chunkers (chunker.py, rich_chunker.py; size/overlap from config)
      → embedder.py (nomic-embed-text via Ollama; 4-bit TurboVec quantization)
      → storage/vector_store.py + SQLite FTS5 (storage/db.py)

query → querying.py: rewrite (LLM) → hybrid search (semantic + BM25 in
        document/engine.py) → reciprocal rank fusion → cross-encoder rerank
        (reranker.py, BAAI/bge-reranker-base) → context budget assembly
        → generative/responder.py streams answer with sources
```

## Tunables (all per-workspace in .palimind/config.json)

`chunk_size` 3000 / `chunk_overlap` 500 / `turbovec_bit_width` 4 /
`retrieval_limit` 10 / `context_token_budget` 8000 / `rerank` true /
`query_rewrite` true.

## Rules

- Retrieval changes must preserve the "sources" contract returned to the UI.
- Never load embedding/reranker models at module import time — they are lazy
  for startup speed; keep it that way.
- Index DB is `.palimind/index.db` (SQLite FTS5); schema changes need a
  migration story before touching storage/.
