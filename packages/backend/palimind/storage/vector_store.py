"""Vector store backed by FAISS HNSW index.

Provides:
- Sub-millisecond approximate nearest-neighbour search via HNSW
- O(1) deletion by external uint64 ID (via removed-ids set + lazy rebuild)
- Configurable quantization (none / sq8 / pq)
- Disk persistence via faiss.write_index() / faiss.read_index()

The external IDs stored in FAISS are the ``id`` primary keys from the
``chunks`` SQLite table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from palimind.config import palimind_dir
from palimind.exceptions import VectorIndexError

_DEFAULT_DIM = 768
_M = 32  # HNSW bi-directional links per node
_EF_CONSTRUCTION = 200  # HNSW build-time search depth
_EF_SEARCH = 64  # HNSW query-time search depth
_REBUILD_THRESHOLD = 0.05  # rebuild when removed_ids > 5% of total vectors

_META_FILE = "faiss_meta.json"
_INDEX_FILE = "faiss.index"
_REMOVED_FILE = "faiss_removed.json"
_STAMP_FILE = "faiss_stamp.json"  # records {model, dim} the index was built with

# Module-level cache to avoid disk reads on every search
_global_search_cache: dict[str, tuple[faiss.Index, dict[int, dict[str, Any]], set[int]]] = {}


def _index_path(root: Path) -> Path:
    return palimind_dir(root) / _INDEX_FILE


def _meta_path(root: Path) -> Path:
    return palimind_dir(root) / _META_FILE


def _removed_path(root: Path) -> Path:
    return palimind_dir(root) / _REMOVED_FILE


def _stamp_path(root: Path) -> Path:
    return palimind_dir(root) / _STAMP_FILE


def read_stamp(root: Path) -> dict[str, Any] | None:
    """Return the {model, dim} stamp the persisted index was built with."""
    p = _stamp_path(root)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_stamp(root: Path, model: str, dim: int) -> None:
    """Record which embedding model + dimension produced the index."""
    try:
        _stamp_path(root).write_text(json.dumps({"model": model, "dim": int(dim)}))
    except Exception:
        pass


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


def _load_removed(root: Path) -> set[int]:
    p = _removed_path(root)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text()))
    except Exception:
        return set()


def _save_removed(root: Path, removed: set[int]) -> None:
    p = _removed_path(root)
    with p.open("w") as f:
        json.dump(sorted(removed), f)


def _create_index(dim: int, quantization: str = "none") -> faiss.Index:
    """Create a FAISS HNSW index with the given quantization strategy."""
    if quantization == "sq8":
        # 8-bit scalar quantization — 4x compression vs float32
        quantizer = faiss.IndexHNSWSQ(dim, faiss.ScalarQuantizer.QT_8bit, _M)
    elif quantization == "pq":
        # Product quantization — M_sub=8, nbits=8 (faiss signature: d, M, nbits)
        quantizer = faiss.IndexHNSWPQ(dim, _M, 8)
    else:
        # No quantization — best accuracy, float32 storage
        quantizer = faiss.IndexHNSWFlat(dim, _M)

    quantizer.hnsw.efConstruction = _EF_CONSTRUCTION
    quantizer.hnsw.efSearch = _EF_SEARCH

    # Wrap in IndexIDMap to support arbitrary int64 external IDs
    return faiss.IndexIDMap(quantizer)


def _load_index(root: Path, dim: int = _DEFAULT_DIM, quantization: str = "none") -> faiss.Index:
    p = _index_path(root)
    if p.exists():
        # The persisted index is authoritative; trust its own dimension rather
        # than a hard-coded default (which broke 1024-dim models like bge-m3).
        try:
            return faiss.read_index(str(p))
        except Exception as e:
            raise VectorIndexError(f"Vector index at {p} could not be loaded: {e}") from e
    return _create_index(dim, quantization)


def index_load_error(root: Path, expected_model: str | None = None) -> str | None:
    """Return why the persisted index cannot be used, or ``None`` if it is
    absent or healthy. Never raises — intended as a pre-flight check.

    Also flags an embedding-model change (the stamp recorded at build time vs
    ``expected_model``) so callers can rebuild instead of mixing vectors from
    two incompatible models.
    """
    p = _index_path(root)
    if not p.exists():
        return None
    try:
        faiss.read_index(str(p))
        # Also check meta is readable
        _load_meta(root)
    except Exception as e:
        return str(e)

    stamp = read_stamp(root)
    if expected_model and stamp and stamp.get("model"):
        if stamp["model"] != expected_model:
            return (
                f"Embedding model changed ({stamp['model']} → {expected_model}) — rebuilding index"
            )
    return None


def reset(root: Path) -> None:
    """Delete the persisted index and its sidecar metadata.

    Used to recover from an incompatible/corrupt index. Vectors must be
    rebuilt from source afterwards (a full re-index).
    """
    for p in (_index_path(root), _meta_path(root), _removed_path(root), _stamp_path(root)):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    _global_search_cache.pop(str(root), None)


def _save_index(root: Path, index: faiss.Index) -> None:
    faiss.write_index(index, str(_index_path(root)))


def _get_cached_search_data(
    root: Path,
) -> tuple[faiss.Index, dict[int, dict[str, Any]], set[int]] | None:
    path_str = str(root)
    if path_str in _global_search_cache:
        return _global_search_cache[path_str]

    if not _index_path(root).exists():
        return None

    meta = _load_meta(root)
    if not meta:
        return None

    try:
        index = _load_index(root)
    except VectorIndexError:
        return None

    removed = _load_removed(root)
    _global_search_cache[path_str] = (index, meta, removed)
    return index, meta, removed


class VectorStore:
    """Batched session wrapper around a FAISS HNSW index."""

    def __init__(self, root: Path, quantization: str = "none") -> None:
        self.root = root
        self.quantization = quantization
        self._index: faiss.Index | None = None
        self._meta: dict[int, dict[str, Any]] | None = None
        self._removed: set[int] = set()
        self._dirty = False

    # -- context manager --------------------------------------------------

    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.commit()

    # -- internal ---------------------------------------------------------

    def _ensure_loaded(self, dim: int = _DEFAULT_DIM) -> None:
        if self._index is None:
            self._index = _load_index(self.root, dim, self.quantization)
            self._meta = _load_meta(self.root)
            self._removed = _load_removed(self.root)
            # Safety net: never add vectors of one dimension to an index built
            # at another. Indexing resets on a model change, so this only
            # triggers on an out-of-band path (e.g. capture) — fail loudly.
            if self._index.ntotal > 0 and self._index.d != dim:
                raise VectorIndexError(
                    f"Index dimension {self._index.d} does not match embedding "
                    f"dimension {dim}; rebuild the index."
                )

    # -- public API -------------------------------------------------------

    def insert(self, data: list[dict]) -> None:
        """Insert vectors into the active session.

        Supports multi-vector: if a dict has a "vectors" key (list of vectors),
        all vectors are stored with the same chunk_db_id. The first vector is
        used for the primary index; additional vectors are stored in a secondary
        index for multi-vector retrieval.
        """
        if not data:
            return

        dim = len(data[0]["vector"])
        self._ensure_loaded(dim)

        if self._index is None or self._meta is None:
            raise RuntimeError("VectorStore failed to initialise")

        # Check if any items have multi-vector data
        has_multi_vector = any("vectors" in d for d in data)

        if has_multi_vector:
            # Multi-vector mode: store primary vector in main index,
            # additional vectors in a secondary index
            primary_vectors = []
            primary_ids = []
            for d in data:
                cid = int(d["chunk_db_id"])
                vectors = d.get("vectors", [d["vector"]])
                primary_vectors.append(vectors[0])
                primary_ids.append(cid)

                # Store all vectors in meta for multi-vector retrieval
                self._meta[cid] = {
                    "file_path": d["file_path"],
                    "chunk_index": d["chunk_index"],
                    "chunk_type": d["chunk_type"],
                    "content": d["content"],
                    "section_title": d.get("section_title", ""),
                    "subsection": d.get("subsection", ""),
                    "main_section": d.get("main_section", ""),
                    "parent_section": d.get("parent_section", ""),
                    "doc_year": d.get("doc_year"),
                    "doc_type": d.get("doc_type", "other"),
                    "entity_name": d.get("entity_name", ""),
                    "media_start_ts": d.get("media_start_ts"),
                    "media_end_ts": d.get("media_end_ts"),
                    "vectors": vectors,  # Store all vectors for multi-vector retrieval
                }
                self._removed.discard(cid)

            vectors_array = np.array(primary_vectors, dtype=np.float32)
            ids_array = np.array(primary_ids, dtype=np.int64)
            self._index.add_with_ids(vectors_array, ids_array)
        else:
            # Single-vector mode (original behavior)
            vectors = np.array([d["vector"] for d in data], dtype=np.float32)
            ids = np.array([d["chunk_db_id"] for d in data], dtype=np.int64)
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
                    "main_section": d.get("main_section", ""),
                    "parent_section": d.get("parent_section", ""),
                    "doc_year": d.get("doc_year"),
                    "doc_type": d.get("doc_type", "other"),
                    "entity_name": d.get("entity_name", ""),
                    "media_start_ts": d.get("media_start_ts"),
                    "media_end_ts": d.get("media_end_ts"),
                }
                self._removed.discard(cid)

        self._dirty = True

    def delete_file(self, file_path: str) -> None:
        """Remove all vectors matching *file_path*."""
        if not _index_path(self.root).exists() and self._index is None:
            return

        self._ensure_loaded()

        if self._index is None or self._meta is None:
            return

        ids_to_remove = [cid for cid, m in self._meta.items() if m["file_path"] == file_path]
        if not ids_to_remove:
            return

        for cid in ids_to_remove:
            self._removed.add(cid)
            del self._meta[cid]
        self._dirty = True

    def commit(self) -> None:
        """Persist all pending changes to disk."""
        if self._dirty:
            if self._index is not None:
                # Rebuild index if too many removals have accumulated
                total_vectors = self._index.ntotal
                if total_vectors > 0 and len(self._removed) > _REBUILD_THRESHOLD * total_vectors:
                    self._rebuild_index()
                _save_index(self.root, self._index)
            if self._meta is not None:
                _save_meta(self.root, self._meta)
            if self._removed:
                _save_removed(self.root, self._removed)

            # Invalidate cache
            path_str = str(self.root)
            if path_str in _global_search_cache:
                del _global_search_cache[path_str]

            self._dirty = False

    def _rebuild_index(self) -> None:
        """Rebuild the FAISS index without removed vectors."""
        if self._index is None or self._meta is None:
            return

        # Collect all non-removed vectors
        keep_ids = [cid for cid in self._meta.keys() if cid not in self._removed]
        if not keep_ids:
            # Everything was removed — create a fresh empty index
            dim = self._index.d
            self._index = _create_index(dim, self.quantization)
            self._removed.clear()
            return

        # Search for all existing vectors to get their values
        # This is expensive but only happens when > 5% of vectors are removed
        vectors_list = []
        ids_list = []
        for cid in keep_ids:
            try:
                vec = self._index.reconstruct(int(cid))
                vectors_list.append(vec)
                ids_list.append(cid)
            except Exception:
                # Vector not found in index (shouldn't happen, but be safe)
                pass

        if not vectors_list:
            dim = self._index.d
            self._index = _create_index(dim, self.quantization)
            self._removed.clear()
            return

        # Create new index and re-add vectors
        dim = self._index.d
        new_index = _create_index(dim, self.quantization)
        vectors_array = np.array(vectors_list, dtype=np.float32)
        ids_array = np.array(ids_list, dtype=np.int64)
        new_index.add_with_ids(vectors_array, ids_array)

        self._index = new_index
        self._removed.clear()


def search(
    root: Path, query_vector: list[float], limit: int = 5, candidate_ids: set[int] | None = None
) -> list[dict]:
    """Return up to *limit* results closest to *query_vector*.

    When *candidate_ids* filtering is active, starts with a cheap over-fetch
    (k = limit * 10) and only escalates to scanning the whole index if that
    doesn't yield enough matching candidates.
    """
    cached = _get_cached_search_data(root)
    if not cached:
        return []

    index, meta, removed = cached

    def _run(k: int) -> list[dict]:
        query = np.array(query_vector, dtype=np.float32).reshape(1, -1)
        # Over-fetch to account for removed IDs
        over_fetch = min(k + len(removed) + 10, index.ntotal) if removed else k
        over_fetch = min(over_fetch, index.ntotal)
        if over_fetch <= 0:
            return []

        _scores, ext_ids = index.search(query, k=over_fetch)
        results = []
        for ext_id in ext_ids[0]:
            cid = int(ext_id)
            if cid in removed:
                continue
            if candidate_ids is not None and cid not in candidate_ids:
                continue
            if cid in meta:
                item = dict(meta[cid])
                item["chunk_db_id"] = cid
                results.append(item)
                if len(results) >= limit:
                    break
        return results

    if candidate_ids is None:
        return _run(min(limit, len(meta)))

    # Filtered search: escalate only when needed
    total_indexed = len(meta)
    k = min(limit * 10, total_indexed)
    results = _run(k)
    if len(results) < limit and k < total_indexed:
        results = _run(total_indexed)
    return results
