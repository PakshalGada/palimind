# RAG retrieval benchmark

A small, deterministic fixture corpus and query set for measuring Palimind's
document retrieval. It runs the real `hybrid_search` pipeline against a
throwaway workspace, so it exercises chunking, indexing, fusion, MMR, parent
expansion, and context assembly — not a mock.

## Run

```bash
make rag-eval          # deterministic hash embeddings (no model needed)
make rag-eval-live     # real Ollama embeddings
make rag-eval-live RAG_EVAL_MODEL=nomic-embed-text
```

Or directly:

```bash
.venv/bin/python scripts/rag_eval.py --fake
.venv/bin/python scripts/rag_eval.py --live --rerank
.venv/bin/python scripts/rag_eval.py --live --fail-under 0.85
```

Reports are written to `benchmarks/rag/report-<timestamp>.json` unless
`--out` is given.

## Layout

- `corpus/` — six small Markdown documents with distinct sections.
- `golden.jsonl` — one JSON object per query.

```json
{
  "id": "log-retention",
  "query": "How long are audit logs retained?",
  "expected": [{"file": "policy_manual.md", "section": "Data Retention"}],
  "phrases": ["seven years"],
  "abstain": false
}
```

`expected` may name multiple sources for multi-hop or multi-document queries.
`phrases` are verbatim strings that should appear in the retrieved passages.
`abstain` cases have an empty `expected` list and are reported separately.

## Metrics

- **Recall@5 / Recall@10** — fraction of expected sources inside the top-k.
- **MRR** — reciprocal rank of the first relevant result.
- **nDCG@10** — binary-relevance ranking quality.
- **Phrase hit** — fraction of expected verbatim phrases present in the top-k.
- **Latency** — mean and p50/p95 of the retrieval call.

The fake mode is a plumbing/regression check, not a statement about semantic
quality: its embeddings are hashed bag-of-tokens vectors. Use `--live` for
meaningful quality tracking.

## Baselines

| Mode | Recall@5 | Recall@10 | MRR | nDCG@10 | Phrase | p95 |
|---|---|---|---|---|---|---|
| `baseline-fake.json` | 0.967 | 1.000 | 0.791 | 0.843 | 1.000 | 18 ms |
| `baseline-live.json` (bge-m3) | 1.000 | 1.000 | 0.967 | 0.975 | 1.000 | 93 ms |

These are the checked-in reference runs. Regenerate them after an intentional
retrieval change and update this table if the numbers move.
