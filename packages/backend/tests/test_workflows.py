"""Tests for workflow DAGs and cron/file/webhook triggers."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

import pytest

from palimind.jobs import JobRunner, list_jobs
from palimind.jobs.handlers import default_handlers
from palimind.workflows import runtime, store, triggers


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    yield


@pytest.fixture()
def tools():
    from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY

    def echo(text: str) -> str:
        return str(text)

    def upper(text: str) -> str:
        return str(text).upper()

    for name, fn in (("_wf_echo", echo), ("_wf_upper", upper)):
        TOOL_REGISTRY[name] = {
            "fn": fn,
            "description": name,
            "parameters": {"text": "Text to process"},
            "meta": {"tier": 1, "requires_approval": False},
            "timeout_s": 10,
        }
    try:
        yield
    finally:
        for name in ("_wf_echo", "_wf_upper"):
            TOOL_REGISTRY.pop(name, None)


def _workflow(**changes):
    data = {
        "name": "two-step",
        "enabled": True,
        "trigger": {"type": "manual"},
        "nodes": [
            {
                "id": "n1",
                "type": "tool",
                "tool": "_wf_echo",
                "args": {"text": "{{input}}"},
            },
            {
                "id": "n2",
                "type": "tool",
                "tool": "_wf_upper",
                "args": {"text": "{{nodes.n1.output}}"},
            },
        ],
        "edges": [["n1", "n2"]],
    }
    data.update(changes)
    return data


def test_workflow_crud_and_cycle_validation() -> None:
    wf = store.create_workflow(_workflow())
    assert wf["id"]
    assert store.get_workflow(wf["id"])["name"] == "two-step"
    assert any(item["id"] == wf["id"] for item in store.list_workflows())

    updated = store.update_workflow(wf["id"], {"name": "renamed"})
    assert updated["name"] == "renamed"

    with pytest.raises(ValueError, match="cycle"):
        store.create_workflow(
            {
                **_workflow(),
                "name": "cycle",
                "edges": [["n1", "n2"], ["n2", "n1"]],
            }
        )

    assert store.delete_workflow(wf["id"]) is True
    assert store.get_workflow(wf["id"]) is None


def test_execute_two_node_dag(tools, tmp_path: Path) -> None:
    wf = store.create_workflow(_workflow())
    run = asyncio.run(
        runtime.execute_workflow(wf["id"], input_text="hello", workspace_root=tmp_path)
    )
    assert run["status"] == "completed"
    assert run["nodes"]["n1"]["output"] == "hello"
    assert run["nodes"]["n2"]["output"] == "HELLO"
    assert runtime.get_run(run["run_id"])["status"] == "completed"


def test_cron_trigger_enqueues_and_runs_workflow(tools, tmp_path: Path, monkeypatch) -> None:
    wf = store.create_workflow(_workflow(trigger={"type": "cron", "cron": "* * * * *"}))
    monkeypatch.setattr("palimind.jobs.cron.cron_matches", lambda expr, dt=None: True)
    assert triggers.enqueue_due_cron(datetime(2026, 1, 1, 9, 0)) == 1
    jobs = list_jobs(kind="workflow")
    assert len(jobs) == 1
    assert jobs[0]["target"] == wf["id"]

    async def scenario() -> dict:
        runner = JobRunner(default_handlers(), concurrency=1, poll_interval=0.05, lease_seconds=30)
        await runner.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline:
                runs = runtime.list_runs(wf["id"], limit=5)
                if runs and runs[0]["status"] in ("completed", "failed"):
                    return runs[0]
                await asyncio.sleep(0.05)
            return {}
        finally:
            await runner.stop()

    run = asyncio.run(scenario())
    assert run["status"] == "completed"
    assert run["nodes"]["n1"]["output"].startswith("[Scheduled workflow trigger")
    assert run["nodes"]["n2"]["output"] == run["nodes"]["n1"]["output"].upper()


def test_file_trigger_matches_glob(tools) -> None:
    wf = store.create_workflow(_workflow(trigger={"type": "file", "pattern": "*.txt"}))
    assert triggers.enqueue_file_triggers(Path("/tmp/field"), "notes.txt") == 1
    assert triggers.enqueue_file_triggers(Path("/tmp/field"), "image.png") == 0
    jobs = list_jobs(kind="workflow")
    assert len(jobs) == 1
    assert jobs[0]["target"] == wf["id"]


def test_workflow_api_crud_and_webhook(tools) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    created = client.post("/api/workflows", json=_workflow(trigger={"type": "webhook"}))
    assert created.status_code == 200
    wf = created.json()["workflow"]
    assert wf["trigger"]["token"]

    listed = client.get("/api/workflows").json()["workflows"]
    assert any(item["id"] == wf["id"] for item in listed)

    detail = client.get(f"/api/workflows/{wf['id']}").json()
    assert detail["workflow"]["id"] == wf["id"]

    manual = client.post(f"/api/workflows/{wf['id']}/run", json={"input": "hi"})
    assert manual.status_code == 200
    assert manual.json()["status"] == "queued"

    hook = client.post(f"/api/workflows/hooks/{wf['trigger']['token']}", json={"input": "hook"})
    assert hook.status_code == 200
    assert hook.json()["status"] == "queued"

    patched = client.patch(f"/api/workflows/{wf['id']}", json={"enabled": False})
    assert patched.json()["workflow"]["enabled"] is False

    runs = client.get(f"/api/workflows/{wf['id']}/runs").json()["runs"]
    assert isinstance(runs, list)

    assert client.delete(f"/api/workflows/{wf['id']}").json()["status"] == "success"
