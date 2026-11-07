"""Signed routine webhook tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from palimind.agents import routines, webhooks
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
    agent = registry.create(AgentDefinition.new("hook-alpha", display_name="Alpha"))
    routine = routines.create_routine(
        {
            "name": "hook routine",
            "target_type": "agent",
            "target_id": agent.id,
            "input": "handle event",
            "run_mode": "manual",
        }
    )
    yield agent, routine
    registry._by_id = {}
    registry._by_name = {}
    state_store._initialised.clear()


def test_signature_and_receipts(env) -> None:
    _, routine = env
    route = webhooks.create_route(routine["id"], event_type="build.failed")
    body = json.dumps({"type": "build.failed", "data": {"status": "failed"}}).encode()
    timestamp = str(time.time())
    delivery = "delivery-1"
    sig = webhooks.signature(route["secret"], timestamp, delivery, body)
    assert webhooks.verify(
        route["secret"],
        timestamp=timestamp,
        delivery_id=delivery,
        body=body,
        provided=sig,
    )
    assert not webhooks.verify(
        route["secret"],
        timestamp=timestamp,
        delivery_id=delivery,
        body=body,
        provided="sha256=bad",
    )
    assert not webhooks.verify(
        route["secret"],
        timestamp=str(time.time() - 1000),
        delivery_id=delivery,
        body=body,
        provided=sig,
    )
    stored = webhooks.get_route(route["route_id"])
    matched, reason = webhooks.matches(stored, "build.failed", {"status": "failed"})
    assert matched and reason == ""
    matched, reason = webhooks.matches(stored, "build.succeeded", {"status": "ok"})
    assert not matched and reason == "event-type"
    assert webhooks.record_receipt(route["route_id"], delivery, routine["id"], "accepted") is True
    assert webhooks.record_receipt(route["route_id"], delivery, routine["id"], "accepted") is False


def test_filter_pointer_and_rotation(env) -> None:
    _, routine = env
    route = webhooks.create_route(
        routine["id"],
        filters=[{"pointer": "/data/status", "value": "failed"}],
    )
    stored = webhooks.get_route(route["route_id"])
    assert webhooks.matches(stored, "anything", {"data": {"status": "failed"}})[0] is True
    assert webhooks.matches(stored, "anything", {"data": {"status": "ok"}})[0] is False
    new_secret = webhooks.rotate_secret(route["route_id"])
    assert new_secret != route["secret"]
    assert webhooks.revoke_route(route["route_id"]) is True


def test_webhook_http_route(env) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    _, routine = env
    route = webhooks.create_route(routine["id"], event_type="build.failed")
    body = json.dumps({"type": "build.failed", "data": {"status": "failed"}}).encode()
    timestamp = str(time.time())
    delivery = "http-1"
    headers = {
        "Content-Type": "application/json",
        "X-PaliMind-Timestamp": timestamp,
        "X-PaliMind-Delivery": delivery,
        "X-PaliMind-Signature": webhooks.signature(route["secret"], timestamp, delivery, body),
    }
    client = TestClient(server.app)
    first = client.post(f"/api/hooks/{route['route_id']}", content=body, headers=headers)
    assert first.status_code == 202
    second = client.post(f"/api/hooks/{route['route_id']}", content=body, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    bad = dict(headers)
    bad["X-PaliMind-Signature"] = "sha256=bad"
    assert client.post(f"/api/hooks/{route['route_id']}", content=body, headers=bad).status_code == 401
