# RAG architecture

Palimind's knowledge base is local-first: parsing, embedding, indexing, and
retrieval all run on the machine. This document describes the retrieval path
and the contracts that keep the UI and the answer grounded.

## Pipeline

```
ingest      ingestion/doc_parser.py, image_parser.py, video_parser.py
chunk       ingestion/rich_chunker.py
embed       core/embedder.py (Ollama; bge-m3 by default)
store       storage/vector_store.py (FAISS HNSW)
            storage/db.py (SQLite + FTS5 metadata, summaries, entity mentions)
retrieve    rag/retrieve.py:hybrid_search
answer      generative/responder.py
cite        generative/citation.py
```

`rag/indexing.py` orchestrates a sync; `rag/incremental.py` wraps it in durable
runs with progress, cancellation, and resume.

## Retrieval stages

`hybrid_search` (in `rag/retrieve.py`) is the single path used by document
chat, agents, MoE, and the CLI:

1. **Query variants** — the raw query, a punctuation-stripped variant, the
   previous user turn, optional LLM rewrites, and distinctive identifiers
   (acronyms, model numbers, quoted phrases).
2. **Candidate lanes** — dense FAISS search per query variant plus BM25 lanes:
   OR (high recall), AND (high precision), and one lane per distinctive term.
3. **Fusion** — reciprocal-rank fusion with per-lane weights.
4. **Boosts** — knowledge-graph entity matches and whole-document summary
   matches promote their files.
5. **Rerank** — optional local cross-encoder (opt-in for CPU latency).
6. **Diversity** — embedding MMR with a per-file cap, falling back to lexical
   dedupe when stored vectors are unavailable.
7. **Expansion** — matched child chunks are replaced by their parent section
   (bounded by `parent_max_tokens`); unmatched hits get neighbour windows.
8. **Assembly** — blocks are numbered `[1]`, `[2]`, … and trimmed to
   `context_token_budget`. Graph/summary supplements get a small reserved
   slice so they are not always crowded out.

Agentic document mode (`document/agentic.py`) plans 2–6 sub-queries, runs them
in parallel, adds exact substring lookups for figures and quotes, merges with
MMR, and optionally runs a sufficiency/follow-up round.

## Citation contract

Every context block starts with a numeric marker:

```
[1] --- Document: reports/annual_2023.pdf → Revenue (p. 4) ---
Acme reported total revenue of $4.2 billion in 2023.
```

The model must cite the matching `[n]`. `generative/citation.py`:

- normalises any legacy `[Source: filename]` marker to `[n]`,
- maps each retrieved chunk to one `Source` (file, section, page, chunk id,
  retrieval lane, score),
- attaches markers deterministically when the model did not cite, and
- scores coverage and citation accuracy for the UI.

The retrieval result's `results` list is ordered exactly like the context
blocks, and each item carries `citation_index`, so marker `n` always points at
the passage the model saw.

## Knowledge workspace API

The Knowledge view is backed by one scoped API surface. Every endpoint accepts
`scope=field` (the active workspace) or `scope=project:<id>` (the project's
private index), so the header, graph, library and source links never mix two
knowledge bases.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/document/stats` | File/chunk counts, summaries, type/year breakdowns, model + dimension, chunker, staleness, last run, retrieval settings |
| `GET /api/document/diagnostics` | Stamp/dimension/chunker checks, vector-vs-chunk counts, missing source files, failed runs |
| `GET /api/document/files` | Paginated, filtered, sorted index-backed file library |
| `GET /api/document/files/detail?path=…` | Summary, section outline, entities and chunk previews |
| `POST /api/document/files/reindex` | Force re-parse and re-embed one file |
| `DELETE /api/document/files?path=…` | Remove a file from the index without touching disk |
| `GET /api/document/search?q=…` | Run the real hybrid pipeline and return passages with lane, score and timings |
| `GET/PATCH /api/document/config` | Read/update validated retrieval and indexing settings |
| `POST /api/document/sync` | Plan and enqueue a durable incremental run |
| `GET /api/document/runs` | Run history for the scoped knowledge base |
| `GET /api/document/graph` | Graph payload with type/year/relation filters and node/edge caps |

`hybrid_search` still returns its `diagnostics` dict (lanes, fused count,
rerank/MMR flags, budget usage, cache hit) next to `timings` and `errors`; the
search preview endpoint exposes a compact version for the UI.

Indexing runs are durable: `POST /api/document/sync` returns a `run` object
whose `run_id` identifies the job. The UI polls `/api/index/runs/<id>` (or its
events) for phase/counters, and `cancel`/`resume` are available from the
Activity tab.

`POST /api/update` and project KB sync are compatibility wrappers over the same
run machinery. They default to waiting for completion and return the legacy
`indexed_files`/`deleted_files` fields; pass `wait=false` to `/api/update` to
receive the queued run immediately. If no durable job worker is running (CLI
and test processes), the already-planned run is executed inline rather than
leaving the caller waiting forever.

## Evaluation

Use `make rag-eval` for a deterministic plumbing check and
`make rag-eval-live` for quality tracking against real embeddings. See
`benchmarks/rag/README.md`. Run the RAG tests after any retrieval change:

```bash
cd packages/backend
python -m pytest tests/test_retrieve.py tests/test_citations.py \
  tests/test_rag_tiers.py tests/test_rag_reliability.py \
  tests/test_rag_eval_metrics.py -q
```

## Known limitations

- The fake eval embeddings are lexical, so they validate plumbing rather than
  semantic quality.
- Cross-encoder reranking is off by default because CPU inference can dominate
  query latency; enable it per workspace when accuracy matters more.
- The knowledge graph is built at index time and only expanded on the query
  path when a loaded graph exists.
- Embedding-cache and FAISS metadata files are still JSON; large corpora are a
  known scaling target.
