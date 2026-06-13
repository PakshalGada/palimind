"""Vector store backed by turbovec IdMapIndex.

IdMapIndex provides:
- Compressed storage (up to 16× vs raw float32)
- O(1) deletion by external uint64 ID
- No training phase required
- Disk persistence via .write() / .load()

The external IDs stored in turbovec are the ``id`` primary keys from the
``chunks`` SQLite table.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from turbovec import IdMapIndex

from core.config import palimind_dir

_DEFAULT_DIM = 768
_BIT_WIDTH = 4
_META_FILE = "turbovec_meta.json"
_INDEX_FILE = "turbovec.tvim"

# Module-level cache to avoid disk reads on every search
_global_search_cache: dict[str, tuple[IdMapIndex, dict[int, dict[str, Any]]]] = {}


def _get_cached_search_data(root: Path) -> tuple[IdMapIndex, dict[int, dict[str, Any]]] | None:
    path_str = str(root)
    if path_str in _global_search_cache:
        return _global_search_cache[path_str]
    
    if not _index_path(root).exists():
        return None
        
    meta = _load_meta(root)
    if not meta:
        return None
        
    index = _load_index(root)
    _global_search_cache[path_str] = (index, meta)
    return index, meta


def _index_path(root: Path) -> Path:
    return palimind_dir(root) / _INDEX_FILE


def _meta_path(root: Path) -> Path:
    return palimind_dir(root) / _META_FILE


def _load_meta(root: Path) -> dict[int, dict[str, Any]]:
    p = _meta_path(root)
    if not p.exists():
        return {}
    with p.open() as f:
        raw: dict[str, Any] = json.load(f)
    return {int(k): v for k, v in raw.items()}


def _save_meta(root: Path, meta: dict[int, dict[str, Any]]) -> None:
    p = _meta_path(root)
    with p.open("w") as f:
        json.dump({str(k): v for k, v in meta.items()}, f)


def _load_index(root: Path, dim: int = _DEFAULT_DIM) -> IdMapIndex:
    p = _index_path(root)
    if p.exists():
        return IdMapIndex.load(str(p))
    return IdMapIndex(dim=dim, bit_width=_BIT_WIDTH)


def _save_index(root: Path, index: IdMapIndex) -> None:
    index.write(str(_index_path(root)))


class VectorStore:
    """Batched session wrapper around a turbovec IdMapIndex."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._index: IdMapIndex | None = None
        self._meta: dict[int, dict[str, Any]] | None = None
        self._dirty = False

    # -- context manager --------------------------------------------------

    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.commit()

    # -- internal ---------------------------------------------------------

    def _ensure_loaded(self, dim: int = _DEFAULT_DIM) -> None:
        if self._index is None:
            self._index = _load_index(self.root, dim)
            self._meta = _load_meta(self.root)

    # -- public API -------------------------------------------------------

    def insert(self, data: list[dict]) -> None:
        """Insert vectors into the active session."""
        if not data:
            return

        dim = len(data[0]["vector"])
        self._ensure_loaded(dim)

        if self._index is None or self._meta is None:
            raise RuntimeError("VectorStore failed to initialise")

        vectors = np.array([d["vector"] for d in data], dtype=np.float32)
        ids = np.array([d["chunk_db_id"] for d in data], dtype=np.uint64)
        self._index.add_with_ids(vectors, ids)

        for d in data:
            cid = int(d["chunk_db_id"])
            self._meta[cid] = {
                "file_path": d["file_path"],
                "chunk_index": d["chunk_index"],
                "chunk_type": d["chunk_type"],
                "content": d["content"],
                "section_title": d.get("section_title", ""),
                "subsection": d.get("subsection", ""),
                "doc_year": d.get("doc_year"),
                "doc_type": d.get("doc_type", "other"),
                "entity_name": d.get("entity_name", ""),
            }
        self._dirty = True

    def delete_file(self, file_path: str) -> None:
        """Remove all vectors matching *file_path*."""
        if not _index_path(self.root).exists() and self._index is None:
            return

        self._ensure_loaded()

        if self._index is None or self._meta is None:
            return

        ids_to_remove = [
            cid for cid, m in self._meta.items() if m["file_path"] == file_path
        ]
        if not ids_to_remove:
            return

        for cid in ids_to_remove:
            self._index.remove(cid)
            del self._meta[cid]
        self._dirty = True

    def commit(self) -> None:
        """Persist all pending changes to disk."""
        if self._dirty:
            if self._index is not None:
                _save_index(self.root, self._index)
            if self._meta is not None:
                _save_meta(self.root, self._meta)
            
            # Invalidate cache
            path_str = str(self.root)
            if path_str in _global_search_cache:
                del _global_search_cache[path_str]
                
            self._dirty = False


def search(root: Path, query_vector: list[float], limit: int = 5, candidate_ids: set[int] | None = None) -> list[dict]:
    """Return up to *limit* results closest to *query_vector*."""
    cached = _get_cached_search_data(root)
    if not cached:
        return []
    
    index, meta = cached

    query = np.array(query_vector, dtype=np.float32).reshape(1, -1)
    
    # If filtering, fetch more to ensure we get enough matches after filtering
    k = min(limit * 10 if candidate_ids is not None else limit, len(meta))
    if candidate_ids is not None and len(meta) > 0:
        # If the index is small enough, just fetch everything to guarantee we find the candidate chunks
        k = len(meta)
        
    _scores, ext_ids = index.search(query, k=k)
    top_ids = ext_ids[0]

    results = []
    for ext_id in top_ids:
        cid = int(ext_id)
        if candidate_ids is not None and cid not in candidate_ids:
            continue
            
        if cid in meta:
            item = dict(meta[cid])
            item["chunk_db_id"] = cid
            results.append(item)
            if len(results) >= limit:
                break
    return results
