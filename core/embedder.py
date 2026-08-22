from __future__ import annotations

import hashlib
import json
import time
import threading
from pathlib import Path

import httpx

from core.exceptions import EmbeddingError


_CACHE_TTL_HOURS = 24
_mem_lock = threading.Lock()
# Process-level cache: root path str → {cache_key: {"e": [...], "ts": float}}
_mem_cache: dict[str, dict] = {}
_MEM_FLUSH_EVERY = 64  # persist to disk after this many uncached writes


def _cache_path(root: Path | None = None) -> Path | None:
    if root is None:
        return None
    from core.config import palimind_dir
    return palimind_dir(root) / "embed_cache.json"


def _get_mem_cache(root: Path) -> dict:
    key = str(root)
    with _mem_lock:
        entry = _mem_cache.get(key)
        if entry is None:
            entry = {
                "data": _load_cache(root),
                "dirty": 0,
            }
            _mem_cache[key] = entry
        return entry


def _flush_mem_cache(root: Path, entry: dict) -> None:
    _save_cache(entry["data"], root)
    entry["dirty"] = 0


def _text_key(text: str, model: str) -> str:
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{h}:{model}"


def _load_cache(root: Path | None) -> dict:
    p = _cache_path(root)
    if not p or not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict, root: Path | None) -> None:
    p = _cache_path(root)
    if not p:
        return
    try:
        p.write_text(json.dumps(cache, separators=(",", ":")))
    except Exception:
        pass


def _prune_cache(cache: dict) -> dict:
    now = time.time()
    cutoff = now - _CACHE_TTL_HOURS * 3600
    return {k: v for k, v in cache.items() if v.get("ts", 0) > cutoff}


def _mem_get(root: Path | None, key: str) -> list[float] | None:
    if root is None:
        return None
    entry = _get_mem_cache(root)
    cached = entry["data"].get(key)
    if cached and isinstance(cached, dict):
        emb = cached.get("e")
        if emb and len(emb) > 0:
            return emb
    return None


def _mem_put(root: Path | None, key: str, embedding: list[float]) -> None:
    if root is None:
        return
    entry = _get_mem_cache(root)
    entry["data"][key] = {"e": embedding, "ts": time.time()}
    _prune_cache(entry["data"])
    entry["dirty"] += 1
    if entry["dirty"] >= _MEM_FLUSH_EVERY:
        _flush_mem_cache(root, entry)


def flush_embed_cache(root: Path) -> None:
    """Force-persist the in-memory embedding cache to disk."""
    with _mem_lock:
        entry = _mem_cache.get(str(root))
    if entry and entry.get("dirty"):
        _flush_mem_cache(root, entry)


def generate_embedding(
    text: str,
    ollama_url: str,
    embed_model: str,
    root: Path | None = None,
) -> list[float]:
    """Generate an embedding for a single text using Ollama, with cache."""
    key = _text_key(text, embed_model)

    # Check memory/disk cache
    cached = _mem_get(root, key)
    if cached:
        return cached

    # Generate via Ollama
    url = f"{ollama_url.rstrip('/')}/api/embed"
    payload = {"model": embed_model, "input": text}
    try:
        response = httpx.post(url, json=payload, timeout=120.0)
        response.raise_for_status()
    except httpx.TimeoutException as e:
        raise EmbeddingError(f"Embedding request timed out: {e}") from e
    except httpx.HTTPError as e:
        raise EmbeddingError(f"Failed to generate embedding: {e}") from e

    data = response.json()
    embeddings = data.get("embeddings", [])
    if not embeddings or not embeddings[0]:
        raise EmbeddingError("Ollama returned an empty embedding")
    embedding = embeddings[0]

    # Write to memory cache (flushed to disk periodically)
    _mem_put(root, key, embedding)

    return embedding


def generate_embeddings_batch(
    texts: list[str],
    ollama_url: str,
    embed_model: str,
    root: Path | None = None,
) -> list[list[float]]:
    """Generate embeddings for multiple texts with per-text cache check."""
    if not texts:
        return []

    # Check memory/disk cache for each text
    keys = [_text_key(t, embed_model) for t in texts]
    cached_mask = [False] * len(texts)
    results: list[list[float] | None] = [None] * len(texts)
    for i, k in enumerate(keys):
        cached = _mem_get(root, k)
        if cached:
            results[i] = cached
            cached_mask[i] = True

    uncached = [t for t, c in zip(texts, cached_mask) if not c]
    if not uncached:
        return [r for r in results if r is not None]  # type: ignore

    # Generate only uncached texts
    url = f"{ollama_url.rstrip('/')}/api/embed"
    payload = {"model": embed_model, "input": uncached}
    try:
        response = httpx.post(url, json=payload, timeout=300.0)
        response.raise_for_status()
    except httpx.TimeoutException as e:
        raise EmbeddingError(f"Batch embedding request timed out: {e}") from e
    except httpx.HTTPError as e:
        raise EmbeddingError(f"Failed to generate batch embeddings: {e}") from e

    data = response.json()
    new_embeddings = data.get("embeddings", [])
    if len(new_embeddings) != len(uncached):
        raise EmbeddingError(
            f"Expected {len(uncached)} embeddings, got {len(new_embeddings)}"
        )

    # Fill uncached results and persist
    uncached_idx = 0
    for i, c in enumerate(cached_mask):
        if not c:
            emb = new_embeddings[uncached_idx]
            results[i] = emb
            _mem_put(root, keys[i], emb)
            uncached_idx += 1

    return [r for r in results if r is not None]  # type: ignore
