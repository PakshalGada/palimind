"""Regression tests for storage/memory bugs (FTS syntax, episodic memory,
run ordering, artifact files, export filenames, embed cache pruning)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "palimind-home"
    monkeypatch.setenv("PALIMIND_HOME", str(home))
    monkeypatch.setenv("PALIMIND_STATE_DB", str(home / "state.db"))
    return tmp_path


# ── FTS5 query sanitising ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    ["COVID-19 report", "revenue AND profit", "NOT", "foo -bar", "NEAR(a b)", 'he said "x'],
)
def test_fts_search_survives_fts5_operators(tmp_path: Path, query: str) -> None:
    from palimind.storage import db

    (tmp_path / ".palimind").mkdir()
    db.init_db(tmp_path)
    conn = db.get_connection(tmp_path)
    try:
        fid = db.upsert_file(conn, "doc.txt", "h", 0.0)
        db.insert_chunks(
            conn,
            fid,
            [(0, "text", "COVID-19 report: revenue and profit, NOT near foo bar said x")],
        )
        conn.commit()
        assert db.fts_search(conn, query), query
        assert db.fts_search_filtered(conn, query, file_paths=["doc.txt"]), query
    finally:
        conn.close()


# ── episodic chat memory ──────────────────────────────────────────────────


def _episode(cid: int, sid: str, dim: int, seed: int) -> dict:
    vec = np.random.default_rng(seed).random(dim).astype("float32").tolist()
    return {"vector": vec, "chunk_id": cid, "session_id": sid, "content": f"turn {cid}"}


def test_chat_store_survives_embedding_dimension_change(tmp_path: Path) -> None:
    from palimind.storage.chat_store import ChatVectorStore, search_chat_episodes

    (tmp_path / ".palimind").mkdir()
    with ChatVectorStore(tmp_path) as vs:
        vs.insert([_episode(1, "s1", 8, 1)])
    # Model switched to a different dimension: inserts must keep working and
    # searches with the new dimension must not raise.
    new = _episode(2, "s1", 16, 2)
    with ChatVectorStore(tmp_path) as vs:
        vs.insert([new])
    hits = search_chat_episodes(tmp_path, new["vector"], limit=3)
    assert [h["chunk_id"] for h in hits] == [2]
    assert search_chat_episodes(tmp_path, [0.1] * 8, limit=3) == []


def test_delete_session_purges_episodic_memory(tmp_path: Path) -> None:
    from palimind.memory import session_store
    from palimind.storage.chat_store import ChatVectorStore, search_chat_episodes

    data = session_store.add_new_session(tmp_path, "one")
    sid = data["active_session_id"]
    keep = session_store.add_new_session(tmp_path, "two")["active_session_id"]
    gone, kept = _episode(1, sid, 8, 1), _episode(2, keep, 8, 2)
    with ChatVectorStore(tmp_path) as vs:
        vs.insert([gone, kept])

    session_store.delete_session(tmp_path, sid)

    hits = search_chat_episodes(tmp_path, gone["vector"], limit=5)
    assert [h["session_id"] for h in hits] == [keep]


# ── agent run history ordering ────────────────────────────────────────────


def test_list_runs_returns_newest_when_limited(isolated_home: Path) -> None:
    from palimind.storage import state_store

    for i in range(5):
        state_store.append_run("a1", f"r{i}", {"run_id": f"r{i}", "timestamp": 100.0 + i}, 50)
    latest = state_store.list_runs("a1", limit=1)
    assert [r["run_id"] for r in latest] == ["r4"]
    two = state_store.list_runs("a1", limit=2)
    assert [r["run_id"] for r in two] == ["r3", "r4"]  # still chronological


# ── board tasks: concurrent read-modify-write ─────────────────────────────


def test_task_store_concurrent_updates_are_not_lost(isolated_home: Path, monkeypatch) -> None:
    import threading

    from palimind.storage import task_store

    monkeypatch.setattr(task_store, "TASKS_FILE", isolated_home / "no-legacy.json")
    ids = [task_store.create_task({"title": f"t{i}"})["id"] for i in range(16)]
    threads = [
        threading.Thread(target=task_store.update_task, args=(tid, {"status": "completed"}))
        for tid in ids
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = [t["status"] for t in task_store.list_tasks()]
    assert statuses.count("completed") == 16


# ── project artifacts ─────────────────────────────────────────────────────


def test_project_artifact_without_extension_is_readable(isolated_home: Path) -> None:
    from palimind.projects import artifacts, store

    project = store.create_project("p", workspace_path=isolated_home / "ws")
    saved = artifacts.save_artifact(
        project["id"], {"content": "# hi", "type": "markdown", "filename": "README"}
    )
    loaded = artifacts.get_artifact(project["id"], saved["id"])
    assert loaded["content"] == "# hi"
    path, filename, _mime = artifacts.export_artifact(project["id"], saved["id"])
    assert filename == "README.md" and path.read_text() == "# hi"


def test_project_artifact_concurrent_saves_are_all_kept(isolated_home: Path) -> None:
    import threading

    from palimind.projects import artifacts, store

    project = store.create_project("p", workspace_path=isolated_home / "ws")
    threads = [
        threading.Thread(target=artifacts.save_artifact, args=(project["id"], {"content": f"c{i}"}))
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(artifacts.list_artifacts(project["id"])) == 20


def test_export_with_non_latin_title_does_not_500(isolated_home: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from palimind.artifacts import registry
    from palimind.artifacts.api import router

    app = FastAPI()
    app.include_router(router)
    art = registry.save_artifact({"title": "季度报告 ✨", "content": "# x", "type": "markdown"})
    res = TestClient(app).post(f"/api/artifacts/{art['id']}/export", json={"format": "md"})
    assert res.status_code == 200
    assert 'filename="' in res.headers["content-disposition"]


# ── embedding cache ───────────────────────────────────────────────────────


def test_embed_cache_flush_prunes_expired_entries(tmp_path: Path) -> None:
    import json

    from palimind.core import embedder

    (tmp_path / ".palimind").mkdir()
    cache_file = tmp_path / ".palimind" / "embed_cache.json"
    cache_file.write_text(json.dumps({"old:m": {"e": [0.1], "ts": 1.0}}))
    embedder._mem_cache.pop(str(tmp_path), None)
    try:
        assert embedder._mem_get(tmp_path, "old:m") is None  # expired on load
        embedder._mem_put(tmp_path, "new:m", [0.2])
        embedder.flush_embed_cache(tmp_path)
        assert set(json.loads(cache_file.read_text())) == {"new:m"}
    finally:
        embedder._mem_cache.pop(str(tmp_path), None)


# ── file watcher ──────────────────────────────────────────────────────────


def test_watcher_handles_field_under_hidden_directory(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from palimind.core.watcher import FieldEventHandler

    field = tmp_path / ".palimind" / "projects" / "abc" / "workspace"
    field.mkdir(parents=True)
    seen: list[str] = []
    handler = FieldEventHandler(seen.append, field)
    for p in (field / "a.txt", field / ".git" / "x", field / "node_modules" / "y.js"):
        handler.on_any_event(SimpleNamespace(is_directory=False, src_path=str(p)))
    assert seen == [str(field / "a.txt")]


# ── web fetch SSRF via redirect ───────────────────────────────────────────


def test_fallback_fetch_rechecks_redirect_targets(monkeypatch) -> None:
    import httpx

    from palimind.core import web_search

    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        assert kwargs.get("follow_redirects") is False
        req = httpx.Request("GET", url)
        if url.startswith("https://public.example"):
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/x"}, request=req)
        return httpx.Response(200, text="<p>secret</p>", request=req)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(web_search, "_is_safe_url", lambda u: "127.0.0.1" not in u)
    assert web_search._fetch_page_fallback("https://public.example/a") == ""
    assert calls == ["https://public.example/a"]


def test_delete_message_with_negative_index_deletes_nothing(tmp_path: Path) -> None:
    from palimind.memory import session_store

    sid = session_store.add_new_session(tmp_path, "s")["active_session_id"]
    session_store.append_message_to_session(tmp_path, sid, "user", "first")
    session_store.append_message_to_session(tmp_path, sid, "assistant", "second")
    session_store.delete_session_message(tmp_path, sid, -1)
    sess = session_store.load_session_by_id(tmp_path, sid)
    assert [m["content"] for m in sess["messages"]] == ["first", "second"]


def test_session_store_recovers_when_state_dir_is_removed(tmp_path: Path) -> None:
    import shutil

    from palimind.memory import session_store

    session_store.add_new_session(tmp_path, "a")
    shutil.rmtree(tmp_path / ".palimind")  # what DELETE /api/agents/{id}/sessions does
    assert len(session_store.load_sessions(tmp_path)["sessions"]) == 1
