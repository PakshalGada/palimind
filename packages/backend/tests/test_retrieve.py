"""Tests for the shared retrieval pipeline and ingest fixes."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from palimind.rag.retrieve import (
    _assemble_context,
    base_query_variants,
    rewrite_queries,
    rrf_fuse,
    select_diverse,
)


def _res(cid: int, content: str, stype: str = "semantic", fp: str = "a.md") -> dict:
    return {
        "chunk_db_id": cid,
        "file_path": fp,
        "content": content,
        "search_type": stype,
    }


def test_rrf_fuse_merges_shared_chunks() -> None:
    l1 = [_res(1, "alpha"), _res(2, "beta")]
    l2 = [_res(1, "alpha", "keyword"), _res(3, "gamma", "keyword")]
    fused = rrf_fuse([l1, l2])

    assert fused[0]["result"]["chunk_db_id"] == 1
    # Chunk 1 appears in both lists → tagged with both search types
    assert fused[0]["result"]["search_type"] == "semantic+keyword"
    assert fused[0]["result"]["rrf_score"] > 0


def test_rrf_fuse_handles_chunks_without_id() -> None:
    l1 = [{"file_path": "a.md", "content": "no id here", "search_type": "semantic"}]
    fused = rrf_fuse([l1])
    assert len(fused) == 1
    assert "chunk_db_id" not in fused[0]["result"]


def test_select_diverse_dedups_near_duplicates() -> None:
    duplicate = "The company grew revenue by twenty percent last quarter."
    results = [
        _res(1, duplicate),
        _res(2, duplicate),
        _res(3, "Additional context about the same topic with unique detail."),
        _res(4, "Completely unrelated sentence about birds flying south."),
    ]
    selected = select_diverse(results, limit=10)
    contents = [r["content"] for r in selected]
    assert contents[0] == duplicate
    assert "Completely unrelated sentence about birds flying south." in contents
    # Only ONE copy of the duplicate text should survive
    assert contents.count(duplicate) == 1
    assert len(selected) == 3


def test_select_diverse_respects_source_flooding() -> None:
    results = [_res(i, f"unique content {i}", fp="same.md") for i in range(10)]
    selected = select_diverse(results, limit=10)
    assert len(selected) <= 4  # max 4 chunks per file


def test_assemble_context_respects_token_budget() -> None:
    results = [
        _res(1, "first chunk with some content"),
        _res(2, "second chunk with some content"),
        _res(3, "third chunk with some content"),
    ]
    for r in results:
        r["token_estimate"] = 4

    parts, kept = _assemble_context(results, token_budget=7)
    assert len(parts) == 1
    assert kept[0]["chunk_db_id"] == 1


def test_assemble_context_without_budget_keeps_all() -> None:
    results = [_res(1, "a"), _res(2, "b")]
    for r in results:
        r["token_estimate"] = 1
    parts, kept = _assemble_context(results, token_budget=None)
    assert len(parts) == 2


def test_base_query_variants_strips_punctuation() -> None:
    variants = base_query_variants("How did revenue grow last year?")
    assert variants[0] == "How did revenue grow last year?"
    assert "How did revenue grow last year" in variants


def test_rewrite_queries_respects_flags() -> None:
    assert rewrite_queries("q", ollama_url="", light_model="", enabled=True) == []
    assert rewrite_queries("q", ollama_url="http://x", light_model="m", enabled=False) == []


def test_parse_docx_extracts_paragraph_text(tmp_path: Path) -> None:
    from palimind.ingestion.doc_parser import parse_docx

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = ElementTree.Element(f"{{{w}}}body")
    for text in ("First paragraph", "Second paragraph"):
        p = ElementTree.SubElement(body, f"{{{w}}}p")
        r = ElementTree.SubElement(p, f"{{{w}}}r")
        t = ElementTree.SubElement(r, f"{{{w}}}t")
        t.text = text
    buf = io.BytesIO()
    ElementTree.ElementTree(body).write(buf, encoding="utf-8", xml_declaration=True)

    path = tmp_path / "sample.docx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", buf.getvalue())

    text = parse_docx(path)
    assert "First paragraph" in text
    assert "Second paragraph" in text


def test_parse_pdf_emits_page_markers(tmp_path: Path) -> None:
    import fitz

    from palimind.ingestion.doc_parser import parse_pdf

    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_text((72, 72), "Hello page content")
    path = tmp_path / "sample.pdf"
    doc.save(path)
    doc.close()

    text = parse_pdf(path)
    assert "[Page 1]" in text
    assert "[Page 2]" in text


def test_retrieve_graceful_without_index(tmp_path: Path) -> None:
    from palimind.rag.querying import retrieve

    ctx = retrieve(tmp_path, "something that has no index")
    assert ctx.sources == ()
    assert ctx.text_contexts == ()
