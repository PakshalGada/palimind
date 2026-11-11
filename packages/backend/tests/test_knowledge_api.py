"""Tests for the Knowledge workspace service and HTTP surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palimind import knowledge
from palimind.rag.indexing import initialize_index
from palimind.storage.db import get_connection, insert_chunks, upsert_file, upsert_file_summary


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    yield


@pytest.fixture()
def field(tmp_path: Path) -> Path:
    root = tmp_path / "field"
    root.mkdir()
    (root / "reports").mkdir()
    (root / "reports" / "annual_2024.pdf").write_text("revenue", "utf-8")
    (root / "notes.md").write_text("# Notes\n\nAcme plans to expand.", "utf-8")
    initialize_index(root)

    conn = get_connection(root)
    try:
        first = upsert_file(
            conn,
            "reports/annual_2024.pdf",
            "hash-a",
            1_700_000_000.0,
            doc_year=2024,
            doc_type="report",
            entity_name="Acme",
        )
        insert_chunks(
            conn,
            first,
            [
                (
                    0,
                    "text",
                    "Acme reported total revenue of $4.2 billion in 2024.",
                    "Revenue",
                    "",
                    "Financials",
                    4,
                    8,
                    12,
                    None,
                    None,
                    "Acme revenue",
                    "Financials",
                ),
                (
                    1,
                    "text",
                    "Operating margin improved year over year.",
                    "Margins",
                    "",
                    "Financials",
                    5,
                    6,
                    9,
                    None,
                    None,
                    "Acme margin",
                    "Financials",
                ),
            ],
        )
        upsert_file_summary(conn, "reports/annual_2024.pdf", "Annual report for Acme.")
        second = upsert_file(
            conn,
            "notes.md",
            "hash-b",
            1_700_000_100.0,
            doc_type="note",
        )
        insert_chunks(
            conn,
            second,
            [
                (
                    0,
                    "text",
                    "Acme plans to expand into Europe.",
                    "Expansion",
                    "",
                    "Notes",
                    1,
                    7,
                    10,
                    None,
                    None,
                    "Acme expansion",
                    "Notes",
                )
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return root


def _client() -> TestClient:
    import palimind.api_server as server

    return TestClient(server.app)


def test_stats_include_breakdowns_and_model(field: Path) -> None:
    stats = knowledge.collect_stats(field)

    assert stats["files"] == 2
    assert stats["chunks"] == 3
    assert stats["summaries"] == 1
    assert stats["types"][0]["files"] >= 1
    assert {item["year"] for item in stats["years"]} == {2024}
    assert stats["index_model"]
    assert stats["retrieval"]["retrieval_limit"] >= 1


def test_list_files_filters_and_pagination(field: Path) -> None:
    result = knowledge.list_files(field)
    assert result["total"] == 2
    assert {f["path"] for f in result["files"]} == {
        "reports/annual_2024.pdf",
        "notes.md",
    }

    reports = knowledge.list_files(field, doc_type="report")
    assert reports["total"] == 1
    assert reports["files"][0]["doc_year"] == 2024
    assert reports["files"][0]["has_summary"] is True

    no_summary = knowledge.list_files(field, status="no-summary")
    assert [f["path"] for f in no_summary["files"]] == ["notes.md"]

    searched = knowledge.list_files(field, q="annual")
    assert searched["total"] == 1

    page = knowledge.list_files(field, limit=1, offset=0)
    assert len(page["files"]) == 1
    assert page["total"] == 2


def test_file_detail_includes_sections_and_entities(field: Path) -> None:
    detail = knowledge.get_file_detail(field, "reports/annual_2024.pdf")
    assert detail is not None
    assert detail["chunks"] == 2
    assert detail["summary"] == "Annual report for Acme."
    assert {section["title"] for section in detail["sections"]} == {"Revenue", "Margins"}
    assert detail["previews"][0]["content"].startswith("Acme reported")

    assert knowledge.get_file_detail(field, "missing.md") is None


def test_remove_file_clears_index_but_not_disk(field: Path) -> None:
    assert knowledge.remove_file(field, "notes.md") is True
    assert (field / "notes.md").is_file()

    result = knowledge.list_files(field)
    assert {f["path"] for f in result["files"]} == {"reports/annual_2024.pdf"}
    assert knowledge.remove_file(field, "notes.md") is False


def test_settings_update_validates_and_persists(field: Path) -> None:
    settings = knowledge.update_settings(
        field,
        {
            "retrieval_limit": 12,
            "rerank": True,
            "mmr_lambda": 0.5,
            "agentic_rag": "always",
        },
    )
    assert settings["retrieval_limit"] == 12
    assert settings["rerank"] is True
    assert settings["mmr_lambda"] == 0.5
    assert settings["agentic_rag"] == "always"

    from palimind.config import load_config

    config = load_config(field)
    assert config["rerank_opt_in"] is True

    with pytest.raises(ValueError):
        knowledge.update_settings(field, {"retrieval_limit": 999})
    with pytest.raises(ValueError):
        knowledge.update_settings(field, {"agentic_rag": "sometimes"})
    with pytest.raises(ValueError):
        knowledge.update_settings(field, {"unknown_key": 1})


def test_diagnostics_reports_missing_summaries_and_sources(field: Path) -> None:
    (field / "notes.md").unlink()
    report = knowledge.diagnostics(field)

    codes = {issue["code"] for issue in report["issues"]}
    assert "missing_summaries" in codes or "missing_source_files" in codes
    assert "missing_source_files" in codes
    assert report["files"] == 2
    assert report["chunks"] == 3


def test_graph_payload_filters_and_reports_totals(field: Path) -> None:
    from palimind.document.graph import DocGraph

    graph = DocGraph(field)
    file_id = graph.add_file_node(
        "reports/annual_2024.pdf",
        label="annual_2024.pdf",
        doc_type="report",
        doc_year=2024,
    )
    other_id = graph.add_file_node("notes.md", label="notes.md", doc_type="note")
    entity_id = graph.add_entity_node("Acme")
    graph.add_edge(file_id, entity_id, "references")
    graph.add_edge(file_id, other_id, "related_via")
    graph.save()

    payload = knowledge.graph_payload(field, types=["file", "entity"], max_nodes=50)
    assert payload["total_nodes"] == 3
    assert payload["indexed_files"] == 2
    assert {node["type"] for node in payload["nodes"]} == {"file", "entity"}

    filtered = knowledge.graph_payload(field, doc_type="report")
    paths = {node["file_path"] for node in filtered["nodes"] if node["type"] == "file"}
    assert paths == {"reports/annual_2024.pdf"}
    # The entity attached to the report is retained.
    assert any(node["type"] == "entity" for node in filtered["nodes"])

    limited = knowledge.graph_payload(field, max_nodes=1)
    assert limited["node_count"] == 1
    assert limited["truncated"] is True


def test_reindex_file_forces_reembedding(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "reindex-field"
    root.mkdir()
    (root / "notes.md").write_text("# Notes\n\nAcme expands.\n" * 4, "utf-8")
    initialize_index(root)

    def _fake_embeddings(texts, *_args, **_kwargs):
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr("palimind.rag.indexing.generate_embeddings_batch", _fake_embeddings)

    first = knowledge.reindex_file(root, "notes.md")
    assert first["indexed"] == 1
    assert first["chunks"] >= 1

    # A second explicit reindex must do work even though the bytes did not
    # change (same hash is what a normal Sync would skip).
    second = knowledge.reindex_file(root, "notes.md")
    assert second["indexed"] == 1
    assert second["unchanged"] == 0


def test_http_endpoints_are_scope_aware(field: Path, monkeypatch) -> None:
    import palimind.api_server as server

    monkeypatch.setattr(server.state, "active_field", field)
    client = _client()

    stats = client.get("/api/document/stats").json()
    assert stats["files"] == 2

    files = client.get("/api/document/files", params={"q": "annual"}).json()
    assert files["total"] == 1

    detail = client.get(
        "/api/document/files/detail", params={"path": "reports/annual_2024.pdf"}
    ).json()
    assert detail["chunks"] == 2

    diagnostics = client.get("/api/document/diagnostics").json()
    assert diagnostics["files"] == 2

    config = client.get("/api/document/config").json()
    assert "retrieval_limit" in config

    patched = client.patch("/api/document/config", json={"retrieval_limit": 9}).json()
    assert patched["status"] == "success"
    assert patched["settings"]["retrieval_limit"] == 9

    invalid = client.patch("/api/document/config", json={"retrieval_limit": 0}).json()
    assert invalid["error"]

    removed = client.delete("/api/document/files", params={"path": "notes.md"}).json()
    assert removed["removed"] is True
    remaining = client.get("/api/document/files").json()
    assert [f["path"] for f in remaining["files"]] == ["reports/annual_2024.pdf"]


def test_sync_and_runs_endpoints_return_scoped_runs(field: Path, monkeypatch) -> None:
    import palimind.api_server as server
    from palimind.rag import incremental

    run = {
        "run_id": "run-1",
        "root": str(field),
        "status": "queued",
        "total": 2,
        "queued": 2,
        "indexed": 0,
        "deleted": 0,
        "unchanged": 0,
        "failed": 0,
        "phase": "queued",
        "message": "planned",
        "created_at": 1_700_000_000.0,
        "started_at": None,
        "finished_at": None,
        "errors": [],
    }
    monkeypatch.setattr(incremental, "enqueue_run", lambda *args, **kwargs: dict(run))
    monkeypatch.setattr(incremental, "list_runs", lambda limit=30: [dict(run)])

    monkeypatch.setattr(server.state, "active_field", field)
    client = _client()

    started = client.post("/api/document/sync").json()
    assert started["status"] == "success"
    assert started["run"]["run_id"] == "run-1"

    listed = client.get("/api/document/runs").json()
    assert [item["run_id"] for item in listed["runs"]] == ["run-1"]


def test_project_scope_uses_project_root(field: Path, tmp_path: Path, monkeypatch) -> None:
    import palimind.api_server as server
    from palimind.projects import kb, store

    workspace = tmp_path / "project-workspace"
    project = store.create_project("Scoped", workspace_path=workspace)
    (workspace / "only-project.txt").write_text("project-only content", "utf-8")
    project_root = kb.ensure_project_storage(project["id"])
    conn = get_connection(project_root)
    try:
        upsert_file(conn, "only-project.txt", "hash-p", 1_700_000_000.0, doc_type="note")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(server.state, "active_field", field)
    client = _client()

    field_stats = client.get("/api/document/stats").json()
    project_stats = client.get(
        "/api/document/stats", params={"scope": f"project:{project['id']}"}
    ).json()

    assert field_stats["files"] == 2
    assert project_stats["files"] == 1
    assert project_stats["root"] == str(project_root)

    project_files = client.get(
        "/api/document/files", params={"scope": f"project:{project['id']}"}
    ).json()
    assert [f["path"] for f in project_files["files"]] == ["only-project.txt"]

    detail = client.get(
        "/api/document/files/detail",
        params={"path": "only-project.txt", "scope": f"project:{project['id']}"},
    ).json()
    assert detail["exists_on_disk"] is True

    opened = client.get(
        "/api/files/open",
        params={"path": "only-project.txt", "scope": f"project:{project['id']}"},
    )
    assert opened.status_code == 200
    assert opened.text == "project-only content"

    from palimind.rag import incremental

    captured: dict[str, str] = {}

    def fake_enqueue(root, *, source_root=None, priority=0):
        captured["root"] = str(root)
        captured["source_root"] = str(source_root)
        return {"run_id": "project-run", "root": str(root), "status": "queued"}

    monkeypatch.setattr(incremental, "enqueue_run", fake_enqueue)
    started = client.post(
        "/api/document/sync", params={"scope": f"project:{project['id']}"}
    ).json()
    assert started["run"]["run_id"] == "project-run"
    assert Path(captured["source_root"]) == workspace
    assert Path(captured["root"]) == project_root
