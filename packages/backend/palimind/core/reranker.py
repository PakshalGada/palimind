"""Local cross-encoder reranking for retrieval results.

Uses a sentence-transformers CrossEncoder (default: a small MiniLM model)
running on CPU. The model is lazy-loaded once per process and cached, and
pair scores are memoised so repeated queries are cheap.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)

_model = None
_model_name: str | None = None
_load_lock = threading.Lock()

# Reranking the same (query, chunk) pair is common across a conversation.
# Scores are deterministic for a given model, so a bounded in-process cache
# removes most of the cross-encoder cost on warm queries.
_SCORE_CACHE_MAX = 4096
_score_cache: OrderedDict[tuple[str, str, str], float] = OrderedDict()
_score_lock = threading.Lock()


def _content_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _cached_score(model_name: str, query: str, text: str) -> float | None:
    key = (model_name, query, _content_key(text))
    with _score_lock:
        value = _score_cache.get(key)
        if value is not None:
            _score_cache.move_to_end(key)
        return value


def _store_score(model_name: str, query: str, text: str, score: float) -> None:
    key = (model_name, query, _content_key(text))
    with _score_lock:
        _score_cache[key] = float(score)
        _score_cache.move_to_end(key)
        while len(_score_cache) > _SCORE_CACHE_MAX:
            _score_cache.popitem(last=False)


def _get_cross_encoder(model_name: str):
    global _model, _model_name
    if _model is not None and _model_name == model_name:
        return _model
    with _load_lock:
        if _model is not None and _model_name == model_name:
            return _model
        from palimind import setup_status

        setup_status.start("reranker", f"Preparing reranker model ({model_name})")
        try:
            import os

            for k, v in (
                ("OMP_NUM_THREADS", "2"),
                ("OMP_WAIT_POLICY", "PASSIVE"),
                ("MKL_NUM_THREADS", "2"),
            ):
                os.environ.setdefault(k, v)
            try:
                import torch

                torch.set_num_threads(2)
            except Exception:
                pass
            from sentence_transformers import CrossEncoder

            logger.info(f"Loading reranker model: {model_name}")
            # Try ONNX Runtime first for 2-5x faster CPU inference
            try:
                _model = CrossEncoder(
                    model_name,
                    device="cpu",
                    backend="onnx",
                    model_kwargs={"export": True},
                )
            except Exception:
                # Fallback to PyTorch CPU
                _model = CrossEncoder(model_name, device="cpu")
            _model_name = model_name
        except Exception as e:
            logger.warning(f"Failed to load reranker model {model_name}: {e}")
            _model = None
        finally:
            setup_status.finish("reranker")
    return _model


def is_rerank_enabled(root: Path | None = None) -> bool:
    try:
        from palimind.config import load_config

        config = load_config(root) if root else {}
    except Exception:
        config = {}
    return bool(config.get("rerank", False))


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
            from palimind.config import load_config

            config = load_config(root)
        except Exception:
            config = {}
        model_name = (
            model_name or config.get("rerank_model") or "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )

    model_name = model_name or "cross-encoder/ms-marco-MiniLM-L-6-v2"
    model = _get_cross_encoder(model_name)
    if model is None:
        return results

    try:
        texts = [r.get("content", "")[:2000] for r in results]
        scores: list[float | None] = [_cached_score(model_name, query, text) for text in texts]
        missing = [i for i, score in enumerate(scores) if score is None]
        if missing:
            pairs = [(query, texts[i]) for i in missing]
            fresh = model.predict(pairs, batch_size=16, show_progress_bar=False)
            for i, score in zip(missing, fresh, strict=False):
                scores[i] = float(score)
                _store_score(model_name, query, texts[i], float(score))

        scored = []
        for r, s in zip(results, scores, strict=False):
            item = dict(r)
            item["rerank_score"] = float(s if s is not None else 0.0)
            scored.append(item)
        scored.sort(key=lambda x: -x["rerank_score"])
        return scored[:top_k] if top_k else scored
    except Exception as e:
        logger.debug(f"Rerank failed (keeping original order): {e}")
        return results
