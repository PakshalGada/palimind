"""Tests for the RAG upgrades: child/parent chunks, context headers, pages,
summary index, metadata filters, embedding MMR, and agentic retrieval."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def _fake_embeddings(texts, _url, _model, root=None):  # noqa: ANN001
    # Deterministic, distinct vectors so FAISS returns something stable.
    out = []
    for i, text in enumerate(texts):
        seed = (sum(ord(c) for c in str(text)) % 7) + 1
        out.append([0.01 * seed] * 8)
    return out


@pytest.fixture()
def kb(tmp_path: Path, monkeypatch) -> Path:
    from palimind.core import embedder
    from palimind.rag import indexing

    monkeypatch.setattr(indexing, "generate_embeddings_batch", _fake_embeddings)
    monkeypatch.setattr(embedder, "generate_embeddings_batch", _fake_embeddings)
    root = tmp_path / "kb"
    root.mkdir()
    indexing.initialize_index(root)
    return root


# ── Tier 1: chunking ──────────────────────────────────────────────────────────


def test_chunker_sets_pages_context_header_and_small_children() -> None:
    from palimind.ingestion.rich_chunker import DocumentMeta, rich_chunk_document

    text = (
        "[Page 1]\nIntro on page one.\n\n"
        "# Overview\n\n" + ("Revenue grew twelve percent. " * 20) + "\n\n"
        "[Page 2]\n\n# Risks\n\nSupply chain risk is material.\n"
    )
    chunks = rich_chunk_document(
        text,
        DocumentMeta(path="reports/acme_10k_2023.pdf", doc_year=2023, doc_type="other"),
        chunk_size=200,
        chunk_overlap=20,
    )
    assert chunks
    # Page numbers are recovered across heading boundaries.
    assert chunks[-1].page_number == 2
    assert chunks[0].page_number == 1
    # Embedding text carries a context header the display content does not.
    assert "acme_10k_2023" in chunks[-1].embed_text
    assert "page 2" in chunks[-1].embed_text
    assert "[Page 2]" not in chunks[-1].content
    # The 20-sentence section is split into multiple child chunks.
    overview = [c for c in chunks if c.section_title == "Overview"]
    assert len(overview) > 1
    assert all(c.parent_section == "Overview" for c in overview)
    assert all(c.main_section == "" for c in overview)


def test_chunker_pptx_slide_markers_are_pages(tmp_path: Path) -> None:
    from palimind.ingestion.doc_parser import parse_pptx

    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(0, 0, 100, 100)
    box.text = "Slide one content"
    path = tmp_path / "deck.pptx"
    prs.save(path)
    assert "[Page 1]" in parse_pptx(path)


# ── Tier 1 + 3: storage ───────────────────────────────────────────────────────


def test_index_stores_embed_text_main_section_and_summary_fts(kb: Path) -> None:
    from palimind.rag.indexing import update_index
    from palimind.storage.db import (
        get_connection,
        get_rich_chunks_for_file,
        get_section_chunks,
        search_summary_files,
    )

    (kb / "doc.md").write_text(
        "# Overview\n\nApple revenue grew 12% in 2023.\n\n"
        "# Risks\n\nSupply chain risk is material.\n",
        encoding="utf-8",
    )
    result = update_index(kb)
    assert result.indexed_files == 1

    conn = get_connection(kb)
    try:
        rows = get_rich_chunks_for_file(conn, "doc.md")
        assert rows and all(r["main_section"] == "" for r in rows)
        # Summary FTS is populated even with LLM summarisation disabled.
        hits = search_summary_files(conn, "supply chain")
        assert hits and hits[0]["file_path"] == "doc.md"
        # Parent (section) retrieval returns all chunks of the section.
        section = get_section_chunks(conn, "doc.md", "Risks", "Risks", "")
        assert section and all(s["section_title"] == "Risks" for s in section)
        # The embedding text is persisted separately from display content.
        raw = conn.execute(
            "SELECT embed_text, content FROM chunks WHERE section_title = 'Overview'"
        ).fetchone()
        assert raw[0] != raw[1]
        assert "doc" in raw[0]
    finally:
        conn.close()


def test_grep_chunks_finds_verbatim_numbers(kb: Path) -> None:
    from palimind.rag.indexing import update_index
    from palimind.storage.db import get_connection, grep_chunks

    (kb / "q.txt").write_text("Q3 revenue was $4.2 billion, up 12%.", encoding="utf-8")
    update_index(kb)
    conn = get_connection(kb)
    try:
        assert grep_chunks(conn, ["$4.2 billion"])
        assert grep_chunks(conn, ["12%"])
        assert not grep_chunks(conn, ["not-in-the-document"])
    finally:
        conn.close()


def test_metadata_filters_narrow_the_candidate_set(kb: Path) -> None:
    from palimind.rag.indexing import update_index
    from palimind.storage.db import get_candidate_chunk_ids, get_connection

    (kb / "annual_report_2023.md").write_text("Risk factors for 2023.", encoding="utf-8")
    (kb / "annual_report_2022.md").write_text("Risk factors for 2022.", encoding="utf-8")
    update_index(kb)
    conn = get_connection(kb)
    try:
        ids_2023 = get_candidate_chunk_ids(conn, doc_year=2023)
        ids_2022 = get_candidate_chunk_ids(conn, doc_year=2022)
        assert ids_2023 and ids_2022 and not (ids_2023 & ids_2022)
    finally:
        conn.close()


# ── Tier 1 + 3: retrieval helpers ─────────────────────────────────────────────


def test_parent_expansion_assembles_section_and_dedupes(kb: Path) -> None:
    from palimind.rag.indexing import update_index
    from palimind.rag.retrieve import expand_parent_sections
    from palimind.storage.db import get_connection, get_rich_chunks_for_file

    body = " ".join(f"Sentence {i} about supply chain exposure." for i in range(40))
    (kb / "long.md").write_text(f"# Risks\n\n{body}\n", encoding="utf-8")
    update_index(kb)
    conn = get_connection(kb)
    try:
        rows = get_rich_chunks_for_file(conn, "long.md")
        assert len(rows) > 1
        first, second = rows[0], rows[1]
        expanded = expand_parent_sections(conn, [first, second], max_tokens=2000)
        assert expanded[0].get("parent_expanded") is True
        assert "Sentence 0" in expanded[0]["content"] and "Sentence 39" in expanded[0]["content"]
        # The second child from the same section is not duplicated wholesale.
        assert not expanded[1].get("parent_expanded")
    finally:
        conn.close()


def test_select_mmr_uses_embeddings_and_drops_duplicates(monkeypatch) -> None:
    from palimind.rag import retrieve

    vectors = {
        1: [1.0, 0.0],
        2: [1.0, 0.0],
        3: [0.0, 1.0],
        4: [0.7, 0.7],
    }
    monkeypatch.setattr(
        retrieve,
        "_candidate_vectors",
        lambda _root, pool: [vectors[r["chunk_db_id"]] for r in pool],
    )
    results = [
        {"chunk_db_id": 1, "file_path": "a.md", "content": "alpha", "rrf_score": 0.9},
        {"chunk_db_id": 2, "file_path": "b.md", "content": "alpha duplicate", "rrf_score": 0.8},
        {"chunk_db_id": 3, "file_path": "c.md", "content": "beta", "rrf_score": 0.7},
        {"chunk_db_id": 4, "file_path": "d.md", "content": "gamma", "rrf_score": 0.6},
    ]
    selected = retrieve.select_mmr(
        results,
        3,
        root=Path("/tmp"),
        query_vector=[1.0, 0.0],
        per_file_cap=4,
    )
    contents = [r["content"] for r in selected]
    assert "alpha duplicate" not in contents
    assert len(selected) <= 3


def test_chunker_version_change_forces_reindex(kb: Path) -> None:
    from palimind.config import load_config, save_config
    from palimind.rag.indexing import update_index
    from palimind.storage.vector_store import read_stamp

    (kb / "doc.md").write_text("# A\n\nAlpha content.\n", encoding="utf-8")
    first = update_index(kb)
    assert first.indexed_files == 1
    stamp = read_stamp(kb) or {}
    assert stamp.get("chunker") == 3

    # Simulate an index built by an older chunker: the next update must rebuild
    # rather than leaving old-layout chunks mixed with new ones.
    config = load_config(kb)
    config["chunker_version"] = 4
    save_config(kb, config)
    second = update_index(kb)
    assert second.indexed_files == 1
    assert second.unchanged_files == 0


def test_get_vectors_reads_embeddings_back_from_faiss(kb: Path) -> None:
    from palimind.rag.indexing import update_index
    from palimind.storage.db import get_connection, get_rich_chunks_for_file
    from palimind.storage.vector_store import get_vectors

    (kb / "doc.md").write_text("# A\n\nAlpha content.\n\n# B\n\nBeta content.\n", encoding="utf-8")
    update_index(kb)
    conn = get_connection(kb)
    try:
        ids = {r["chunk_db_id"] for r in get_rich_chunks_for_file(conn, "doc.md")}
    finally:
        conn.close()
    vectors = get_vectors(kb, ids)
    assert set(vectors) == ids
    assert all(len(v) == 8 for v in vectors.values())


def test_hybrid_search_applies_metadata_filter_and_summary_boost(kb: Path) -> None:
    from palimind.rag.indexing import update_index
    from palimind.rag.retrieve import hybrid_search

    (kb / "apple_2023.md").write_text(
        "# Overview\n\nApple supply chain and revenue details for 2023.\n", encoding="utf-8"
    )
    (kb / "banana_2022.md").write_text(
        "# Overview\n\nBanana supply chain notes for 2022.\n", encoding="utf-8"
    )
    update_index(kb)

    result = hybrid_search(
        kb,
        "supply chain",
        limit=5,
        ollama_url="http://x",
        embed_model="m",
        query_rewrite_enabled=False,
        doc_year=2023,
        summary_search=False,
    )
    assert result["results"]
    assert all(r["file_path"] == "apple_2023.md" for r in result["results"])

    # Summary-stage matches the whole document even without a chunk keyword hit.
    result2 = hybrid_search(
        kb,
        "banana",
        limit=5,
        ollama_url="http://x",
        embed_model="m",
        query_rewrite_enabled=False,
        summary_search=True,
    )
    assert any(r.get("search_type") == "summary" for r in result2["results"])


# ── Tier 2: agentic RAG ───────────────────────────────────────────────────────


def test_agentic_routing_and_planning_fallbacks() -> None:
    from palimind.document.agentic import (
        extract_lookup_terms,
        heuristic_subqueries,
        should_use_agentic,
    )

    assert should_use_agentic("what is the revenue?", "auto") is False
    assert should_use_agentic("compare 2022 and 2023 revenue across both segments", "auto") is True
    assert should_use_agentic("anything", "always") is True
    assert should_use_agentic("compare x and y", "off") is False

    subs = heuristic_subqueries(
        "Compare Apple's 2022 revenue and Apple's 2023 revenue? What changed?"
    )
    assert len(subs) >= 2
    assert any("2022" in s for s in subs)

    terms = extract_lookup_terms('What was the "$4.2 billion" revenue in 2023 for Apple Inc?')
    assert "$4.2 billion" in terms
    assert "2023" in terms


def test_merge_contexts_fuses_parallel_searches_without_duplicates(kb: Path) -> None:
    from palimind.document.agentic import merge_contexts
    from palimind.rag.indexing import update_index
    from palimind.storage.db import get_connection, get_rich_chunks_for_file

    (kb / "doc.md").write_text("# Overview\n\nAlpha beta gamma delta.\n", encoding="utf-8")
    update_index(kb)
    conn = get_connection(kb)
    try:
        rows = get_rich_chunks_for_file(conn, "doc.md")
    finally:
        conn.close()
    chunk = rows[0]
    contexts = [
        {"results": [{**chunk, "search_type": "semantic"}], "sources": ["doc.md"]},
        {"results": [{**chunk, "search_type": "keyword"}], "sources": ["doc.md"]},
    ]
    merged = merge_contexts(kb, "alpha", contexts, limit=3, token_budget=2000)
    assert merged["total_results"] == 1
    assert merged["sources"] == ["doc.md"]
    assert "Alpha beta gamma" in merged["content"]


def test_agentic_retrieve_runs_parallel_plan_and_sufficiency(kb: Path, monkeypatch) -> None:
    from palimind.document import agentic

    class FakeEngine:
        root = kb
        ollama_url = "http://x"
        light_model = "light"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def retrieve_context(self, query, **kwargs):  # noqa: ANN001
            self.calls.append(query)
            return {
                "results": [
                    {
                        "chunk_db_id": 1,
                        "file_path": "doc.md",
                        "content": f"Evidence for {query}",
                        "section_title": "Overview",
                        "search_type": "semantic",
                        "rrf_score": 1.0,
                    }
                ],
                "sources": ["doc.md"],
                "errors": [],
            }

    engine = FakeEngine()
    monkeypatch.setattr(
        agentic,
        "plan_subqueries",
        lambda *a, **k: {"subqueries": ["part one", "part two"], "source": "test"},
    )
    monkeypatch.setattr(
        agentic,
        "sufficiency_check",
        lambda *a, **k: {"sufficient": True, "followups": [], "missing": ""},
    )
    monkeypatch.setattr(agentic, "_exact_lookup", lambda *a, **k: [])

    merged = agentic.agentic_retrieve(
        engine, "compare part one and part two", limit=5, planner_model="m"
    )
    assert sorted(engine.calls) == ["part one", "part two"]
    assert merged["rounds"] == 1
    assert merged["subqueries"] == ["part one", "part two"]
    assert merged["total_results"] >= 1


def test_agentic_stream_emits_plan_and_answer(kb: Path, monkeypatch) -> None:
    from palimind.document import engine as engine_mod
    from palimind.document import stream as stream_mod

    class FakeEngine:
        root = kb
        ollama_url = "http://x"
        light_model = "light"

        def __init__(self, *a, **k) -> None:
            pass

        def ensure_graph(self):  # noqa: ANN201
            return None

        def retrieve_context(self, q, **kw):  # noqa: ANN001
            return {"content": "", "sources": [], "results": [], "errors": []}

        def stream_answer(self, q, context, **kw):  # noqa: ANN001
            yield "answer"

    def fake_agentic(engine, query, **kwargs):  # noqa: ANN001
        return {
            "content": "context",
            "sources": ["doc.md"],
            "results": [],
            "total_results": 0,
            "errors": [],
            "subqueries": ["a", "b"],
            "rounds": 2,
            "plan_source": "test",
            "lookup_terms": ["2023"],
            "sufficiency": {"sufficient": True, "missing": ""},
        }

    monkeypatch.setattr(engine_mod, "DocumentEngine", FakeEngine)
    monkeypatch.setattr(
        stream_mod, "load_config", lambda _r: {"retrieval_limit": 5, "agentic_rag": "always"}
    )
    monkeypatch.setattr("palimind.document.agentic.agentic_retrieve", fake_agentic)

    async def run():
        resp = await stream_mod.document_mode_stream(
            "compare a and b",
            None,
            None,
            None,
            None,
            "http://x",
            "m",
            kb,
            "off",
            rag_mode="always",
        )
        return [c async for c in resp.body_iterator]

    chunks = asyncio.run(run())
    events = [__import__("json").loads(c[6:]) for c in chunks if c.startswith("data: ")]
    assert any(e.get("type") == "rag_plan" for e in events)
    assert any(e.get("type") == "token" and e.get("text") == "answer" for e in events)


# ── Tier 3: optional sparse/ColBERT adapter ───────────────────────────────────


def test_sparse_adapter_is_a_safe_noop_without_flagembedding(monkeypatch) -> None:
    from palimind.core import sparse

    sparse._load_model.cache_clear()
    monkeypatch.setattr(sparse, "_load_model", lambda _m: None)
    assert sparse.available() is False
    assert sparse.encode(["x"]) == []
    results = [{"content": "x", "rrf_score": 1.0}]
    assert sparse.rerank("x", results) is results
    # Scoring helpers are pure and always available.
    assert sparse.sparse_score({"a": 2.0}, {"a": 3.0}) == 6.0
    assert sparse.colbert_score([[1.0, 0.0]], [[1.0, 0.0]]) == pytest.approx(1.0)


def test_sparse_rerank_rescores_with_injected_encoder(monkeypatch) -> None:
    from palimind.core import sparse

    class FakeModel:
        def encode(self, texts, **_kw):  # noqa: ANN001
            weights = []
            for text in texts:
                if "revenue" in text:
                    weights.append({"revenue": 1.0})
                else:
                    weights.append({"revenue": 0.1})
            return {"lexical_weights": weights, "colbert_vecs": []}

    monkeypatch.setattr(sparse, "_load_model", lambda _m: FakeModel())
    results = [
        {"content": "unrelated text", "rrf_score": 0.9},
        {"content": "revenue grew", "rrf_score": 0.1},
    ]
    out = sparse.rerank("revenue", results, use_sparse=True)
    assert out[0]["content"] == "revenue grew"
    assert "sparse_score" in out[0]
