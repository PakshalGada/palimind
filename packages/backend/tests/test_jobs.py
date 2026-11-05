"""Tests for the durable SQLite-backed job service."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from palimind.jobs import (
    JobRunner,
    cancel_job,
    claim_next,
    complete,
    enqueue,
    get_job,
    list_events,
    list_jobs,
    recover_orphans,
    retry_job,
    stats,
)
from palimind.storage import state_store


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    yield


def _force_due(job_id: str, run_at: float | None = None) -> None:
    conn = state_store.state_connection()
    try:
        conn.execute(
            "UPDATE jobs SET run_at=? WHERE id=?",
            (time.time() - 1 if run_at is None else run_at, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_enqueue_get_list_and_events() -> None:
    job = enqueue("agent_run", "agent-1", {"input": "hi"}, priority=2)
    assert job["status"] == "queued"
    assert job["kind"] == "agent_run"
    assert job["payload"]["input"] == "hi"
    assert get_job(job["id"])["id"] == job["id"]
    assert any(item["id"] == job["id"] for item in list_jobs(kind="agent_run"))
    events = list_events(job["id"])
    assert events and events[0]["type"] == "enqueued"


def test_idempotency_key_prevents_duplicates() -> None:
    first = enqueue("agent_run", "a", {"input": "1"}, idempotency_key="same-key")
    second = enqueue("agent_run", "a", {"input": "2"}, idempotency_key="same-key")
    assert first["id"] == second["id"]
    assert len(list_jobs(kind="agent_run")) == 1


def test_priority_and_delay_ordering() -> None:
    low = enqueue("agent_run", "a", {"input": "low"}, priority=1)
    high = enqueue("agent_run", "a", {"input": "high"}, priority=10)
    later = enqueue("agent_run", "a", {"input": "later"}, delay=3600)

    claimed = claim_next("w1", lease_seconds=30)
    assert claimed is not None and claimed["id"] == high["id"]
    assert get_job(low["id"])["status"] == "queued"
    assert get_job(later["id"])["status"] == "queued"


def test_lease_recovery_requeues_running_job() -> None:
    job = enqueue("agent_run", "a", {"input": "x"})
    claimed = claim_next("w1", lease_seconds=5)
    assert claimed is not None and claimed["status"] == "running"
    conn = state_store.state_connection()
    try:
        conn.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() - 1, job["id"]))
        conn.commit()
    finally:
        conn.close()
    assert recover_orphans() == 1
    recovered = get_job(job["id"])
    assert recovered is not None and recovered["status"] == "queued"


def test_retry_backoff_and_dead_letter() -> None:
    job = enqueue("agent_run", "a", {"input": "x"}, max_attempts=2)
    assert claim_next("w1") is not None
    first = complete(job["id"], status="error", error="boom")
    assert first is not None and first["status"] == "queued"
    assert first["attempts"] == 1
    assert first["last_error"] == "boom"

    _force_due(job["id"])
    assert claim_next("w1") is not None
    second = complete(job["id"], status="error", error="boom again")
    assert second is not None and second["status"] == "dead_letter"
    assert second["attempts"] == 2

    retried = retry_job(job["id"])
    assert retried is not None and retried["status"] == "queued"
    assert retried["attempts"] == 0


def test_cancel_queued_and_running() -> None:
    queued = enqueue("agent_run", "a", {"input": "queued"})
    assert cancel_job(queued["id"])["status"] == "cancelled"

    running = enqueue("agent_run", "a", {"input": "running"})
    assert claim_next("w1") is not None
    cancelled = cancel_job(running["id"])
    assert cancelled is not None
    assert cancelled["cancel_requested"] is True
    finished = complete(running["id"], status="success", result="done")
    assert finished is not None and finished["status"] == "cancelled"


def test_interval_job_reschedules_after_success() -> None:
    job = enqueue("agent_run", "a", {"input": "loop"}, interval_seconds=60)
    assert claim_next("w1") is not None
    completed = complete(job["id"], status="success", result="ok")
    assert completed is not None
    assert completed["status"] == "queued"
    assert completed["attempts"] == 0
    assert completed["run_at"] > time.time()


def test_stats() -> None:
    enqueue("agent_run", "a", {"input": "1"})
    enqueue("agent_run", "a", {"input": "2"})
    claim_next("w1")
    data = stats()
    assert data["queued"] == 1
    assert data["running"] == 1


def test_job_runner_executes_jobs() -> None:
    seen: list[str] = []

    async def handler(job):
        seen.append(job["id"])
        return {"status": "success", "output": "done"}

    async def scenario() -> None:
        job = enqueue("probe", "x", {"n": 1})
        runner = JobRunner({"probe": handler}, concurrency=1, poll_interval=0.05, lease_seconds=5)
        await runner.start()
        try:
            deadline = time.time() + 3
            while time.time() < deadline:
                if get_job(job["id"])["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
        finally:
            await runner.stop()
        assert get_job(job["id"])["status"] == "completed"
        assert seen == [job["id"]]

    asyncio.run(scenario())


def test_jobs_survive_a_restart() -> None:
    job = enqueue("agent_run", "a", {"input": "survive"})
    claimed = claim_next("old-worker", lease_seconds=5)
    assert claimed is not None

    # Simulate a process death: the lease expires and a new process starts.
    conn = state_store.state_connection()
    try:
        conn.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() - 1, job["id"]))
        conn.commit()
    finally:
        conn.close()

    assert recover_orphans() == 1
    restarted = get_job(job["id"])
    assert restarted is not None
    assert restarted["status"] == "queued"
    assert restarted["payload"]["input"] == "survive"


def test_job_endpoints() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    job = enqueue("agent_run", "a", {"input": "api"})
    client = TestClient(server.app)

    listed = client.get("/api/jobs?kind=agent_run").json()["jobs"]
    assert any(item["id"] == job["id"] for item in listed)

    stats_body = client.get("/api/jobs/stats").json()
    assert stats_body["queued"] >= 1

    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert detail["job"]["id"] == job["id"]
    assert detail["events"]

    cancelled = client.post(f"/api/jobs/{job['id']}/cancel").json()
    assert cancelled["job"]["status"] == "cancelled"

    retried = client.post(f"/api/jobs/{job['id']}/retry").json()
    assert retried["job"]["status"] == "queued"

    deleted = client.delete(f"/api/jobs/{job['id']}").json()
    assert deleted["status"] == "success"
