"""Knowledge space lifecycle tests (registry + HTTP surface)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palimind import spaces


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path: Path):
    import palimind.api_server as server

    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(server, "GLOBAL_CONFIG_PATH", tmp_path / "global.json")
    monkeypatch.setattr(server.state, "fields", [])
    monkeypatch.setattr(server.state, "active_field", None)
    monkeypatch.setattr(server.state, "active_space_id", None)
    yield


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    path = tmp_path / "vault"
    path.mkdir()
    return path


def test_create_managed_space_makes_folder_and_index(vault: Path) -> None:
    record = spaces.create_space("Research Notes", parent_dir=str(vault))

    root = Path(record["root"])
    assert root == (vault / "Research Notes").resolve()
    assert root.is_dir()
    assert (root / ".palimind" / "config.json").is_file()
    assert record["kind"] == "managed"
    assert spaces.active_space_id() == record["id"]
    assert [s["id"] for s in spaces.list_spaces()] == [record["id"]]


def test_link_existing_folder_never_creates_content(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "note.md").write_text("# hi", "utf-8")

    record = spaces.create_space("Existing", root=str(existing), mode="link")

    assert record["kind"] == "linked"
    assert Path(record["root"]) == existing.resolve()
    assert sorted(p.name for p in existing.iterdir()) == [".palimind", "note.md"]


def test_duplicate_non_empty_folder_is_rejected(vault: Path) -> None:
    target = vault / "Taken"
    target.mkdir()
    (target / "x.txt").write_text("x", "utf-8")

    with pytest.raises(spaces.SpaceError):
        spaces.create_space("Taken", parent_dir=str(vault))


def test_path_separator_in_name_is_rejected(vault: Path) -> None:
    with pytest.raises(spaces.SpaceError):
        spaces.create_space("../escape", parent_dir=str(vault))


def test_delete_keeps_files_by_default(vault: Path) -> None:
    record = spaces.create_space("Keep", parent_dir=str(vault))
    root = Path(record["root"])
    (root / "note.md").write_text("body", "utf-8")

    assert spaces.delete_space(record["id"]) is True
    assert root.is_dir()
    assert spaces.get_space(record["id"]) is None
    assert spaces.delete_space(record["id"]) is False


def test_migrate_legacy_fields(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()

    created = spaces.migrate_legacy_fields([str(legacy), str(legacy)])

    assert created == 1
    assert spaces.find_by_root(legacy) is not None
    # Running the migration again must not duplicate the space.
    assert spaces.migrate_legacy_fields([str(legacy)]) == 0


def test_spaces_http_surface(vault: Path) -> None:
    import palimind.api_server as server

    client = TestClient(server.app)

    created = client.post(
        "/api/spaces",
        json={"name": "Web", "parent_dir": str(vault), "index": False},
    ).json()
    assert created["status"] == "success"
    space_id = created["space"]["id"]

    listed = client.get("/api/spaces").json()
    assert [s["name"] for s in listed["spaces"]] == ["Web"]
    assert listed["active_space_id"] == space_id
    assert server.state.active_field == Path(created["space"]["root"])

    renamed = client.patch(f"/api/spaces/{space_id}", json={"name": "Web KB"}).json()
    assert renamed["space"]["name"] == "Web KB"

    activated = client.post(f"/api/spaces/{space_id}/activate").json()
    assert activated["status"] == "success"

    removed = client.delete(f"/api/spaces/{space_id}").json()
    assert removed["removed"] is True
    assert Path(created["space"]["root"]).is_dir()

    # The legacy folder config and the space registry must stay in sync.
    saved = json.loads(Path(server.GLOBAL_CONFIG_PATH).read_text("utf-8"))
    assert saved["fields"] == []


def test_sources_and_collections_http_surface(vault: Path, monkeypatch) -> None:
    import palimind.api_server as server
    from palimind.api_routers.routers import spaces as spaces_router

    client = TestClient(server.app)
    created = client.post(
        "/api/spaces", json={"name": "Sources", "parent_dir": str(vault), "index": False}
    ).json()
    space_id = created["space"]["id"]

    # URL ingestion is backgrounded; do not reach the network in this test.
    monkeypatch.setattr(spaces_router, "_schedule_ingest", lambda *args, **kwargs: None)

    note = client.post(
        f"/api/spaces/{space_id}/sources",
        json={"text": "The graph connects ideas.", "title": "Note"},
    ).json()
    assert note["status"] == "success"
    note_id = note["sources"][0]["id"]

    link = client.post(
        f"/api/spaces/{space_id}/sources",
        json={"urls": ["https://example.com/post"]},
    ).json()
    assert link["status"] == "success"
    link_id = link["sources"][0]["id"]
    assert link["sources"][0]["status"] == "queued"

    listed = client.get(f"/api/spaces/{space_id}/sources").json()
    assert listed["total"] == 2
    assert {item["id"] for item in listed["sources"]} == {note_id, link_id}

    filtered = client.get(
        f"/api/spaces/{space_id}/sources", params={"q": "Note"}
    ).json()
    assert [item["id"] for item in filtered["sources"]] == [note_id]

    patched = client.patch(
        f"/api/spaces/{space_id}/sources/{link_id}",
        json={"title": "Renamed", "reading_state": "read", "favorite": True},
    ).json()
    assert patched["source"]["title"] == "Renamed"
    assert patched["source"]["reading_state"] == "read"
    assert patched["source"]["favorite"] is True

    content = client.get(
        f"/api/spaces/{space_id}/sources/{note_id}/content"
    ).json()
    assert "The graph connects ideas." in content["content"]

    collection = client.post(
        f"/api/spaces/{space_id}/collections", json={"name": "Graphs"}
    ).json()["collection"]
    attached = client.post(
        f"/api/spaces/{space_id}/sources/{note_id}/collections",
        json={"collection_id": collection["id"]},
    ).json()
    assert attached["status"] == "success"
    in_collection = client.get(
        f"/api/spaces/{space_id}/sources", params={"collection": collection["id"]}
    ).json()
    assert [item["id"] for item in in_collection["sources"]] == [note_id]

    removed = client.delete(
        f"/api/spaces/{space_id}/sources/{link_id}"
    ).json()
    assert removed["removed"] is True
    assert client.get(f"/api/spaces/{space_id}/sources").json()["total"] == 1
