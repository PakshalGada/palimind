from __future__ import annotations

from sentence_transformers import CrossEncoder

# ms-marco-MiniLM-L-6-v2 is ~4× faster than bge-reranker-base on CPU
# with equivalent quality for short-to-medium document chunks.
_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Pre-load at module import so the first query has zero model-load lag.
_reranker_model: CrossEncoder | None = None
_reranker_failed = False


def _load_reranker() -> CrossEncoder | None:
    global _reranker_model, _reranker_failed
    if _reranker_model is None and not _reranker_failed:
        try:
            _reranker_model = CrossEncoder(_MODEL_NAME)
        except Exception as e:
            _reranker_failed = True
            print(f"Warning: Reranker model '{_MODEL_NAME}' failed to load ({e}). "
                  "Reranking will be bypassed and results will fall back to default vector similarity ranking.")
    return _reranker_model


# Lazy loading only; no background thread so we don't force HF downloads
# until actually used.


def rerank_chunks(query: str, chunks: list[dict], top_n: int = 5) -> list[dict]:
    """Re-rank retrieved chunks using a cross-encoder.

    Always runs the CrossEncoder when there are >= 2 candidates so that
    results are sorted by true semantic relevance, not raw RRF scores.
    Expects each chunk to have a ``content`` key.
    """
    if not chunks:
        return []

    # Only skip if there's literally one or zero chunks — reranking a single
    # chunk against itself is meaningless but ordering 2+ by relevance matters.
    if len(chunks) == 1:
        return chunks

    reranker = _load_reranker()
    if reranker is None:
        return chunks[:top_n]

    pairs = [[query, chunk["content"]] for chunk in chunks]
    scores = reranker.predict(pairs, show_progress_bar=False)

    for chunk, score in zip(chunks, scores):
        chunk["rerank_score"] = float(score)

    reranked = sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
    return reranked[:top_n]
