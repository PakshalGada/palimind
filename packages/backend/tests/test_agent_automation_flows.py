"""Waits, flows, routine signals and local automation tests."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from palimind.agents import automation, flows, routine_signals, routines, waits
from palimind.agents.catalog import AgentDefinition
from palimind.agents.registry import get_registry
from palimind.storage import state_store


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    import palimind.agents.catalog as catalog

    monkeypatch.setattr(catalog, "GLOBAL_AGENTS_DIR", tmp_path / "agents")
    state_store._initialised.clear()
    registry = get_registry()
    registry._by_id = {}
    registry._by_name = {}
    agent = registry.create(AgentDefinition.new("flow-alpha", display_name="Alpha"))
    yield agent
    registry._by_id = {}
    registry._by_name = {}
    state_store._initialised.clear()
    routine_signals.clear()
    automation.stop_server()


def test_waits_open_wake_and_limit(env) -> None:
    first = waits.create_wait(env.id, "wait for build")
    second = waits.create_wait(env.id, "wait for deploy", routine_id="routine-1")
    assert waits.open_wait_count(env.id) == 2
    woken = waits.wake(env.id, wait_id=first["id"], payload="done")
    assert [w["id"] for w in woken] == [first["id"]]
    assert waits.get_wait(first["id"])["status"] == "woken"
    assert [w["id"] for w in waits.list_waits(env.id)] == [second["id"]]
    assert waits.close_wait(second["id"], reason="not needed")["status"] == "closed"


def test_flows_fan_in_and_failure_skip(env) -> None:
    other = get_registry().create(AgentDefinition.new("flow-beta", display_name="Beta"))
    flows.connect(env.id, "routine-a", other.id)
    flow_b = flows.connect(env.id, "routine-b", other.id)
    assert len(flow_b["links"]) == 2
    flows.record_result(env.id, "routine-a", "run-1", status="success", output="A done")
    assert flows.ready_handoffs(flow_b["id"], "run-1") == []  # B still pending
    flows.record_result(env.id, "routine-b", "run-1", status="success", output="B done")
    ready = flows.ready_handoffs(flow_b["id"], "run-1")
    assert ready and ready[0]["agent_id"] == other.id
    assert "A done" in ready[0]["text"] and "B done" in ready[0]["text"]
    get_registry().delete(other.id)


def test_flows_all_failed_is_skipped(env) -> None:
    other = get_registry().create(AgentDefinition.new("flow-gamma", display_name="Gamma"))
    flows.connect(env.id, "routine-a", other.id)
    flow = flows.connect(env.id, "routine-b", other.id)
    flows.record_result(env.id, "routine-a", "run-2", status="failed", error="no")
    flows.record_result(env.id, "routine-b", "run-2", status="failed", error="no")
    assert flows.ready_handoffs(flow["id"], "run-2") == []
    assert flows.flow_status(flow["id"])["failed"] == 2
    get_registry().delete(other.id)


def test_routine_quiet_and_failure_signals(env, monkeypatch) -> None:
    routine = routines.create_routine(
        {
            "name": "q",
            "target_type": "agent",
            "target_id": env.id,
            "input": "check",
            "run_source": "schedule",
        }
    )

    async def fake_run(defn, text, session_id="", **kwargs):
        return "nothing new"

    monkeypatch.setattr("palimind.agents.service.run_agent", fake_run)
    monkeypatch.setattr(
        "palimind.agents.runtime.get_last_run",
        lambda agent_id: {"run_id": "run-q", "status": "success"},
    )
    routine_signals.mark_quiet("run-q")
    assert asyncio_run(routines.run_routine(routine["id"])) == "run-q"
    assert routines.get_routine(routine["id"])["last_status"] == "quiet"

    routine_signals.report_failure("run-q", "task failed")
    with pytest.raises(RuntimeError):
        asyncio_run(routines.run_routine(routine["id"]))
    assert routines.get_routine(routine["id"])["last_status"] == "failed"


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


def test_automation_security_and_message_route(env) -> None:
    get_registry().update(env.id, {"allow_automation": True})
    server = automation.start_server()
    try:
        base = server.url
        token = server.token

        def request(
            method: str, path: str, *, body: dict | None = None, origin: str = "", host: str = ""
        ):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + path, data=data, method=method)
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/json")
            if origin:
                req.add_header("Origin", origin)
            if host:
                req.add_header("Host", host)
            return urllib.request.urlopen(req, timeout=5)

        with request("GET", "/v1/agents") as resp:
            payload = json.loads(resp.read())
        assert payload["agents"][0]["id"] == env.id

        try:
            request("GET", "/v1/agents", origin="https://evil.example")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("origin must be refused")

        with request(
            "POST", f"/v1/agents/{env.id}/messages", body={"text": "hello", "clientMessageId": "c1"}
        ) as resp:
            sent = json.loads(resp.read())
        assert sent["messageId"]
        with request("GET", f"/v1/agents/{env.id}/deliveries/{sent['messageId']}") as resp:
            delivery = json.loads(resp.read())
        assert delivery["status"] in ("queued", "starting", "running", "completed")
        with request("POST", f"/v1/agents/{env.id}/context/clear", body={}) as resp:
            assert json.loads(resp.read())["ok"] is True
    finally:
        automation.stop_server()
