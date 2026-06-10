from __future__ import annotations

from sentence_transformers import CrossEncoder

# ms-marco-MiniLM-L-6-v2 is ~4× faster than bge-reranker-base on CPU
# with equivalent quality for short-to-medium document chunks.
_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Pre-load at module import so the first query has zero model-load lag.
_reranker_model: CrossEncoder | None = None


def _load_reranker() -> CrossEncoder:
    global _reranker_model
    if _reranker_model is None:
        _reranker_model = CrossEncoder(_MODEL_NAME)
    return _reranker_model


# Eagerly start loading in a background thread so it's ready by first query.
import threading as _threading
_threading.Thread(target=_load_reranker, daemon=True).start()


def rerank_chunks(query: str, chunks: list[dict], top_n: int = 5) -> list[dict]:
    """Re-rank retrieved chunks using a cross-encoder.

    Skips reranking when there are no more candidates than we need —
    ordering doesn't matter if we'd return everything anyway.
    Expects each chunk to have a ``content`` key.
    """
    if not chunks:
        return []

    # If we already have top_n or fewer candidates, reranking won't change
    # which chunks are returned — skip the CPU inference entirely.
    if len(chunks) <= top_n:
        return chunks[:top_n]

    reranker = _load_reranker()

    pairs = [[query, chunk["content"]] for chunk in chunks]
    scores = reranker.predict(pairs, show_progress_bar=False)

    for chunk, score in zip(chunks, scores):
        chunk["rerank_score"] = float(score)

    reranked = sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
    return reranked[:top_n]
