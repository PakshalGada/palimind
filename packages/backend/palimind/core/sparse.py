"""Optional learned-sparse and ColBERT late-interaction retrieval.

Ollama's ``/api/embed`` endpoint exposes only dense vectors. bge-m3 can also
produce **learned sparse** weights and **ColBERT** token vectors, which are
stronger for exact terms and long queries, but they need the optional
``FlagEmbedding`` package and a local checkpoint. This module makes that a
drop-in upgrade: when the dependency/model is absent every function is a safe
no-op, so PaliMind keeps using dense + BM25 exactly as before.

Enable with ``sparse_retrieval`` / ``colbert_rerank`` in config after moving
off the Ollama embed endpoint.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-m3"


@lru_cache(maxsize=2)
def _load_model(model_name: str) -> Any | None:
    try:
        from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - optional dependency
        return None
    try:
        return BGEM3FlagModel(model_name, use_fp16=True)
    except Exception as e:  # noqa: BLE001 - model may not be downloaded
        logger.info(f"bge-m3 sparse/ColBERT model unavailable ({model_name}): {e}")
        return None


def available(model_name: str = DEFAULT_MODEL) -> bool:
    """Return True when learned-sparse / ColBERT encoding is usable."""
    return _load_model(model_name) is not None


def encode(
    texts: Iterable[str],
    *,
    model_name: str = DEFAULT_MODEL,
    sparse: bool = True,
    colbert: bool = False,
) -> list[dict[str, Any]]:
    """Encode texts into sparse weights and/or ColBERT token vectors.

    Returns one dict per text with the requested keys (``sparse`` and
    ``colbert``). An empty list means the optional backend is unavailable.
    """
    items = [str(t or "") for t in texts]
    if not items:
        return []
    model = _load_model(model_name)
    if model is None:
        return []
    try:
        output = model.encode(
            items,
            return_dense=False,
            return_sparse=sparse,
            return_colbert_vecs=colbert,
            max_length=8192,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"bge-m3 encode failed: {e}")
        return []

    encoded: list[dict[str, Any]] = []
    sparse_values = output.get("lexical_weights") or [] if isinstance(output, dict) else []
    colbert_values = output.get("colbert_vecs") or [] if isinstance(output, dict) else []
    for index in range(len(items)):
        item: dict[str, Any] = {}
        if sparse and index < len(sparse_values):
            item["sparse"] = {
                str(token): float(weight) for token, weight in dict(sparse_values[index]).items()
            }
        if colbert and index < len(colbert_values):
            item["colbert"] = colbert_values[index]
        encoded.append(item)
    return encoded


def sparse_score(query_weights: dict[str, float], doc_weights: dict[str, float]) -> float:
    """Dot product of learned sparse vectors (shared token ids only)."""
    if not query_weights or not doc_weights:
        return 0.0
    return float(
        sum(weight * doc_weights.get(token, 0.0) for token, weight in query_weights.items())
    )


def colbert_score(query_vectors: Any, doc_vectors: Any) -> float:
    """ColBERT max-sim late interaction between query and document tokens."""
    try:
        import numpy as np

        query = np.asarray(query_vectors, dtype="float32")
        doc = np.asarray(doc_vectors, dtype="float32")
        if query.ndim != 2 or doc.ndim != 2 or not len(query) or not len(doc):
            return 0.0
        # Normalise then sum, for every query token, the best doc token match.
        query = query / (np.linalg.norm(query, axis=1, keepdims=True) + 1e-9)
        doc = doc / (np.linalg.norm(doc, axis=1, keepdims=True) + 1e-9)
        return float((query @ doc.T).max(axis=1).sum())
    except Exception:  # noqa: BLE001
        return 0.0


def rerank(
    query: str,
    results: list[dict],
    *,
    model_name: str = DEFAULT_MODEL,
    text_key: str = "content",
    top_n: int = 50,
    use_sparse: bool = True,
    use_colbert: bool = False,
    sparse_weight: float = 0.65,
) -> list[dict]:
    """Rescore fused candidates with sparse and/or ColBERT signals.

    This is deliberately a reranker over an existing candidate pool: without a
    persisted sparse/ColBERT index, rescanning the whole corpus would be slower
    than the dense HNSW lookup. Returns *results* unchanged when unavailable.
    """
    if not results or not (use_sparse or use_colbert):
        return results
    model = _load_model(model_name)
    if model is None:
        return results

    candidates = results[:top_n]
    texts = [str(r.get(text_key) or "") for r in candidates]
    query_encoded = encode([query], model_name=model_name, sparse=use_sparse, colbert=use_colbert)
    doc_encoded = encode(texts, model_name=model_name, sparse=use_sparse, colbert=use_colbert)
    if not query_encoded or not doc_encoded:
        return results

    q = query_encoded[0]
    scores: list[float] = []
    for item in doc_encoded:
        score = 0.0
        if use_sparse:
            score += sparse_score(q.get("sparse") or {}, item.get("sparse") or {})
        if use_colbert:
            score += colbert_score(q.get("colbert"), item.get("colbert"))
        scores.append(score)

    if not any(scores):
        return results

    hi = max(scores) or 1.0
    lo = min(scores)
    span = (hi - lo) or 1.0
    reranked: list[dict] = []
    for result, score in zip(candidates, scores, strict=False):
        item = dict(result)
        normalized = (score - lo) / span
        prior = float(item.get("rrf_score") or 0.0)
        item["sparse_score"] = round(normalized, 6)
        item["_rerank_score"] = sparse_weight * normalized + (1 - sparse_weight) * prior
        reranked.append(item)
    reranked.sort(key=lambda r: -(r.get("_rerank_score") or 0))
    return reranked + results[top_n:]
