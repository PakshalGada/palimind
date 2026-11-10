"""Integration tests for the Phase 4 runtime pipeline (mocked LLM/tools)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from palimind.agents import runtime as rt
from palimind.agents.catalog import AgentDefinition


class _FakeRunning(rt.RunningAgent):
    def __init__(self) -> None:
        super().__init__("a", "r", None)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _stub_runtime(monkeypatch):
    from palimind.llm.mixture_of_expert import tools as moe_tools

    moe_tools.clear_todo()

    async def fake_register(agent_id, run_id, max_concurrent=1):
        return _FakeRunning()

    async def fake_unregister(agent_id, run_id=None):
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
    monkeypatch.setattr("palimind.opencode.router.opencode_model_ids", lambda: set())
    from palimind.agents import model_routing as routing

    monkeypatch.setattr(
        routing,
        "get_capabilities",
        lambda model_id, _base_url="": routing.infer_from_name(model_id),
    )
    from palimind.agents import suggestions as sug

    monkeypatch.setattr(sug, "generate_suggestions", lambda *a, **k: [])
    yield
    moe_tools.clear_todo()


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


def test_followups_are_emitted_and_recorded(monkeypatch) -> None:
    calls = _record_runs(monkeypatch)
    monkeypatch.setattr(rt, "run_agent", lambda *a, **k: "the answer")

    from palimind.agents import suggestions as sug

    def fake_suggestions(*_a, usage_cb=None, **_k):
        if usage_cb is not None:
            usage_cb({"prompt_tokens": 7, "completion_tokens": 3})
        return ["Check the source", "Write a brief", "What changed?"]

    monkeypatch.setattr(sug, "generate_suggestions", fake_suggestions)
    events: list[tuple] = []

    async def emit(etype, payload):
        events.append((etype, payload))

    defn = AgentDefinition.new(
        "followups", reasoning_effort="off", planning_mode="off", self_critique=False
    )
    out = asyncio.run(rt.run_with_definition(defn, "compare the reports", emit=emit))
    assert out == "the answer"
    suggestion_events = [p for t, p in events if t == "agent:suggestions"]
    assert suggestion_events[0]["suggestions"][0] == "Check the source"
    completed = next(p for t, p in events if t == "agent:completed")
    assert completed["suggestions"] == suggestion_events[0]["suggestions"]
    assert calls[0]["suggestions"] == suggestion_events[0]["suggestions"]
    # The follow-up call's tokens are added to the run total, not replaced.
    assert calls[0]["usage"] == {"prompt_tokens": 7, "completion_tokens": 3}
    assert calls[0]["usage_stages"]["followups"] == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
    }
    assert completed["usage"]["prompt_tokens"] == 7


def test_smaller_agent_model_prepares_escalation_to_field_model(monkeypatch) -> None:
    _record_runs(monkeypatch)
    seen: list[dict] = []

    monkeypatch.setattr(
        rt, "_resolve_available_model", lambda requested, default, url: ("small-model", "")
    )
    monkeypatch.setattr(
        "palimind.opencode.router.available_model_ids",
        lambda _url: {"small-model", "test-model"},
    )

    def fake_run_agent(agent_id, sub_task, model, url, max_iters, on_step, **kwargs):
        seen.append({"model": model, "url": url, **kwargs})
        return "done"

    monkeypatch.setattr(rt, "run_agent", fake_run_agent)

    defn = AgentDefinition.new(
        "escalation",
        model="small-model",
        reasoning_effort="off",
        planning_mode="off",
        self_critique=False,
    )

    async def emit(_etype, _payload):
        return None

    out = asyncio.run(rt.run_with_definition(defn, "do work", emit=emit))
    assert out == "done"
    # No automatic escalation: the user's model is the only model used.
    assert seen[0]["escalation_model"] == ""
    assert seen[0]["escalation_url"] == ""


def test_usage_events_reach_the_client_with_cost(monkeypatch) -> None:
    _record_runs(monkeypatch)
    monkeypatch.setattr(
        rt,
        "usage_payload",
        lambda payload: {
            "prompt_tokens": int(payload.get("prompt_tokens", 0)),
            "completion_tokens": int(payload.get("completion_tokens", 0)),
            "estimated_cost_usd": 0.25,
        },
    )

    def fake_run_agent(agent_id, sub_task, model, url, max_iters, on_step, **kwargs):
        kwargs["event_cb"]("agent:usage", {"prompt_tokens": 100, "completion_tokens": 50})
        return "done"

    monkeypatch.setattr(rt, "run_agent", fake_run_agent)
    events: list[tuple] = []

    async def emit(etype, payload):
        events.append((etype, payload))

    defn = AgentDefinition.new(
        "usage", reasoning_effort="off", planning_mode="off", self_critique=False
    )
    asyncio.run(rt.run_with_definition(defn, "do work", emit=emit))
    usage = next(p for t, p in events if t == "agent:usage")
    assert usage == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "estimated_cost_usd": 0.25,
    }


def test_capability_router_can_switch_the_run_model(monkeypatch) -> None:
    calls = _record_runs(monkeypatch)
    seen: list[dict] = []

    def fake_run_agent(agent_id, sub_task, model, url, max_iters, on_step, **kwargs):
        seen.append({"model": model, "url": url, **kwargs})
        return "done"

    monkeypatch.setattr(rt, "run_agent", fake_run_agent)
    from palimind.agents import model_routing as routing

    monkeypatch.setattr(
        routing,
        "route_model",
        lambda *_a, **_k: routing.ModelRoute(
            model="frontier-model",
            provider="hosted",
            reason="hard task → frontier fallback",
            unchanged=False,
        ),
    )
    events: list[tuple] = []

    async def emit(etype, payload):
        events.append((etype, payload))

    defn = AgentDefinition.new(
        "routing", reasoning_effort="off", planning_mode="off", self_critique=False
    )
    out = asyncio.run(rt.run_with_definition(defn, "do work", emit=emit))
    assert out.endswith("done")
    assert "Model routed" not in out
    # The router never replaces the user's selected model.
    assert seen[0]["model"] != "frontier-model"
    assert all(t != "agent:model_route" for t, _ in events)
    assert calls[0]["model_route"] is None


def test_hard_small_model_routes_to_grok_with_openai_client(monkeypatch) -> None:
    calls = _record_runs(monkeypatch)
    seen: list[dict] = []

    monkeypatch.setattr(
        rt, "_resolve_available_model", lambda requested, default, url: ("qwen3.5:4b", "")
    )

    def fake_run_agent(agent_id, sub_task, model, url, max_iters, on_step, **kwargs):
        seen.append({"model": model, "url": url, **kwargs})
        return "SAVED=3192"

    monkeypatch.setattr(rt, "run_agent", fake_run_agent)
    from palimind.agents import adaptive_reasoning as ar
    from palimind.agents import model_routing as routing

    monkeypatch.setattr(
        ar,
        "resolve_effort",
        lambda *_a, **_k: {
            "level": "high",
            "source": "test",
            "reasoning": "",
            "score": 1.0,
        },
    )
    monkeypatch.setattr(routing, "AGENT_FRONTIER_MODELS", ["grok-4.7"])
    monkeypatch.setattr(routing, "AGENT_FRONTIER_MIN_COMPLEXITY", "high")
    monkeypatch.setattr("palimind.opencode.router.opencode_model_ids", lambda: {"grok-4.7"})

    events: list[tuple] = []

    async def emit(etype, payload):
        events.append((etype, payload))

    defn = AgentDefinition.new(
        "frontier-route",
        model="qwen3.5:4b",
        reasoning_effort="high",
        planning_mode="off",
        self_critique=False,
    )
    out = asyncio.run(
        rt.run_with_definition(
            defn,
            "Analyse this system end to end and compute the result carefully.",
            emit=emit,
        )
    )
    assert out.endswith("SAVED=3192")
    assert seen[0]["model"] == "qwen3.5:4b"
    assert seen[0]["model_client"] is None
    assert all(t != "agent:model_route" for t, _ in events)
    assert calls[0]["model_route"] is None
