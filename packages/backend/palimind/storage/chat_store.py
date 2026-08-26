"""Vector store backed by turbovec IdMapIndex for Chat Episodic Memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from turbovec import IdMapIndex

from palimind.config import palimind_dir

_DEFAULT_DIM = 768
_BIT_WIDTH = 4
_META_FILE = "turbovec_chat_meta.json"
_INDEX_FILE = "turbovec_chat.tvim"


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


class ChatVectorStore:
    """Batched session wrapper around a turbovec IdMapIndex for Chat History."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._index: IdMapIndex | None = None
        self._meta: dict[int, dict[str, Any]] | None = None
        self._dirty = False

    def __enter__(self) -> ChatVectorStore:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.commit()

    def _ensure_loaded(self, dim: int = _DEFAULT_DIM) -> None:
        if self._index is None:
            self._index = _load_index(self.root, dim)
            self._meta = _load_meta(self.root)

    def insert(self, data: list[dict]) -> None:
        """Insert vectors into the active session.
        data expects:
        {
            "vector": list[float],
            "chunk_id": int,
            "session_id": str,
            "content": str
        }
        """
        if not data:
            return

        dim = len(data[0]["vector"])
        self._ensure_loaded(dim)

        if self._index is None or self._meta is None:
            raise RuntimeError("ChatVectorStore failed to initialise")

        vectors = np.array([d["vector"] for d in data], dtype=np.float32)
        ids = np.array([d["chunk_id"] for d in data], dtype=np.uint64)
        self._index.add_with_ids(vectors, ids)

        for d in data:
            cid = int(d["chunk_id"])
            self._meta[cid] = {
                "session_id": d["session_id"],
                "content": d["content"],
            }
        self._dirty = True

    def commit(self) -> None:
        """Persist all pending changes to disk."""
        if self._dirty:
            if self._index is not None:
                _save_index(self.root, self._index)
            if self._meta is not None:
                _save_meta(self.root, self._meta)
            self._dirty = False


def search_chat_episodes(root: Path, query_vector: list[float], limit: int = 5) -> list[dict]:
    """Return up to *limit* results closest to *query_vector*."""
    if not _index_path(root).exists():
        return []

    meta = _load_meta(root)
    if not meta:
        return []

    index = _load_index(root)
    query = np.array(query_vector, dtype=np.float32).reshape(1, -1)
    k = min(limit, len(meta))
    _scores, ext_ids = index.search(query, k=k)
    top_ids = ext_ids[0]

    results = []
    for ext_id in top_ids:
        cid = int(ext_id)
        if cid in meta:
            item = dict(meta[cid])
            item["chunk_id"] = cid
            results.append(item)
    return results
