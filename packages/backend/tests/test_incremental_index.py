"""Tests for incremental indexing runs (delta, cancel/resume, progress)."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.rag import incremental
from palimind.rag.indexing import initialize_index


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    yield


@pytest.fixture()
def field(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "field"
    root.mkdir()
    (root / "a.txt").write_text("alpha beta gamma\n" * 20, encoding="utf-8")
    (root / "b.txt").write_text("delta epsilon zeta\n" * 20, encoding="utf-8")
    initialize_index(root)

    # Keep the test local: no Ollama embedding call.
    def _fake_embeddings(texts, *_args, **_kwargs):
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr("palimind.rag.indexing.generate_embeddings_batch", _fake_embeddings)
    return root


def _db_files(root: Path) -> set[str]:
    from palimind.storage.db import get_connection

    conn = get_connection(root)
    try:
        return {row[0] for row in conn.execute("SELECT path FROM files").fetchall()}
    finally:
        conn.close()


def test_plan_process_and_unchanged_delta(field: Path) -> None:
    run = incremental.plan_run(field)
    assert run["status"] == "queued"
    assert run["queued"] == 2
    files = incremental.list_run_files(field, run["run_id"])
    assert {f["path"] for f in files} == {"a.txt", "b.txt"}
    assert all(f["status"] == "queued" for f in files)

    completed = incremental.process_run(run["run_id"])
    assert completed["status"] == "completed"
    assert completed["indexed"] == 2
    assert _db_files(field) == {"a.txt", "b.txt"}

    # A second plan sees both files as unchanged and does no work.
    again = incremental.plan_run(field)
    assert again["status"] == "completed"
    assert again["total"] == 0
    assert again["unchanged"] == 2
    assert not any(
        f["status"] == "queued" for f in incremental.list_run_files(field, again["run_id"])
    )


def test_chunker_version_change_forces_full_rebuild(field: Path) -> None:
    run = incremental.plan_run(field)
    incremental.process_run(run["run_id"])

    from palimind.config import load_config, save_config

    config = load_config(field)
    config["chunker_version"] = 99
    save_config(field, config)

    rebuilt = incremental.plan_run(field)
    assert rebuilt["status"] == "queued"
    assert rebuilt["queued"] == 2
    assert rebuilt["unchanged"] == 0
    assert "Full rebuild" in rebuilt["message"]
    files = incremental.list_run_files(field, rebuilt["run_id"])
    assert {f["path"] for f in files} == {"a.txt", "b.txt"}
    assert all(f["status"] == "queued" for f in files)

    completed = incremental.process_run(rebuilt["run_id"])
    assert completed["status"] == "completed"
    assert completed["indexed"] == 2
    assert _db_files(field) == {"a.txt", "b.txt"}


def test_deleted_file_is_removed(field: Path) -> None:
    run = incremental.plan_run(field)
    incremental.process_run(run["run_id"])
    assert "b.txt" in _db_files(field)

    (field / "b.txt").unlink()
    deleted_run = incremental.plan_run(field)
    assert deleted_run["deleted"] == 1
    deleted = incremental.process_run(deleted_run["run_id"])
    assert deleted["status"] == "completed"
    assert deleted["deleted"] == 1
    assert _db_files(field) == {"a.txt"}

    files = incremental.list_run_files(field, deleted_run["run_id"])
    assert [f for f in files if f["path"] == "b.txt"][0]["status"] == "deleted"


def test_cancel_and_resume(field: Path) -> None:
    run = incremental.plan_run(field)
    cancelled = incremental.cancel_run(run["run_id"])
    assert cancelled is not None and cancelled["status"] == "cancelled"
    # A cancelled run must not index anything when the worker starts.
    processed = incremental.process_run(run["run_id"])
    assert processed["status"] == "cancelled"
    assert _db_files(field) == set()

    resumed = incremental.resume_run(run["run_id"])
    assert resumed is not None and resumed["status"] == "queued"
    completed = incremental.process_run(run["run_id"])
    assert completed["status"] == "completed"
    assert completed["indexed"] == 2
    assert _db_files(field) == {"a.txt", "b.txt"}


def test_progress_events_are_recorded(field: Path) -> None:
    events: list[dict] = []
    run = incremental.plan_run(field)
    incremental.process_run(run["run_id"], on_event=events.append)
    stored = incremental.list_events(field, run["run_id"])
    types = {e["type"] for e in stored}
    assert "planned" in types
    assert "index_progress" in types
    assert "completed" in types
    assert events and any(e["type"] == "index_complete" for e in events)


def test_index_run_endpoints(field: Path) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    created = client.post("/api/index/runs", json={"root": str(field)})
    assert created.status_code == 200
    run = created.json()["run"]
    assert run["queued"] == 2

    listed = client.get("/api/index/runs").json()["runs"]
    assert any(item["run_id"] == run["run_id"] for item in listed)

    detail = client.get(f"/api/index/runs/{run['run_id']}").json()
    assert detail["run"]["run_id"] == run["run_id"]
    assert len(detail["files"]) == 2

    events = client.get(f"/api/index/runs/{run['run_id']}/events").json()["events"]
    assert events

    cancelled = client.post(f"/api/index/runs/{run['run_id']}/cancel").json()
    assert cancelled["run"]["status"] == "cancelled"

    resumed = client.post(f"/api/index/runs/{run['run_id']}/resume").json()
    assert resumed["run"]["status"] == "queued"


def test_index_job_runs_through_durable_runner(field: Path) -> None:
    import asyncio
    import time

    from palimind.jobs import JobRunner
    from palimind.jobs.handlers import default_handlers

    run = incremental.enqueue_run(field)
    assert run["job_id"]

    async def scenario() -> dict:
        runner = JobRunner(default_handlers(), concurrency=1, poll_interval=0.05, lease_seconds=30)
        await runner.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline:
                current = incremental.get_run(run["run_id"])
                if current and current.get("status") in ("completed", "failed", "cancelled"):
                    return current
                await asyncio.sleep(0.05)
            return incremental.get_run(run["run_id"]) or {}
        finally:
            await runner.stop()

    finished = asyncio.run(scenario())
    assert finished["status"] == "completed"
    assert finished["indexed"] == 2
    assert _db_files(field) == {"a.txt", "b.txt"}
