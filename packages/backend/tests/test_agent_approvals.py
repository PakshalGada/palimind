"""Tests for the global pending-approvals registry and inbox endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.agents import approvals


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(approvals, "_PATH", tmp_path / "pending_approvals.json")
    approvals.clear()
    yield
    approvals.clear()


def test_add_list_remove(monkeypatch) -> None:
    monkeypatch.setattr(approvals, "_is_running", lambda _id: True)
    approvals.add("a1", "r1", "write_file", {"path": "x", "content": "y"}, 0.2, "why")
    pending = approvals.list_pending()
    assert len(pending) == 1
    assert pending[0]["tool"] == "write_file"
    assert pending[0]["run_id"] == "r1"
    approvals.remove("a1")
    assert approvals.list_pending() == []


def test_stale_entries_are_pruned(monkeypatch) -> None:
    monkeypatch.setattr(approvals, "_is_running", lambda _id: True)
    approvals.add("a1", "r1", "run_shell", {"command": "ls"}, 0.0, "")
    assert len(approvals.list_pending()) == 1
    # Agent is no longer running → entry is dropped on read.
    monkeypatch.setattr(approvals, "_is_running", lambda _id: False)
    assert approvals.list_pending() == []


def test_approvals_endpoint() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    resp = client.get("/api/agents/approvals")
    assert resp.status_code == 200
    assert "approvals" in resp.json()


def test_recent_runs_endpoint() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    resp = client.get("/api/agents/runs/recent?limit=5")
    assert resp.status_code == 200
    assert isinstance(resp.json().get("runs"), list)


def test_recall_preview_endpoint() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    resp = client.post("/api/agents/nonexistent/recall-preview", json={"query": "hello"})
    assert resp.status_code == 200
    assert resp.json().get("entries") == []
