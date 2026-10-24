#!/usr/bin/env python3
"""Regression tests for the FAISS-backed VectorStore."""

import sys
import tempfile
from pathlib import Path

root_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_path))

from palimind.exceptions import VectorIndexError
from palimind.storage.vector_store import VectorStore, search


def _vec(dim: int, value: float = 0.1) -> list[float]:
    return [value] * dim


def _entry(dim: int, chunk_db_id: int, file_path: str, content: str) -> dict:
    return {
        "vector": _vec(dim),
        "chunk_db_id": chunk_db_id,
        "file_path": file_path,
        "chunk_index": 0,
        "chunk_type": "text",
        "content": content,
    }


def test_delete_file_does_not_assume_default_dimension():
    """Re-indexing must work when the persisted index dimension != 768.

    Regression: ``delete_file`` used to call ``_ensure_loaded()`` with the
    hard-coded 768 default, raising ``VectorIndexError`` for any model with a
    different dimension (e.g. bge-m3 = 1024). The persisted index must be
    authoritative on the delete path.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".palimind").mkdir()

        with VectorStore(root) as vstore:
            vstore.insert([_entry(1024, 1, "doc.md", "hello")])

        # A fresh session loads the persisted 1024-dim index.
        with VectorStore(root) as vstore:
            vstore.delete_file("doc.md")  # must not raise

        assert search(root, _vec(1024), limit=1) == []


def test_insert_still_rejects_dimension_mismatch():
    """The insert path keeps the dimension guard — no mixing of vector widths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".palimind").mkdir()

        with VectorStore(root) as vstore:
            vstore.insert([_entry(1024, 1, "doc.md", "hello")])

        with VectorStore(root) as vstore:
            try:
                vstore.insert([_entry(768, 2, "other.md", "world")])
            except VectorIndexError:
                pass
            else:
                raise AssertionError("expected VectorIndexError on dimension mismatch")
