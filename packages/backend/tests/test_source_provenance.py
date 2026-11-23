"""Provenance flows from saved sources into retrieval, citations and the graph."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.rag.indexing import initialize_index
from palimind.storage.db import get_connection, insert_chunks, upsert_file


@pytest.fixture()
def indexed_source(tmp_path: Path):
    root = tmp_path / "kb"
    root.mkdir()
    initialize_index(root)
    rel = "sources/web/example-abc12345.md"
    target = root / rel
    target.parent.mkdir(parents=True)
    target.write_text("# Example\n\nKnowledge graphs connect ideas.", "utf-8")

    conn = get_connection(root)
    try:
        file_id = upsert_file(
            conn,
            rel,
            "hash-web",
            1_700_000_000.0,
            doc_type="web",
            source={
                "id": "src123",
                "kind": "web",
                "url": "https://example.com/article?utm_source=x",
                "title": "Example Article",
                "site": "example.com",
                "author": "Ada",
                "published_at": "2024-05-06T10:00:00Z",
                "fetched_at": 1_714_995_600.0,
            },
        )
        insert_chunks(
            conn,
            file_id,
            [(0, "text", "Knowledge graphs connect ideas.", "Intro", "", "", 1, 5, 8)],
        )
        conn.commit()
    finally:
        conn.close()

    return root, rel


def test_file_rows_carry_source_provenance(indexed_source) -> None:
    from palimind.storage.db import get_all_files

    root, rel = indexed_source
    conn = get_connection(root)
    try:
        files = get_all_files(conn)
    finally:
        conn.close()

    row = next(item for item in files if item["path"] == rel)
    assert row["source_url"].startswith("https://example.com/")
    assert row["source_title"] == "Example Article"
    assert row["source_site"] == "example.com"
    assert row["doc_type"] == "web"


def test_context_header_has_url_and_fetch_date(indexed_source) -> None:
    from palimind.rag.retrieve import _assemble_context, _enrich_provenance

    root, rel = indexed_source
    results = [
        {
            "file_path": rel,
            "content": "Knowledge graphs connect ideas.",
            "section_title": "Intro",
            "doc_type": "web",
        }
    ]
    _enrich_provenance(root, results)
    parts, kept = _assemble_context(results, None)

    assert kept and kept[0]["source_url"]
    assert "--- Source:" in parts[0]
    assert "Example Article" in parts[0]
    assert "https://example.com/article" in parts[0]
    assert "fetched" in parts[0]


def test_citation_sources_use_web_url(indexed_source) -> None:
    from palimind.generative.citation import (
        build_bibliography,
        sources_from_text_refs,
    )

    root, rel = indexed_source
    sources = sources_from_text_refs(
        [
            {
                "file": rel,
                "section": "Intro",
                "url": "https://example.com/article",
                "title": "Example Article",
                "snippet": "Knowledge graphs connect ideas.",
            }
        ]
    )
    assert sources[0].kind == "web"
    assert sources[0].url == "https://example.com/article"
    bibliography = build_bibliography(sources)
    assert "[Example Article](https://example.com/article)" in bibliography


def test_graph_file_node_has_source_metadata(indexed_source) -> None:
    from palimind import knowledge
    from palimind.document.graph import DocGraph
    from palimind.storage.db import get_all_files

    root, rel = indexed_source
    graph = DocGraph(root)
    conn = get_connection(root)
    try:
        files = get_all_files(conn)
    finally:
        conn.close()
    graph.add_file_node(
        file_path=rel,
        label="Example Article",
        doc_type="web",
        source_url=files[0]["source_url"],
        source_title=files[0]["source_title"],
        source_site=files[0]["source_site"],
        source_fetched_at=files[0]["source_fetched_at"],
    )
    graph.save()

    payload = knowledge.graph_payload(root, max_nodes=10)
    node = next(n for n in payload["nodes"] if n["type"] == "file")
    assert node["source_url"].startswith("https://example.com/")
    assert node["source_title"] == "Example Article"
    assert node["source_site"] == "example.com"
