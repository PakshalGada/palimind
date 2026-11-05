"""Tests that scheduler/goals/queue/routines enqueue durable jobs."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from palimind.agents import goals, queue, routines, scheduler
from palimind.jobs import list_jobs


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    yield


def test_queue_enqueue_creates_durable_job() -> None:
    item = queue.enqueue("agent", "agent-1", "do work", priority=3)
    assert item["job_id"]
    jobs = list_jobs(kind="queued_run")
    assert len(jobs) == 1
    assert jobs[0]["id"] == item["job_id"]
    assert jobs[0]["payload"]["queue_item_id"] == item["id"]
    assert jobs[0]["payload"]["input"] == "do work"
    queue.clear_target("agent", "agent-1")


def test_scheduler_scheduled_agent_enqueues_job(monkeypatch) -> None:
    defn = SimpleNamespace(
        id="agent-1",
        name="a",
        run_mode="scheduled",
        schedule="* * * * *",
        max_concurrent_runs=1,
        enabled=True,
    )

    class _Registry:
        def enabled_agents(self):
            return [defn]

    monkeypatch.setattr("palimind.agents.registry.get_registry", lambda: _Registry())
    monkeypatch.setattr(scheduler, "cron_matches", lambda expr, dt=None: True)
    monkeypatch.setattr(routines, "due_routines", lambda now=None: [])
    asyncio.run(scheduler._tick_scheduled())
    jobs = list_jobs(kind="agent_run")
    assert jobs
    assert jobs[0]["target"] == "agent-1"
    assert jobs[0]["payload"]["source"] == "scheduled"


def test_scheduler_routine_enqueues_job(monkeypatch) -> None:
    routine = {"id": "routine-1", "name": "R", "enabled": True}
    monkeypatch.setattr(routines, "due_routines", lambda now=None: [routine])
    asyncio.run(scheduler._tick_routines(__import__("datetime").datetime.now()))
    jobs = list_jobs(kind="routine_run")
    assert jobs
    assert jobs[0]["target"] == "routine-1"


def test_goals_due_tasks_enqueue_jobs(monkeypatch) -> None:
    task = {"id": "task-1", "next_run": time.time()}
    monkeypatch.setattr(goals, "due_tasks", lambda now=None: [task])
    assert goals._enqueue_due_tasks() == 1
    jobs = list_jobs(kind="background_task")
    assert jobs
    assert jobs[0]["target"] == "task-1"
    # A second tick must dedupe on the task's next_run.
    goals._enqueue_due_tasks()
    assert len(list_jobs(kind="background_task")) == 1
