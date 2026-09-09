"""Tests for the knowledge graph (pure logic — no Ollama/LLM)."""

from __future__ import annotations

from pathlib import Path

from palimind.document.graph import (
    DocGraph,
    load_doc_graph,
    normalize_entity_name,
)


def _mk_graph(root: Path) -> DocGraph:
    g = DocGraph(root)
    f1 = g.add_file_node("reports/a.pdf", summary="Acme annual report")
    f2 = g.add_file_node("reports/b.pdf", summary="Acme Q2 results")
    g.add_file_node("notes/c.md", summary="Unrelated notes")
    acme = g.add_entity_node("Acme Corp")
    g.add_edge(f1, acme, "references")
    g.add_edge(f2, acme, "references")
    g.add_edge(f1, g.add_section_node("Risk Factors", "reports/a.pdf"), "has_section")
    return g


def test_normalize_entity_name() -> None:
    assert normalize_entity_name("Acme Inc") == "acme"
    assert normalize_entity_name("ACME CORPORATION.") == "acme"
    assert normalize_entity_name("Acme LLC") == "acme"
    assert normalize_entity_name("OpenAI") == "openai"


def test_add_edge_dedupes() -> None:
    g = DocGraph(Path("/tmp/x"))
    f = g.add_file_node("a.md")
    e = g.add_entity_node("Acme")
    g.add_edge(f, e, "references")
    g.add_edge(f, e, "references")
    assert len(g.edges) == 1


def test_get_related_files_via_shared_entity(tmp_path: Path) -> None:
    g = _mk_graph(tmp_path)
    related = g.get_related_files("reports/a.pdf")
    assert "reports/b.pdf" in related
    assert "notes/c.md" not in related


def test_search_by_entity_is_case_insensitive(tmp_path: Path) -> None:
    g = _mk_graph(tmp_path)
    files = g.search_by_entity("acme")
    paths = {f["file_path"] for f in files}
    assert {"reports/a.pdf", "reports/b.pdf"} <= paths


def test_match_entities_finds_label_in_query(tmp_path: Path) -> None:
    g = _mk_graph(tmp_path)
    matched = g.match_entities("How did Acme perform this quarter?")
    assert matched == ["entity:acme"]


def test_remove_file_drops_sections_and_orphan_entities(tmp_path: Path) -> None:
    g = _mk_graph(tmp_path)
    g.remove_file("reports/a.pdf")
    assert "file:reports/a.pdf" not in g.nodes
    assert g.file_nodes.get("reports/a.pdf") is None
    # "Risk Factors" section belonged to a.pdf only
    assert not any(
        n.startswith("section:reports/a.pdf") for n in g.nodes
    )
    # "Acme" entity is still linked via b.pdf, so it survives
    assert "entity:acme" in g.nodes


def test_remove_file_drops_entity_with_no_remaining_links(tmp_path: Path) -> None:
    g = DocGraph(tmp_path)
    f = g.add_file_node("solo.md")
    e = g.add_entity_node("OnlyCo")
    g.add_edge(f, e, "references")
    g.remove_file("solo.md")
    assert "entity:onlyco" not in g.nodes


def test_load_rebuilds_adjacency(tmp_path: Path) -> None:
    g = _mk_graph(tmp_path)
    g.save()
    loaded = DocGraph.load(tmp_path)
    assert loaded is not None
    assert len(loaded.nodes) > 0
    # adjacency index is functional after load
    related = loaded.get_related_files("reports/a.pdf")
    assert "reports/b.pdf" in related
    # hashes round-trip
    g.file_hashes["reports/a.pdf"] = "abc123"
    g.save()
    assert DocGraph.load(tmp_path).file_hashes["reports/a.pdf"] == "abc123"


def test_load_doc_graph_never_builds_without_force(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".palimind").mkdir(parents=True)

    def _fail(*args, **kwargs):
        raise AssertionError("build_doc_graph must not run on the query path")

    monkeypatch.setattr("palimind.document.graph.build_doc_graph", _fail)
    g = load_doc_graph(tmp_path, "http://ollama", "m", force_rebuild=False)
    assert g is not None
    assert len(g.nodes) == 0


def test_load_doc_graph_builds_when_forced(tmp_path: Path, monkeypatch) -> None:
    def _stub(root, ollama_url="", light_model=""):
        g = DocGraph(root)
        g.add_file_node("a.md", summary="s")
        return g

    monkeypatch.setattr("palimind.document.graph.build_doc_graph", _stub)
    g = load_doc_graph(tmp_path, "http://ollama", "m", force_rebuild=True)
    assert "file:a.md" in g.nodes


def test_incremental_drops_deleted_and_refreshes_changed(
    tmp_path: Path, monkeypatch
) -> None:
    from palimind.document.graph import build_doc_graph_incremental
    from palimind.storage import db as db_module

    (tmp_path / ".palimind").mkdir()
    g = DocGraph(tmp_path)
    g.add_file_node("a.md", summary="A", md5="h1")
    g.add_file_node("b.md", summary="B", md5="h1")
    g.add_file_node("c.md", summary="C", md5="h1")
    g.file_hashes = {"a.md": "h1", "b.md": "h1", "c.md": "h1"}
    g.save()

    # Simulate index state: b.md deleted, a.md modified (new hash).
    monkeypatch.setattr(
        db_module,
        "get_files_with_hash",
        lambda conn: [
            {"path": "a.md", "md5": "h2", "summary": "A v2", "doc_year": None,
             "doc_type": "other", "entity_name": "SharedCo"},
            {"path": "c.md", "md5": "h1", "summary": "C", "doc_year": None,
             "doc_type": "other", "entity_name": ""},
        ],
    )
    monkeypatch.setattr(
        "palimind.document.graph._extract_entities_batched", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "palimind.document.graph._write_entity_mentions", lambda *a, **k: None
    )

    out = build_doc_graph_incremental(tmp_path, "http://ollama", "m")
    assert out.file_nodes.get("b.md") is None  # deleted path removed
    assert out.file_nodes.get("a.md") is not None  # re-added
    assert out.file_hashes["a.md"] == "h2"  # hash map refreshed
    assert out.file_hashes["c.md"] == "h1"  # untouched file stays


def test_incremental_falls_back_to_full_build_when_empty(
    tmp_path: Path, monkeypatch
) -> None:
    from palimind.document.graph import build_doc_graph_incremental

    (tmp_path / ".palimind").mkdir()

    def _stub(root, ollama_url="", light_model=""):
        g = DocGraph(root)
        g.add_file_node("x.md", summary="s")
        return g

    monkeypatch.setattr("palimind.document.graph.build_doc_graph", _stub)
    out = build_doc_graph_incremental(tmp_path, "http://ollama", "m")
    assert "file:x.md" in out.nodes
