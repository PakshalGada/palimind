"""Tests for first-class projects: CRUD, isolation, KB and artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def project_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "palimind-home"
    monkeypatch.setenv("PALIMIND_HOME", str(home))
    monkeypatch.setenv("PALIMIND_STATE_DB", str(home / "state.db"))
    return tmp_path


def test_project_crud_and_folder_lifecycle(project_home: Path) -> None:
    from palimind.projects import store

    assert store.list_projects() == []

    workspace = project_home / "workspace"
    project = store.create_project("Alpha", "A project", workspace_path=workspace)
    root = store.project_dir(project["id"])
    assert root.is_dir()
    assert workspace.is_dir()
    assert project["workspace_path"] == str(workspace.resolve())
    assert project["scope"] == f"project:{project['id']}"

    loaded = store.get_project(project["id"])
    assert loaded is not None
    assert loaded["name"] == "Alpha"

    updated = store.update_project(project["id"], {"name": "Beta", "description": "changed"})
    assert updated is not None
    assert updated["name"] == "Beta"
    assert updated["description"] == "changed"

    assert [p["id"] for p in store.list_projects("beta")] == [project["id"]]
    assert store.list_projects("no-such-project") == []

    opened = store.touch_project(project["id"])
    assert opened is not None
    assert opened["last_opened_at"] is not None

    assert store.delete_project(project["id"]) is True
    assert not root.exists()
    assert store.get_project(project["id"]) is None
    # The user's workspace is never deleted.
    assert workspace.is_dir()


def test_rejects_invalid_project_id(project_home: Path) -> None:
    from palimind.projects import store

    with pytest.raises(ValueError):
        store.project_dir("../escape")


def test_project_sessions_are_isolated(project_home: Path) -> None:
    from palimind.projects import session_store, store

    first = store.create_project("First")
    second = store.create_project("Second")

    first_sessions = session_store.new_session(first["id"], "First chat")
    second_sessions = session_store.new_session(second["id"], "Second chat")

    first_id = first_sessions["active_session_id"]
    second_id = second_sessions["active_session_id"]
    assert first_id and second_id

    session_store.append_message(first["id"], first_id, "user", "only in first")
    session_store.append_message(second["id"], second_id, "user", "only in second")

    first_loaded = session_store.list_sessions(first["id"])
    second_loaded = session_store.list_sessions(second["id"])
    assert first_loaded["sessions"][0]["messages"][0]["content"] == "only in first"
    assert second_loaded["sessions"][0]["messages"][0]["content"] == "only in second"
    assert first_loaded["active_session_id"] != second_loaded["active_session_id"]


def test_project_kb_sync_uses_isolated_store(project_home: Path, monkeypatch) -> None:
    from palimind.models import UpdateIndexResult
    from palimind.projects import kb, store

    workspace = project_home / "docs"
    workspace.mkdir()
    (workspace / "note.md").write_text("# Hello\n\nProject note.", encoding="utf-8")

    project = store.create_project("KB", workspace_path=workspace)
    root = store.project_dir(project["id"])
    seen: dict[str, Path] = {}

    def fake_update(
        storage_root: Path,
        *,
        on_progress=None,
        source_root: Path | None = None,
    ) -> UpdateIndexResult:
        seen["storage"] = storage_root
        assert source_root is not None
        seen["source"] = source_root
        return UpdateIndexResult(
            indexed_files=1,
            deleted_files=0,
            unchanged_files=0,
            chunks_indexed=2,
        )

    monkeypatch.setattr(kb, "update_index", fake_update)

    result = kb.sync_project_kb(project["id"])
    assert result["status"] == "success"
    assert result["indexed_files"] == 1
    assert seen["storage"] == root
    assert seen["source"] == workspace.resolve()
    assert (root / ".palimind" / "config.json").exists()
    assert (root / ".palimind" / "index.db").exists()

    status = kb.kb_status(project["id"])
    assert status["project_id"] == project["id"]
    assert status["status"] == "idle"


def test_project_kb_actually_indexes_into_project_root(
    project_home: Path, monkeypatch
) -> None:
    """The FAISS/SQLite index must live in the project folder, not the workspace."""
    from palimind.projects import kb, store
    from palimind.rag import indexing as indexing_mod

    workspace = project_home / "real-docs"
    workspace.mkdir()
    (workspace / "note.md").write_text(
        "# Notes\n\n" + ("The project stores its own isolated index. " * 30),
        encoding="utf-8",
    )

    project = store.create_project("Indexed", workspace_path=workspace)
    root = store.project_dir(project["id"])

    def fake_embeddings(texts, _url, _model, root=None):  # noqa: ANN001
        return [[0.01 * (i + 1)] * 8 for i in range(len(texts))]

    monkeypatch.setattr(indexing_mod, "generate_embeddings_batch", fake_embeddings)

    result = kb.sync_project_kb(project["id"])
    assert result["indexed_files"] == 1
    assert result["chunks_indexed"] >= 1
    assert (root / ".palimind" / "faiss.index").exists()
    assert not (workspace / ".palimind").exists()

    status = kb.kb_status(project["id"])
    assert status["has_index"] is True
    assert status["indexed_files"] == 1
    assert status["chunks"] >= 1


def test_project_artifacts_versions_and_export(project_home: Path) -> None:
    from palimind.projects import artifacts, store

    project = store.create_project("Artifacts")
    saved = artifacts.save_artifact(
        project["id"],
        {
            "title": "Landing page",
            "type": "html",
            "content": "<h1>v1</h1>",
            "session_id": "session-1",
        },
    )
    assert saved["current_version"] == 1
    assert saved["session_id"] == "session-1"
    assert saved["versions"][0]["version"] == 1

    updated = artifacts.add_version(
        project["id"], saved["id"], {"content": "<h1>v2</h1>"}
    )
    assert updated["current_version"] == 2
    assert len(updated["versions"]) == 2

    latest = artifacts.get_artifact(project["id"], saved["id"])
    assert latest["content"] == "<h1>v2</h1>"
    first = artifacts.get_artifact(project["id"], saved["id"], version=1)
    assert first["content"] == "<h1>v1</h1>"

    listed = artifacts.list_artifacts(project["id"])
    assert len(listed) == 1
    assert listed[0]["title"] == "Landing page"

    path, filename, mime_type = artifacts.export_artifact(
        project["id"], saved["id"], version=1
    )
    assert path.read_text(encoding="utf-8") == "<h1>v1</h1>"
    assert filename.endswith(".html")
    assert mime_type == "text/html"

    assert artifacts.delete_artifact(project["id"], saved["id"]) is True
    assert artifacts.list_artifacts(project["id"]) == []


def test_project_api_crud_and_scope_sessions(project_home: Path) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    assert client.get("/health").status_code == 200

    workspace = project_home / "api-workspace"
    response = client.post(
        "/api/projects",
        json={"name": "API project", "workspace_path": str(workspace)},
    )
    assert response.status_code == 201
    project = response.json()
    project_id = project["id"]
    assert project["scope"] == f"project:{project_id}"

    listed = client.get("/api/projects").json()["projects"]
    assert [p["id"] for p in listed] == [project_id]

    # Project-scoped sessions use the private project store.
    sessions = client.get(f"/api/sessions?scope=project:{project_id}").json()
    assert sessions["active_session_id"]

    from palimind.projects import session_store

    session_id = sessions["active_session_id"]
    session_store.append_message(project_id, session_id, "user", "persisted in project")
    reloaded = client.get(f"/api/sessions?scope=project:{project_id}").json()
    assert reloaded["sessions"][0]["messages"][0]["content"] == "persisted in project"

    opened = client.post(f"/api/projects/{project_id}/open").json()
    assert opened["scope"] == f"project:{project_id}"

    # Artifact collection + export through the router.
    created_artifact = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={"title": "Snippet", "type": "markdown", "content": "# v1"},
    )
    assert created_artifact.status_code == 201
    artifact = created_artifact.json()
    assert artifact["current_version"] == 1
    versioned = client.post(
        f"/api/projects/{project_id}/artifacts/{artifact['id']}/versions",
        json={"content": "# v2"},
    )
    assert versioned.status_code == 201
    assert versioned.json()["current_version"] == 2
    artifacts_list = client.get(f"/api/projects/{project_id}/artifacts").json()
    assert [a["id"] for a in artifacts_list["artifacts"]] == [artifact["id"]]
    exported = client.get(
        f"/api/projects/{project_id}/artifacts/{artifact['id']}/export?version=1"
    )
    assert exported.status_code == 200
    assert exported.text == "# v1"

    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get("/api/projects").json()["projects"] == []


def test_project_chat_routes_to_project_root(project_home: Path, monkeypatch) -> None:
    """A project chat must stream against the project's private store."""
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient

    import palimind.api_server as server
    from palimind.projects import store

    project = store.create_project("Chat project")
    expected_root = store.project_dir(project["id"])
    seen: dict[str, Path] = {}

    def fake_resolve_model(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return "test-model", "http://127.0.0.1:11434", ""

    async def fake_stream(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["root"] = args[7]
        seen["session"] = args[1]

        async def gen():
            yield 'data: {"type": "done"}\n\n'

        return StreamingResponse(gen(), media_type="text/event-stream")

    monkeypatch.setattr("palimind.opencode.router.resolve_model", fake_resolve_model)
    monkeypatch.setattr(server, "llm_mode_stream", fake_stream)

    client = TestClient(server.app)
    sessions = client.get(f"/api/sessions?scope=project:{project['id']}").json()
    assert sessions["active_session_id"]
    response = client.get(
        f"/api/chat?q=hello&scope=project:{project['id']}&chat_mode=llm&llm_sub_mode=default"
    )
    assert response.status_code == 200
    assert seen["root"] == expected_root
    assert seen["session"] == sessions["active_session_id"]
