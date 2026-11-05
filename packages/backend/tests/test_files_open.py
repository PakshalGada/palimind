"""Tests for opening workspace files from chat citations."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _client() -> TestClient:
    import palimind.api_server as server

    return TestClient(server.app)


def test_open_file_serves_workspace_document(tmp_path: Path, monkeypatch) -> None:
    import palimind.api_server as server

    monkeypatch.setattr(server.state, "active_field", tmp_path)
    target = tmp_path / "docs" / "notes.md"
    target.parent.mkdir()
    target.write_text("# Notes\n\nA passage.", "utf-8")

    response = _client().get("/api/files/open", params={"path": "docs/notes.md"})

    assert response.status_code == 200
    assert response.text == "# Notes\n\nA passage."
    assert response.headers["content-type"].startswith("text/markdown")
    assert "inline" in response.headers["content-disposition"]


def test_open_file_forwards_section_header(tmp_path: Path, monkeypatch) -> None:
    import palimind.api_server as server

    monkeypatch.setattr(server.state, "active_field", tmp_path)
    (tmp_path / "paper.txt").write_text("body", "utf-8")

    response = _client().get(
        "/api/files/open",
        params={"path": "paper.txt", "section": "Introduction"},
    )

    assert response.status_code == 200
    assert response.headers["x-source-section"] == "Introduction"


def test_open_file_rejects_paths_outside_workspace(tmp_path: Path, monkeypatch) -> None:
    import palimind.api_server as server

    root = tmp_path / "field"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", "utf-8")
    monkeypatch.setattr(server.state, "active_field", root)

    response = _client().get("/api/files/open", params={"path": "../secret.txt"})

    assert response.status_code == 403


def test_open_file_requires_an_active_field(tmp_path: Path, monkeypatch) -> None:
    import palimind.api_server as server

    monkeypatch.setattr(server.state, "active_field", None)

    response = _client().get("/api/files/open", params={"path": "notes.md"})

    assert response.status_code == 404


def test_open_file_reports_missing_file(tmp_path: Path, monkeypatch) -> None:
    import palimind.api_server as server

    monkeypatch.setattr(server.state, "active_field", tmp_path)

    response = _client().get("/api/files/open", params={"path": "missing.md"})

    assert response.status_code == 404
