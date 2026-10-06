"""Integration tests for the Phase 4 runtime pipeline (mocked LLM/tools)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from palimind.agents import runtime as rt
from palimind.agents.catalog import AgentDefinition


class _FakeRunning:
    def __init__(self) -> None:
        self.agent_id = "a"
        self.run_id = "r"
        self.loop = None
        self.approval_event = asyncio.Event()
        self.approval_result = None
        self.pending = None


@pytest.fixture(autouse=True)
def _stub_runtime(monkeypatch):
    async def fake_register(agent_id, run_id):
        return _FakeRunning()

    async def fake_unregister(agent_id):
        return None

    monkeypatch.setattr(rt, "register_running", fake_register)
    monkeypatch.setattr(rt, "unregister_running", fake_unregister)
    monkeypatch.setattr(rt, "set_tool_context", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_field_models", lambda root=None: ("test-model", "http://x", "light"))
    monkeypatch.setattr(rt, "_resolve_available_model", lambda *a, **k: ("test-model", ""))
    monkeypatch.setattr("palimind.opencode.router.resolve_model_url", lambda model, url: url)
    monkeypatch.setattr(rt, "recall_memory", lambda *a, **k: [])
    monkeypatch.setattr(rt, "append_chat", lambda *a, **k: None)
    monkeypatch.setattr(rt, "append_memory", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_workspace_context_block", lambda root: "")
    yield


def _record_runs(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_record(agent_id, run_id, input, output, status, duration, **kwargs):
        calls.append({"output": output, "status": status, **kwargs})

    monkeypatch.setattr(rt, "record_run", fake_record)
    return calls


def test_effort_is_resolved_and_recorded(monkeypatch) -> None:
    calls = _record_runs(monkeypatch)
    seen_kwargs: list[dict] = []

    def fake_run_agent(agent_id, sub_task, model, url, max_iters, on_step, **kwargs):
        seen_kwargs.append({"max_iters": max_iters, **kwargs})
        return "the answer"

    monkeypatch.setattr(rt, "run_agent", fake_run_agent)
    defn = AgentDefinition.new(
        "phase4", reasoning_effort="minimal", planning_mode="off", self_critique=False
    )
    events: list[tuple] = []

    async def emit(etype, payload):
        events.append((etype, payload))

    out = asyncio.run(rt.run_with_definition(defn, "hello", emit=emit))
    assert out == "the answer"
    # minimal effort caps iterations at the profile value.
    assert seen_kwargs[0]["max_iters"] <= 3
    assert any(e[0] == "agent:effort" for e in events)
    assert calls and calls[0]["effort"]["level"] == "minimal"


def test_planning_mode_injects_plan(monkeypatch, tmp_path: Path) -> None:
    _record_runs(monkeypatch)
    seen: list[dict] = []

    def fake_run_agent(agent_id, sub_task, model, url, max_iters, on_step, **kwargs):
        seen.append(kwargs)
        return "done"

    monkeypatch.setattr(rt, "run_agent", fake_run_agent)

    from palimind.agents import planner as pl

    plan = pl.new_plan("task", [{"title": "Step one"}, {"title": "Step two"}])
    monkeypatch.setattr(pl, "generate_plan", lambda *a, **k: plan)
    monkeypatch.setattr(pl, "save_plan", lambda p: p)

    defn = AgentDefinition.new("planner", reasoning_effort="off", planning_mode="auto")
    events: list[tuple] = []

    async def emit(etype, payload):
        events.append((etype, payload))

    out = asyncio.run(rt.run_with_definition(defn, "do work", emit=emit))
    assert out == "done"
    assert "[PLAN]" in seen[0]["extra_system_prompt"]
    assert "Step one" in seen[0]["extra_system_prompt"]
    assert any(e[0] == "agent:plan" for e in events)


def test_planning_review_rejection_aborts(monkeypatch) -> None:
    calls = _record_runs(monkeypatch)
    ran: list[int] = []

    def fake_run_agent(*a, **k):
        ran.append(1)
        return "should not run"

    monkeypatch.setattr(rt, "run_agent", fake_run_agent)

    from palimind.agents import planner as pl

    plan = pl.new_plan("task", [{"title": "Step"}])
    monkeypatch.setattr(pl, "generate_plan", lambda *a, **k: plan)
    monkeypatch.setattr(pl, "save_plan", lambda p: p)

    async def rejected(plan_id, timeout=0):
        return {"approved": False}

    monkeypatch.setattr(pl, "wait_for_plan_review", rejected)

    defn = AgentDefinition.new("planner2", reasoning_effort="off", planning_mode="review")

    async def emit(etype, payload):
        return None

    out = asyncio.run(rt.run_with_definition(defn, "do work", emit=emit))
    assert "rejected" in out.lower()
    assert ran == []
    assert calls[0]["status"] == "rejected"


def test_self_critique_verifies_and_records(monkeypatch) -> None:
    calls = _record_runs(monkeypatch)
    monkeypatch.setattr(rt, "run_agent", lambda *a, **k: "draft answer")

    from palimind.agents import self_critique as sc

    report = {"passed": True, "confidence": 0.95, "issues": [], "suggestions": []}
    monkeypatch.setattr(sc, "verify_output", lambda *a, **k: report)

    defn = AgentDefinition.new(
        "verifier", reasoning_effort="off", planning_mode="off", self_critique=True
    )
    events: list[tuple] = []

    async def emit(etype, payload):
        events.append((etype, payload))

    asyncio.run(rt.run_with_definition(defn, "task", emit=emit))
    assert any(e[0] == "agent:verification" for e in events)
    assert calls[0]["verification"]["confidence"] == 0.95


def test_self_critique_retries_on_low_confidence(monkeypatch) -> None:
    _record_runs(monkeypatch)
    attempts: list[str] = []

    def fake_run_agent(agent_id, sub_task, *a, **k):
        attempts.append(sub_task["task"])
        return f"answer {len(attempts)}"

    monkeypatch.setattr(rt, "run_agent", fake_run_agent)

    from palimind.agents import self_critique as sc

    reports = iter(
        [
            {"passed": False, "confidence": 0.2, "issues": ["bad"], "suggestions": []},
            {"passed": True, "confidence": 0.9, "issues": [], "suggestions": []},
        ]
    )
    monkeypatch.setattr(sc, "verify_output", lambda *a, **k: next(reports))
    monkeypatch.setattr(rt, "SELF_CRITIQUE_MAX_RETRIES", 1)

    defn = AgentDefinition.new(
        "retry", reasoning_effort="off", planning_mode="off", self_critique=True
    )
    out = asyncio.run(rt.run_with_definition(defn, "original task"))
    assert out == "answer 2"
    assert len(attempts) == 2
