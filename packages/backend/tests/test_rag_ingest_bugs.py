"""Regression tests for RAG ingestion / retrieval bugs (indexing robustness,
stale chunks, chunker termination, retrieval cache + filters)."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from palimind.exceptions import EmbeddingError, OCRError


def _fake_embeddings(texts, _url, _model, root=None):  # noqa: ANN001
    return [[0.01 * (i + 1)] * 8 for i in range(len(texts))]


@pytest.fixture()
def kb_root(tmp_path: Path, monkeypatch) -> Path:
    from palimind.rag import indexing

    monkeypatch.setattr(indexing, "generate_embeddings_batch", _fake_embeddings)
    root = tmp_path / "kb"
    root.mkdir()
    indexing.initialize_index(root)
    return root


def _chunk_rows(root: Path, path: str) -> list[str]:
    from palimind.storage.db import get_connection

    conn = get_connection(root)
    try:
        rows = conn.execute(
            "SELECT c.content FROM chunks c JOIN files f ON c.file_id = f.id WHERE f.path = ?",
            (path,),
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def _file_hash(root: Path, path: str) -> str | None:
    from palimind.storage.db import get_connection

    conn = get_connection(root)
    try:
        row = conn.execute("SELECT md5_hash FROM files WHERE path = ?", (path,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


# ── indexing ──────────────────────────────────────────────────────────────


def test_non_utf8_text_file_does_not_abort_indexing(kb_root: Path) -> None:
    from palimind.rag.indexing import update_index

    (kb_root / "latin1.txt").write_bytes(
        "Caf\xe9 cr\xe8me br\xfbl\xe9e recipe notes".encode("latin-1")
    )
    (kb_root / "ok.md").write_text("# Title\n\nSome perfectly fine text here.", encoding="utf-8")

    result = update_index(kb_root)

    assert result.indexed_files == 2
    assert any("Caf" in c for c in _chunk_rows(kb_root, "latin1.txt"))


def test_unexpected_parser_exception_is_a_file_error_not_a_crash(
    kb_root: Path, monkeypatch
) -> None:
    from palimind.rag import indexing

    real = indexing.extract_chunks

    def flaky(fpath, root, config):  # noqa: ANN001
        if fpath.name == "bad.md":
            raise FileNotFoundError("ffmpeg")
        return real(fpath, root, config)

    monkeypatch.setattr(indexing, "extract_chunks", flaky)
    (kb_root / "bad.md").write_text("broken", encoding="utf-8")
    (kb_root / "good.md").write_text("good content for the index", encoding="utf-8")

    result = indexing.update_index(kb_root)

    assert result.indexed_files == 1
    assert [e.path for e in result.file_errors] == ["bad.md"]


def test_embedding_failure_does_not_mark_file_indexed(kb_root: Path, monkeypatch) -> None:
    from palimind.rag import indexing

    (kb_root / "a.md").write_text("alpha content to embed", encoding="utf-8")

    def boom(*_a, **_k):  # noqa: ANN002, ANN003
        raise EmbeddingError("ollama down")

    monkeypatch.setattr(indexing, "generate_embeddings_batch", boom)
    first = indexing.update_index(kb_root)
    assert [e.path for e in first.file_errors] == ["a.md"]
    assert first.indexed_files == 0
    # The file must not be recorded with its current hash, or it is never retried.
    assert not _file_hash(kb_root, "a.md")

    monkeypatch.setattr(indexing, "generate_embeddings_batch", _fake_embeddings)
    second = indexing.update_index(kb_root)
    assert second.indexed_files == 1
    assert _chunk_rows(kb_root, "a.md")


def test_file_emptied_on_reindex_drops_stale_chunks(kb_root: Path) -> None:
    from palimind.rag.indexing import update_index

    f = kb_root / "notes.md"
    f.write_text("obsolete secret paragraph about zebras", encoding="utf-8")
    update_index(kb_root)
    assert _chunk_rows(kb_root, "notes.md")

    f.write_text("", encoding="utf-8")
    update_index(kb_root)
    assert _chunk_rows(kb_root, "notes.md") == []


def test_parse_error_on_reindex_drops_stale_chunks(kb_root: Path, monkeypatch) -> None:
    from palimind.exceptions import ParseError
    from palimind.rag import indexing

    f = kb_root / "notes.md"
    f.write_text("obsolete secret paragraph about zebras", encoding="utf-8")
    indexing.update_index(kb_root)
    old_hash = _file_hash(kb_root, "notes.md")

    f.write_text("changed content", encoding="utf-8")

    def fail(*_a, **_k):  # noqa: ANN002, ANN003
        raise ParseError("corrupt")

    monkeypatch.setattr(indexing, "extract_chunks", fail)
    result = indexing.update_index(kb_root)
    assert [e.path for e in result.file_errors] == ["notes.md"]
    # Vectors were dropped, so the FTS rows must go too; the old hash is kept
    # so the file is retried on the next run.
    assert _chunk_rows(kb_root, "notes.md") == []
    assert _file_hash(kb_root, "notes.md") == old_hash


# ── parsers ───────────────────────────────────────────────────────────────


def test_pdf_with_image_only_page_survives_ocr_failure(tmp_path: Path, monkeypatch) -> None:
    import pymupdf

    from palimind.ingestion import doc_parser

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Real text on page one")
    doc.new_page()  # blank → OCR fallback
    pdf = tmp_path / "mixed.pdf"
    doc.save(pdf)
    doc.close()

    def no_ocr(_bytes):  # noqa: ANN001
        raise OCRError("easyocr not installed")

    monkeypatch.setattr(doc_parser, "extract_text_from_image", no_ocr)
    text = doc_parser.parse_pdf(pdf)
    assert "Real text on page one" in text


def test_ffmpeg_missing_keeps_raising_runtime_error(monkeypatch) -> None:
    from palimind.ingestion import video_parser

    monkeypatch.setattr(video_parser, "_ffmpeg_checked", False)
    monkeypatch.setattr(video_parser.shutil, "which", lambda _n: None)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            video_parser.ffmpeg_available()


def test_character_chunk_terminates_on_zero_chunk_size() -> None:
    from palimind.ingestion.rich_chunker import _character_chunk

    out: list = []
    t = threading.Thread(target=lambda: out.append(_character_chunk("abc def " * 20, 0, 0)))
    t.daemon = True
    t.start()
    t.join(5)
    assert not t.is_alive(), "_character_chunk hung with chunk_size=0"
    assert "".join(out[0]).replace(" ", "") == ("abcdef" * 20)


# ── retrieval ─────────────────────────────────────────────────────────────


def test_build_candidate_ids_honours_every_filter(kb_root: Path) -> None:
    from palimind.rag.indexing import update_index
    from palimind.rag.retrieve import _build_candidate_ids

    (kb_root / "a.md").write_text("alpha alpha alpha", encoding="utf-8")
    (kb_root / "b.md").write_text("beta beta beta", encoding="utf-8")
    update_index(kb_root)

    ids_a = _build_candidate_ids(kb_root, ["a.md"])
    ids_b = _build_candidate_ids(kb_root, ["b.md"])
    both = _build_candidate_ids(kb_root, ["a.md", "b.md"])
    assert ids_a and ids_b
    assert both == ids_a | ids_b


def test_semantic_cache_is_scoped_per_index(tmp_path: Path, monkeypatch) -> None:
    from palimind.rag import retrieve

    retrieve._semantic_result_cache.clear()
    from palimind.core import embedder

    # Healthy index whose query embedding yields no vectors → keyword-only,
    # no errors, so the result is cacheable.
    monkeypatch.setattr(retrieve, "_index_exists", lambda _r: True)
    monkeypatch.setattr(retrieve, "index_compatibility_error", lambda *_a, **_k: None)
    monkeypatch.setattr(retrieve, "index_dimension", lambda _r: 1024)
    monkeypatch.setattr(embedder, "generate_embeddings_batch", lambda *_a, **_k: [])
    monkeypatch.setattr(retrieve, "_build_candidate_ids", lambda _r, _f: None)

    def fake_fts(conn, q, limit=5, **_kw):  # noqa: ANN001
        return [{"chunk_db_id": 1, "file_path": f"{conn}", "content": "hit"}]

    calls: list[Path] = []

    def fake_conn(root):  # noqa: ANN001
        calls.append(root)

        class C:
            def close(self) -> None:
                pass

            def __str__(self) -> str:
                return str(root.name)

        return C()

    monkeypatch.setattr(retrieve, "fts_search", fake_fts)
    monkeypatch.setattr(retrieve, "get_connection", fake_conn)
    monkeypatch.setattr(retrieve, "expand_window", lambda _c, r: r)

    kwargs = dict(ollama_url="http://x", embed_model="m", query_rewrite_enabled=False)
    a = retrieve.hybrid_search(tmp_path / "proj_a", "q", **kwargs)
    b = retrieve.hybrid_search(tmp_path / "proj_b", "q", **kwargs)
    assert a["sources"] == ["proj_a"]
    assert b["sources"] == ["proj_b"]
    assert a["errors"] == []
    # Same index + query is still served from the cache.
    assert retrieve.hybrid_search(tmp_path / "proj_a", "q", **kwargs) is not None
    assert len(retrieve._semantic_result_cache) == 2
    retrieve._semantic_result_cache.clear()


# ── document-mode streaming ───────────────────────────────────────────────


def test_document_stream_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    from palimind.document import engine as engine_mod
    from palimind.document import stream as stream_mod

    class FakeEngine:
        def __init__(self, *_a, **_k) -> None:  # noqa: ANN002, ANN003
            pass

        def ensure_graph(self):  # noqa: ANN201
            return None

        def retrieve_context(self, *_a, **_k):  # noqa: ANN002, ANN003, ANN201
            return {"content": "", "sources": [], "results": [], "errors": []}

        def stream_answer(self, *_a, **_k):  # noqa: ANN002, ANN003, ANN201
            time.sleep(0.4)  # slow first token (prompt processing)
            yield "hello"

    monkeypatch.setattr(engine_mod, "DocumentEngine", FakeEngine)
    monkeypatch.setattr(stream_mod, "load_config", lambda _r: {"retrieval_limit": 5})

    async def run() -> int:
        resp = await stream_mod.document_mode_stream(
            "q", None, None, None, None, "http://x", "m", tmp_path, ""
        )
        ticks = 0
        stop = False

        async def ticker() -> None:
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0.02)

        task = asyncio.create_task(ticker())
        chunks = [c async for c in resp.body_iterator]
        stop = True
        await task
        assert any('"hello"' in c for c in chunks)
        return ticks

    assert asyncio.run(run()) >= 5


# ── research project store ────────────────────────────────────────────────


def test_add_sources_keeps_document_sources_and_scores(tmp_path: Path, monkeypatch) -> None:
    from palimind.research import project_store

    monkeypatch.setattr(project_store, "projects_dir", lambda: tmp_path / "research")
    project = project_store.create_project("P")
    doc_src = {
        "marker": 1,
        "title": "Risk Factors",
        "kind": "document",
        "url": "",
        "file": "10k.pdf",
        "section": "Risk Factors",
        "snippet": "s",
        "content": "",
        "score": 0.8,
    }
    web_src = {"marker": 2, "title": "W", "kind": "web", "url": "https://a.org/x", "score": 0.7}
    project_store.add_sources(project["id"], [doc_src, web_src])
    again = project_store.add_sources(project["id"], [doc_src])
    assert again is not None
    files = [s["file"] for s in again["sources"]]
    assert files.count("10k.pdf") == 1
    assert {s["kind"] for s in again["sources"]} == {"document", "web"}
    assert next(s for s in again["sources"] if s["kind"] == "web")["score"] == 0.7
