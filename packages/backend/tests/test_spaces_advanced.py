"""Advanced space features: cross-space search, digests, signals, policy, quota."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from palimind import spaces
from palimind.spaces import analysis, digest, policy, research
from palimind.spaces import sources as sources_mod
from palimind.storage.db import (
    get_connection,
    insert_chunks,
    insert_entity_mentions,
    upsert_file,
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path: Path):
    import palimind.api_server as server

    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(server, "GLOBAL_CONFIG_PATH", tmp_path / "global.json")
    monkeypatch.setattr(server.state, "fields", [])
    monkeypatch.setattr(server.state, "active_field", None)
    monkeypatch.setattr(server.state, "active_space_id", None)
    yield


def _space(tmp_path: Path, name: str) -> dict:
    parent = tmp_path / "vault"
    parent.mkdir(exist_ok=True)
    return spaces.create_space(name, parent_dir=str(parent))


def test_cross_space_search_annotates_and_dedupes(tmp_path: Path, monkeypatch) -> None:
    from palimind import knowledge
    from palimind.spaces import search as search_mod

    first = _space(tmp_path, "Alpha")
    second = _space(tmp_path, "Beta")

    def fake_search(root, query, **kwargs):
        name = "Alpha" if str(root) == first["root"] else "Beta"
        return {
            "results": [
                {
                    "file_path": f"sources/{name}.md",
                    "section": "Intro",
                    "score": 0.9 if name == "Alpha" else 0.4,
                    "content": f"{name} answer",
                    "url": f"https://example.com/{name.lower()}",
                }
            ],
            "errors": [],
        }

    monkeypatch.setattr(knowledge, "search", fake_search)
    payload = search_mod.search_all("answer", limit_per_space=3)

    assert payload["spaces_searched"] == 2
    assert [item["space_name"] for item in payload["results"]] == ["Alpha", "Beta"]
    assert payload["by_space"] == {"Alpha": 1, "Beta": 1}
    assert all(item["space_id"] in {first["id"], second["id"]} for item in payload["results"])


def test_digest_creation_is_idempotent_per_day(tmp_path: Path) -> None:
    space = _space(tmp_path, "Digest")
    root = Path(space["root"])
    sources_mod.create_text_source(root, "A new note", title="New note")

    built = digest.build_digest(root, days=1)
    assert built["source_count"] == 1
    assert "New note" in built["text"]

    first = digest.create_digest(root)
    assert first["status"] == "created"
    assert (root / first["source"]["file_path"]).is_file()

    second = digest.create_digest(root)
    assert second["status"] == "exists"

    forced = digest.create_digest(root, force=True)
    assert forced["status"] == "created"
    assert forced["source"]["id"] != first["source"]["id"]


def test_due_digests_respects_space_toggle(tmp_path: Path) -> None:
    space = _space(tmp_path, "Daily")
    spaces.update_space(space["id"], {"digest_enabled": True})
    first = digest.run_due_digests()
    assert first["created"] == 1

    spaces.update_space(space["id"], {"digest_enabled": False})
    second = digest.run_due_digests()
    assert second["created"] == 0


def test_contradictions_and_aliases_from_entity_mentions(tmp_path: Path) -> None:
    space = _space(tmp_path, "Signals")
    root = Path(space["root"])
    conn = get_connection(root)
    try:
        first = upsert_file(conn, "a.md", "h1", time.time(), doc_type="note")
        second = upsert_file(conn, "b.md", "h2", time.time(), doc_type="note")
        ids_a = insert_chunks(
            conn,
            first,
            [(0, "text", "Acme revenue increased in 2024.", "Revenue", "", "", None, 6, 9)],
        )
        ids_b = insert_chunks(
            conn,
            second,
            [(0, "text", "Acme revenue decreased in 2024.", "Revenue", "", "", None, 6, 9)],
        )
        insert_entity_mentions(
            conn,
            [
                (ids_a[0], "Acme Inc.", "organization", ""),
                (ids_b[0], "ACME Corporation", "organization", ""),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    contradictions = analysis.contradiction_candidates(root)
    assert len(contradictions) >= 1
    assert contradictions[0]["entity"].lower().startswith("acme")
    assert "opposing" in contradictions[0]["reason"] or "negated" in contradictions[0]["reason"]

    aliases = analysis.entity_aliases(root)
    assert any(len(item["labels"]) >= 2 for item in aliases)


def test_domain_policy_and_quota(tmp_path: Path) -> None:
    space = _space(tmp_path, "Policy")
    root = Path(space["root"])
    spaces.update_space(
        space["id"],
        {"domain_mode": "deny", "domains": ["example.com"]},
    )
    blocked = sources_mod.create_web_source(root, "https://example.com/post")
    assert "blocked" in blocked.get("error", "").lower()

    allowed = sources_mod.create_web_source(root, "https://allowed.test/post")
    assert allowed.get("error") is None
    assert policy.domain_allowed(root, "https://sub.allowed.test/x")[0] is True

    spaces.update_space(space["id"], {"quota_bytes": 5})
    too_big = sources_mod.create_text_source(root, "this note is definitely too large")
    assert "quota" in too_big.get("error", "").lower()
    usage = policy.space_usage(root)
    assert usage["quota_bytes"] == 5


def test_research_source_saving_is_deduped(tmp_path: Path) -> None:
    space = _space(tmp_path, "Research")
    root = Path(space["root"])
    result = research.save_research_sources(
        root,
        [
            {"url": "https://example.com/a", "title": "A"},
            {"url": "https://example.com/a", "title": "A duplicate"},
            {"url": "", "title": "No URL"},
        ],
        tags=["research"],
    )
    assert len(result["sources"]) == 1
    listed = sources_mod.list_space_sources(root)
    assert listed["total"] == 1
    assert listed["sources"][0]["tags"] == ["research"]


def test_profiles_match_subdomains_and_headers() -> None:
    from palimind.spaces import profiles

    # Pure helper test; storage behaviour is covered through the HTTP/DB tests.
    profile = {
        "headers": {"X-API-Key": "secret"},
        "cookies": "session=abc",
        "user_agent": "CustomAgent/1.0",
    }
    headers = profiles.headers_for(profile)
    assert headers["X-API-Key"] == "secret"
    assert headers["Cookie"] == "session=abc"
    assert headers["User-Agent"] == "CustomAgent/1.0"


def test_advanced_http_surface(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    import palimind.api_server as server
    from palimind import knowledge

    monkeypatch.setattr(
        "palimind.spaces.ingest.schedule_ingest", lambda *args, **kwargs: None
    )
    client = TestClient(server.app)
    parent = tmp_path / "vault"
    parent.mkdir()
    created = client.post(
        "/api/spaces",
        json={"name": "HTTP Space", "parent_dir": str(parent), "index": False},
    ).json()
    space_id = created["space"]["id"]
    root = Path(created["space"]["root"])
    sources_mod.create_text_source(root, "Searchable body", title="HTTP note")

    monkeypatch.setattr(
        knowledge,
        "search",
        lambda root, query, **kwargs: {
            "results": [
                {
                    "file_path": "sources/text/note.md",
                    "section": "Intro",
                    "score": 0.8,
                    "content": "Searchable body",
                    "url": "https://example.com/note",
                }
            ],
            "errors": [],
        },
    )
    found = client.get("/api/spaces/search", params={"q": "body"}).json()
    assert found["total"] == 1
    assert found["results"][0]["space_name"] == "HTTP Space"

    policy = client.patch(
        f"/api/spaces/{space_id}/policy",
        json={"domain_mode": "allow", "domains": ["example.com"], "quota_bytes": 1048576, "digest_enabled": True},
    ).json()
    assert policy["status"] == "success"
    assert policy["space"]["domain_mode"] == "allow"

    usage = client.get(f"/api/spaces/{space_id}/usage").json()
    assert usage["quota_bytes"] == 1048576
    assert usage["total_bytes"] > 0

    digest = client.post(f"/api/spaces/{space_id}/digest", json={"force": True}).json()
    assert digest["status"] == "created"
    listed = client.get(f"/api/spaces/{space_id}/digests").json()
    assert listed["digests"]

    signals = client.get(f"/api/spaces/{space_id}/signals").json()
    assert "aliases" in signals and "contradictions" in signals

    profile = client.post(
        f"/api/spaces/{space_id}/profiles",
        json={"name": "Example", "domain": "example.com", "headers": {"X-Key": "v"}},
    ).json()
    assert profile["status"] == "success"
    cached = client.get(f"/api/spaces/{space_id}/profiles").json()
    assert cached["profiles"][0]["domain"] == "example.com"
    removed = client.delete(
        f"/api/spaces/{space_id}/profiles/{profile['profile']['id']}"
    ).json()
    assert removed["removed"] is True

    saved = client.post(
        f"/api/spaces/{space_id}/sources/from-research",
        json={"sources": [{"url": "https://example.com/research", "title": "Research"}]},
    ).json()
    assert saved["status"] == "success"
    assert len(saved["sources"]) == 1


def test_agent_tool_supports_digest_and_cross_space_search(tmp_path: Path, monkeypatch) -> None:
    import importlib
    from palimind import knowledge

    tool = importlib.import_module("palimind.agents.tools.knowledge-space.tool")
    first = _space(tmp_path, "Tool Alpha")
    _space(tmp_path, "Tool Beta")
    sources_mod.create_text_source(Path(first["root"]), "tool note", title="Tool note")

    monkeypatch.setattr(
        knowledge,
        "search",
        lambda root, query, **kwargs: {
            "results": [{"file_path": "a.md", "content": "hit", "score": 0.5}],
            "errors": [],
        },
    )
    found = tool.knowledge_space(action="search_all", query="hit", space_id=first["id"])
    assert "Tool Alpha" in found and "Tool Beta" in found

    digest = tool.knowledge_space(action="digest", space_id=first["id"])
    assert "Digest" in digest


def test_retention_prunes_old_sources(tmp_path: Path) -> None:
    from palimind.spaces import retention

    space = _space(tmp_path, "Retention")
    root = Path(space["root"])
    record = sources_mod.create_text_source(root, "old note", title="Old")
    conn = get_connection(root)
    try:
        conn.execute(
            "UPDATE sources SET fetched_at = ?, created_at = ? WHERE id = ?",
            (time.time() - 10 * 86400, time.time() - 10 * 86400, record["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    preview = retention.prune_space(root, 5, dry_run=True)
    assert preview["would_remove"] == 1
    assert (root / record["file_path"]).is_file()

    result = retention.prune_space(root, 5)
    assert result["removed"] == 1
    assert not (root / record["file_path"]).exists()
    assert sources_mod.list_space_sources(root)["total"] == 0


def test_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    from palimind.spaces import backup

    space = _space(tmp_path, "Backup")
    root = Path(space["root"])
    note = sources_mod.create_text_source(root, "backup me", title="Backup note")
    data = backup.create_backup(root, space)
    assert data

    parent = tmp_path / "restored-parent"
    parent.mkdir()
    new_space = spaces.create_space("Restored", parent_dir=str(parent))
    result = backup.restore_backup(data, Path(new_space["root"]))
    assert result["restored_files"] >= 2
    assert (Path(new_space["root"]) / note["file_path"]).is_file()
    restored = sources_mod.list_space_sources(Path(new_space["root"]))
    assert restored["total"] == 1
    assert restored["sources"][0]["title"] == "Backup note"


def test_deep_research_save_helper(tmp_path: Path, monkeypatch) -> None:
    space = _space(tmp_path, "Deep")
    root = Path(space["root"])
    monkeypatch.setattr(
        "palimind.spaces.ingest.schedule_ingest", lambda *args, **kwargs: None
    )
    result = research.save_deep_research(
        root,
        [
            {"url": "https://example.com/one", "title": "One"},
            {"url": "https://example.com/two", "title": "Two"},
        ],
    )
    assert len(result["sources"]) == 2
    listed = sources_mod.list_space_sources(root)
    assert listed["total"] == 2
    assert listed["sources"][0]["tags"] == ["deep-research"]
    assert "deep-research" in (listed["sources"][0]["note"] or "")


def test_agreements_and_graph_confidence_timeline(tmp_path: Path) -> None:
    from palimind import knowledge
    from palimind.document.graph import DocGraph

    space = _space(tmp_path, "Timeline")
    root = Path(space["root"])
    conn = get_connection(root)
    try:
        first = upsert_file(conn, "a.md", "h1", time.time(), doc_type="note", doc_year=2020)
        second = upsert_file(conn, "b.md", "h2", time.time(), doc_type="note", doc_year=2024)
        ids_a = insert_chunks(
            conn,
            first,
            [(0, "text", "Acme revenue increased sharply.", "Revenue", "", "", None, 5, 8)],
        )
        ids_b = insert_chunks(
            conn,
            second,
            [(0, "text", "Acme revenue increased sharply this year.", "Revenue", "", "", None, 6, 9)],
        )
        insert_entity_mentions(
            conn,
            [
                (ids_a[0], "Acme", "organization", ""),
                (ids_b[0], "Acme", "organization", ""),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    agreements = analysis.agreement_candidates(root)
    assert agreements and agreements[0]["entity"] == "Acme"

    graph = DocGraph(root)
    graph.add_file_node("a.md", label="A", doc_year=2020)
    graph.add_file_node("b.md", label="B", doc_year=2024)
    graph.add_edge("file:a.md", "file:b.md", "related")
    graph.save()

    full = knowledge.graph_payload(root)
    assert full["edges"][0]["confidence"] > 0
    assert full["typed_relations"].get("related") == 1
    assert full["edges"][0]["relation"] == "related"

    payload = knowledge.graph_payload(root, since_year=2023)
    assert [n["file_path"] for n in payload["nodes"] if n["type"] == "file"] == ["b.md"]


def test_capture_link_endpoint_for_extension_and_share_sheet(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    import palimind.api_server as server

    monkeypatch.setattr(
        "palimind.spaces.ingest.schedule_ingest", lambda *args, **kwargs: None
    )
    _space(tmp_path, "Capture")
    client = TestClient(server.app)

    saved = client.post(
        "/api/capture/link",
        json={"url": "https://example.com/shared", "title": "Shared page"},
    ).json()
    assert saved["status"] == "success"
    assert saved["source"]["url"] == "https://example.com/shared"

    receipt = client.get(
        "/api/capture/link",
        params={"url": "https://example.com/from-share-sheet", "format": "json"},
    ).json()
    assert receipt["status"] == "success"
