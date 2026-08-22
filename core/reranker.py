"""Local cross-encoder reranking for retrieval results.

Uses a sentence-transformers CrossEncoder (default: BAAI/bge-reranker-base)
running on CPU. The model is lazy-loaded once per process and cached.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_model = None
_model_name: str | None = None
_load_lock = threading.Lock()


def _get_cross_encoder(model_name: str):
    global _model, _model_name
    if _model is not None and _model_name == model_name:
        return _model
    with _load_lock:
        if _model is not None and _model_name == model_name:
            return _model
        try:
            from sentence_transformers import CrossEncoder

            logger.info(f"Loading reranker model: {model_name}")
            _model = CrossEncoder(model_name, device="cpu")
            _model_name = model_name
        except Exception as e:
            logger.warning(f"Failed to load reranker model {model_name}: {e}")
            _model = None
    return _model


def is_rerank_enabled(root: Path | None = None) -> bool:
    try:
        from core.config import load_config

        config = load_config(root) if root else {}
    except Exception:
        config = {}
    return bool(config.get("rerank", True))


def rerank(
    query: str,
    results: list[dict],
    root: Path | None = None,
    *,
    top_k: int | None = None,
    model_name: str | None = None,
) -> list[dict]:
    """Rerank *results* against *query* with a local cross-encoder.

    Falls back to the input order unchanged on any failure. Each result dict
    gets a ``rerank_score`` field; results are returned sorted by it
    (descending), truncated to *top_k* (or all if None).
    """
    if not results or not query.strip():
        return results

    if root is not None:
        try:
            from core.config import load_config

            config = load_config(root)
        except Exception:
            config = {}
        model_name = model_name or config.get("rerank_model") or "BAAI/bge-reranker-base"

    model = _get_cross_encoder(model_name or "BAAI/bge-reranker-base")
    if model is None:
        return results

    try:
        pairs = [(query, r.get("content", "")[:2000]) for r in results]
        scores = model.predict(pairs, batch_size=32, show_progress_bar=False)
        scored = []
        for r, s in zip(results, scores):
            item = dict(r)
            item["rerank_score"] = float(s)
            scored.append(item)
        scored.sort(key=lambda x: -x["rerank_score"])
        return scored[:top_k] if top_k else scored
    except Exception as e:
        logger.debug(f"Rerank failed (keeping original order): {e}")
        return results
