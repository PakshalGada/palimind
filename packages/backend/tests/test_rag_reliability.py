"""Regression tests for embedding-dimension recovery, schema migration,
query latency instrumentation, and acronym-aware retrieval."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest


def _fake_embeddings(texts, _url, _model, root=None, expected_dim=None):  # noqa: ANN001
    dim = expected_dim or 8
    return [[0.01 * (i + 1)] * dim for i in range(len(texts))]


# ── embedding model / dimension ──────────────────────────────────────────────


def test_load_config_refreshes_stale_embed_dim(tmp_path: Path) -> None:
    from palimind.config import load_config, palimind_dir

    palimind_dir(tmp_path).mkdir(parents=True)
    (palimind_dir(tmp_path) / "config.json").write_text(
        json.dumps({"embed_model": "nomic-embed-text", "embed_dim": 1024}),
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config["embed_model"] == "nomic-embed-text"
    assert config["embed_dim"] == 768


def test_load_config_cache_invalidates_on_change(tmp_path: Path) -> None:
    from palimind.config import load_config, palimind_dir

    palimind_dir(tmp_path).mkdir(parents=True)
    path = palimind_dir(tmp_path) / "config.json"
    path.write_text(json.dumps({"retrieval_limit": 3}), encoding="utf-8")
    assert load_config(tmp_path)["retrieval_limit"] == 3
    time.sleep(0.01)
    path.write_text(json.dumps({"retrieval_limit": 11}), encoding="utf-8")
    assert load_config(tmp_path)["retrieval_limit"] == 11


def test_compatibility_uses_known_model_dim_not_stale_embed_dim(tmp_path: Path) -> None:
    import faiss
    import numpy as np

    from palimind.config import palimind_dir
    from palimind.storage.vector_store import index_compatibility_error, write_stamp

    p_dir = palimind_dir(tmp_path)
    p_dir.mkdir(parents=True)
    index = faiss.IndexIDMap(faiss.IndexHNSWFlat(768, 16))
    index.add_with_ids(np.zeros((1, 768), dtype="float32"), np.array([1], dtype="int64"))
    faiss.write_index(index, str(p_dir / "faiss.index"))
    (p_dir / "faiss_meta.json").write_text(json.dumps({"1": {"file_path": "a"}}))
    write_stamp(tmp_path, "nomic-embed-text", 768)

    # embed_dim=1024 is the stale default; the model is known to be 768-dim.
    assert (
        index_compatibility_error(tmp_path, expected_model="nomic-embed-text", expected_dim=1024)
        is None
    )
    write_stamp(tmp_path, "bge-m3", 1024)
    assert (
        index_compatibility_error(tmp_path, expected_model="nomic-embed-text", expected_dim=768)
        is not None
    )


def test_embedder_rejects_wrong_dimension_and_stale_cache(monkeypatch) -> None:
    from palimind.core import embedder
    from palimind.exceptions import EmbeddingError

    class Resp:
        status_code = 200

        def __init__(self, dim: int) -> None:
            self._dim = dim

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"embeddings": [[0.1] * self._dim]}

    calls: list[int] = []

    def fake_post(*_a, **_k):  # noqa: ANN002, ANN003
        calls.append(1)
        return Resp(1024)

    monkeypatch.setattr(embedder.httpx, "post", fake_post)
    # A stale 384-dim cache entry must be ignored, not returned.
    monkeypatch.setattr(embedder, "_mem_get", lambda *_a, **_k: [0.2] * 384)
    monkeypatch.setattr(embedder, "_mem_put", lambda *_a, **_k: None)
    vec = embedder.generate_embedding("hello", "http://x", "bge-m3", expected_dim=1024)
    assert len(vec) == 1024
    assert calls

    def wrong_post(*_a, **_k):  # noqa: ANN002, ANN003
        return Resp(384)

    monkeypatch.setattr(embedder.httpx, "post", wrong_post)
    with pytest.raises(EmbeddingError, match="384 dimensions"):
        embedder.generate_embedding("hello", "http://x", "all-minilm", expected_dim=1024)


# ── old index DB migration ────────────────────────────────────────────────────


def test_get_connection_migrates_old_db_so_fts_keeps_working(tmp_path: Path) -> None:
    from palimind.config import palimind_dir
    from palimind.storage.db import fts_search, get_connection

    p_dir = palimind_dir(tmp_path)
    p_dir.mkdir(parents=True)
    db = p_dir / "index.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            md5_hash TEXT,
            last_indexed REAL,
            summary TEXT DEFAULT ''
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_type TEXT NOT NULL,
            content TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO files(path) VALUES('rulebook.pdf')")
    conn.execute(
        "INSERT INTO chunks(file_id, chunk_index, chunk_type, content) "
        "VALUES(1, 0, 'text', 'The SDDR video limit is three minutes.')"
    )
    conn.commit()
    conn.close()

    conn = get_connection(tmp_path)
    try:
        hits = fts_search(conn, "sddr video", limit=5)
        assert hits and hits[0]["file_path"] == "rulebook.pdf"
        cols = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
        assert {"main_section", "embed_text"} <= cols
    finally:
        conn.close()


# ── query-time recovery + quality ────────────────────────────────────────────


@pytest.fixture()
def small_index(tmp_path: Path, monkeypatch) -> Path:
    from palimind.config import save_config
    from palimind.rag import indexing

    monkeypatch.setattr(indexing, "generate_embeddings_batch", _fake_embeddings)
    root = tmp_path / "kb"
    root.mkdir()
    indexing.initialize_index(root)
    config = {
        "embed_model": "fake-model",
        "embed_dim": 8,
        "child_chunk_size": 120,
        "child_chunk_overlap": 20,
        "summarise": False,
    }
    save_config(root, config)
    (root / "ISDC-2027-Rulebook.md").write_text(
        "# 1.2.4 System Design and Development Review (SDDR)\n\n"
        "The SDDR package has a written report of 10 pages.\n\n"
        "# 1.8 Drone operations\n\nLive video feeds are used for navigation.\n",
        encoding="utf-8",
    )
    indexing.update_index(root)
    return root


def test_query_falls_back_to_the_indexed_embedding_model(small_index: Path, monkeypatch) -> None:
    from palimind.core import embedder
    from palimind.rag import retrieve

    used_models: list[str] = []

    def fake(texts, _url, model, root=None, expected_dim=None):  # noqa: ANN001
        used_models.append(model)
        return [[0.02 * (i + 1)] * (expected_dim or 8) for i in range(len(texts))]

    monkeypatch.setattr(embedder, "generate_embeddings_batch", fake)
    result = retrieve.hybrid_search(
        small_index,
        "sddr video limit",
        limit=4,
        ollama_url="http://x",
        embed_model="all-minilm",  # config/index actually use fake-model
        query_rewrite_enabled=False,
    )
    assert result["results"], result["errors"]
    assert used_models and set(used_models) == {"fake-model"}
    assert any("Index was built with 'fake-model'" in e for e in result["errors"])
    assert "timings" in result and "total_ms" in result["timings"]


def test_distinctive_terms_prioritize_acronyms_and_model_ids() -> None:
    from palimind.rag.retrieve import _distinctive_terms

    terms = _distinctive_terms('What is the SDDR video limit for IRC-2027 and the "3-minute" cut?')
    assert "SDDR" in terms
    assert "IRC-2027" in terms
    assert "3-minute" in terms


def test_numbered_headings_become_sections() -> None:
    from palimind.ingestion.rich_chunker import DocumentMeta, rich_chunk_document

    text = (
        "1.2.4 System Design and Development Review (SDDR)\n\n"
        "The SDDR package has a written report of 10 pages.\n\n"
        "1.2.5 Submission deadlines\n\nDocuments are due in November.\n"
    )
    chunks = rich_chunk_document(
        text, DocumentMeta(path="rulebook.pdf", doc_year=2027, doc_type="report")
    )
    titles = {c.section_title for c in chunks}
    assert "1.2.4 System Design and Development Review (SDDR)" in titles
    assert "1.2.5 Submission deadlines" in titles


def test_acronym_query_retrieves_the_exact_sddr_passage(tmp_path: Path, monkeypatch) -> None:
    from palimind.config import save_config
    from palimind.rag import indexing, retrieve

    def fake(texts, _url, _model, root=None, expected_dim=None):  # noqa: ANN001
        # Distinct-but-uninformative vectors: MMR can still tell chunks apart
        # while BM25/the acronym lane has to find the passage.
        out = []
        for text in texts:
            seed = (sum(ord(c) for c in text) % 17) + 1
            out.append([0.01 * seed] * (expected_dim or 8))
        return out

    monkeypatch.setattr(indexing, "generate_embeddings_batch", fake)
    from palimind.core import embedder

    monkeypatch.setattr(embedder, "generate_embeddings_batch", fake)
    root = tmp_path / "kb"
    root.mkdir()
    indexing.initialize_index(root)
    save_config(
        root,
        {
            "embed_model": "fake-model",
            "embed_dim": 8,
            "child_chunk_size": 400,
            "child_chunk_overlap": 40,
            "summarise": False,
        },
    )
    (root / "IRC-2027-Rulebook.md").write_text(
        "[Page 6]\n# 1.2.4 System Design and Development Review (SDDR)\n\n"
        "The SDDR package comprises a 16-page report and a video component.\n\n"
        "[Page 7]\n# 1.2.4 System Design and Development Review (SDDR) continued\n\n"
        "The video component shall be a 3-minute presentation highlighting the design. "
        "The top 36 teams advance based on SDDR scores.\n",
        encoding="utf-8",
    )
    indexing.update_index(root)

    result = retrieve.hybrid_search(
        root,
        "sddr video limit",
        limit=4,
        ollama_url="http://x",
        embed_model="fake-model",
        query_rewrite_enabled=False,
    )
    assert result["results"]
    assert "3-minute" in result["content"]
    assert "IRC-2027-Rulebook.md" in result["sources"]
    assert any(r.get("page_number") == 7 or r.get("page_end") == 7 for r in result["results"])
