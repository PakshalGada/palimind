"""Tests for the global artifact library and export endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def artifact_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "palimind-home"
    monkeypatch.setenv("PALIMIND_HOME", str(home))
    monkeypatch.setenv("PALIMIND_STATE_DB", str(home / "state.db"))
    return home


def test_global_artifact_library_and_exports(artifact_home: Path) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    created = client.post(
        "/api/artifacts",
        json={
            "title": "Export demo",
            "type": "markdown",
            "language": "md",
            "content": "# Hello\n\nA small artifact.",
        },
    )
    assert created.status_code == 201
    artifact = created.json()
    artifact_id = artifact["id"]

    listed = client.get("/api/artifacts").json()["artifacts"]
    assert [item["id"] for item in listed] == [artifact_id]
    assert client.get("/api/artifacts?q=hello").json()["artifacts"][0]["id"] == artifact_id
    assert client.get(f"/api/artifacts/{artifact_id}").json()["content"].startswith("# Hello")

    for fmt in ("md", "html", "pdf", "docx", "pptx", "png"):
        response = client.post(
            f"/api/artifacts/{artifact_id}/export", json={"format": fmt}
        )
        assert response.status_code == 200, fmt
        assert len(response.content) > 10
        assert "attachment" in response.headers.get("content-disposition", "")

    export_dir = artifact_home / "artifacts" / "exports"
    assert export_dir.is_dir()
    assert any(export_dir.glob(f"{artifact_id}.pdf"))
    assert any(export_dir.glob(f"{artifact_id}.png"))

    assert client.delete(f"/api/artifacts/{artifact_id}").json()["deleted"] is True
    assert client.get(f"/api/artifacts/{artifact_id}").status_code == 404


def test_project_artifact_export(artifact_home: Path) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server
    from palimind.projects import store

    project = store.create_project("Artifact project")
    client = TestClient(server.app)
    saved = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "title": "Slides",
            "type": "slide-outline",
            "content": "# Intro\n\n- First point\n\n# Second slide\n\n- Another point",
        },
    )
    assert saved.status_code == 201
    artifact_id = saved.json()["id"]

    listed = client.get(
        f"/api/projects/{project['id']}/artifacts?include_content=true"
    ).json()["artifacts"]
    assert listed[0]["content"].startswith("# Intro")

    exported = client.post(
        f"/api/projects/{project['id']}/artifacts/{artifact_id}/export",
        json={"format": "pptx"},
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml"
    )
    assert (store.project_dir(project["id"]) / "artifacts" / "exports" / f"{artifact_id}.pptx").exists()
