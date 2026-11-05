"""Tests for local observability metrics and dashboard."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind import metrics


@pytest.fixture(autouse=True)
def _isolated_metrics(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    metrics.reset()
    yield
    metrics.reset()


def test_counters_increment() -> None:
    metrics.record_request("GET", "/api/test", 200, 12.5)
    metrics.record_request("GET", "/api/test", 500, 7.5)
    metrics.record_tokens("model-a", 10, 4)
    metrics.record_tool("web_search", True, 30.0)
    metrics.record_tool("web_search", False, 10.0)
    metrics.record_agent_run("success")
    metrics.record_agent_run("error")
    metrics.record_index_run(indexed_files=3, deleted_files=1, chunks_indexed=12, duration_s=2.0)

    snap = metrics.snapshot()
    assert snap["local_only"] is True
    assert snap["requests"]["total"] == 2
    assert snap["requests"]["by_status"] == {"2xx": 1, "5xx": 1}
    assert snap["requests"]["by_route"]["/api/test"]["count"] == 2
    assert snap["tokens"]["total"] == 14
    assert snap["tokens"]["by_model"]["model-a"]["completion"] == 4
    assert snap["tools"]["web_search"]["success"] == 1
    assert snap["tools"]["web_search"]["failure"] == 1
    assert snap["agent_runs"] == {"success": 1, "error": 1}
    assert snap["index"]["indexed_files"] == 3
    assert snap["index"]["deleted_files"] == 1
    assert snap["index"]["chunks_indexed"] == 12
    assert snap["index"]["files_per_minute"] == 90.0


def test_request_middleware_counts_requests() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    assert client.get("/health").status_code == 200
    snap = client.get("/api/metrics").json()
    assert snap["requests"]["total"] >= 1
    assert snap["requests"]["by_route"]["/health"]["count"] >= 1


def test_tool_metrics_increment_through_call_tool() -> None:
    from palimind.llm.mixture_of_expert.tools import call_tool

    out = call_tool("tool_search", query="read a file")
    assert out
    snap = metrics.snapshot()
    assert snap["tools"]["tool_search"]["total"] == 1
    assert snap["tools"]["tool_search"]["success"] == 1


def test_agent_run_status_is_recorded() -> None:
    from palimind.agents.runtime import record_run

    record_run("agent-1", "run-1", "input", "output", "success", 0.5)
    snap = metrics.snapshot()
    assert snap["agent_runs"]["success"] == 1


def test_dashboard_is_local_and_renders() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    page = client.get("/metrics")
    assert page.status_code == 200
    assert "PALIMIND / METRICS" in page.text
    data = client.get("/metrics/data")
    assert data.status_code == 200
    assert data.json()["local_only"] is True


def test_metrics_module_has_no_outbound_network_code() -> None:
    import inspect

    source = inspect.getsource(metrics)
    for needle in (
        "import httpx",
        "import requests",
        "from urllib",
        "import urllib",
        "import socket",
    ):
        assert needle not in source
