"""Tests for durable agent run checkpoints and resume."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.agents import run_state


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    yield


def _state(run_id: str = "run-1", **changes):
    base = {
        "run_id": run_id,
        "agent_id": "agent-1",
        "input": "do the task",
        "session_id": "s1",
        "model": "m",
        "ollama_url": "http://localhost:11434",
        "messages": [{"role": "user", "content": "hello"}],
        "working_notes": ["note"],
        "iteration": 1,
        "status": "running",
    }
    base.update(changes)
    return base


def test_save_load_and_bounds() -> None:
    long = "x" * 20_000
    state = _state(messages=[{"role": "user", "content": long}] * 200)
    saved = run_state.save_state(state)
    assert len(saved["messages"]) == run_state.MAX_MESSAGES
    assert len(saved["messages"][0]["content"]) == run_state.MAX_MESSAGE_CHARS
    loaded = run_state.load_state("run-1")
    assert loaded is not None
    assert loaded["input"] == "do the task"
    assert loaded["messages"] == saved["messages"]


def test_finalize_and_mark_resumed() -> None:
    run_state.save_state(_state())
    final = run_state.finalize("run-1", "success", "done")
    assert final is not None
    assert final["status"] == "success"
    assert final["resumable"] is False

    run_state.save_state(_state(run_id="run-2"))
    cancelled = run_state.finalize("run-2", "cancelled", "stopped")
    assert cancelled is not None
    assert cancelled["resumable"] is True

    run_state.mark_resumed("run-2", "run-3")
    old = run_state.load_state("run-2")
    assert old is not None
    assert old["status"] == "resumed"
    assert old["resumed_by"] == "run-3"
    assert old["resumable"] is False


def test_startup_recovery_marks_running_resumable() -> None:
    run_state.save_state(_state())
    run_state.save_state(_state(run_id="done-1", status="success", output="done"))
    recovered = run_state.recover_interrupted()
    assert [item["run_id"] for item in recovered] == ["run-1"]
    assert run_state.load_state("run-1")["status"] == "resumable"  # type: ignore[index]
    assert run_state.load_state("done-1")["status"] == "success"  # type: ignore[index]


def test_run_agent_resumes_without_repeating_completed_tools(monkeypatch, tmp_path: Path) -> None:
    from palimind.llm.mixture_of_expert import agents as agents_mod
    from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, set_tool_context

    calls: list[str] = []

    def _probe() -> str:
        calls.append("called")
        return "tool result"

    TOOL_REGISTRY["_resume_probe"] = {
        "fn": _probe,
        "description": "resume probe",
        "parameters": {},
        "meta": {"tier": 1, "requires_approval": False},
        "parallel_safe": True,
        "idempotent": True,
        "timeout_s": 10,
    }
    set_tool_context(tmp_path)
    sub_task = {
        "agent_id": 1,
        "definition_id": "agent-uuid",
        "label": "resume-test",
        "task": "do it",
        "tools": ["_resume_probe"],
        "context": "",
    }

    responses = [
        {
            "content": "",
            "tool_calls": [{"name": "_resume_probe", "arguments": {}}],
            "usage": {},
        }
    ]

    def _fake_chat(*args, **kwargs):
        if responses:
            return responses.pop(0)
        raise RuntimeError("simulated server crash")

    monkeypatch.setattr(agents_mod, "llm_chat_safe", _fake_chat)
    try:
        with pytest.raises(RuntimeError, match="simulated server crash"):
            agents_mod.run_agent(
                1,
                sub_task,
                "m",
                "http://localhost:11434",
                max_tool_iterations=5,
                run_id="run-1",
            )
        assert calls == ["called"]

        checkpoint = run_state.load_state("run-1")
        assert checkpoint is not None
        assert checkpoint["agent_id"] == "agent-uuid"
        assert checkpoint["status"] == "running"
        assert checkpoint["iteration"] == 1
        assert len(checkpoint["messages"]) == 2

        # Simulate a process restart: stale "running" becomes resumable.
        run_state.recover_interrupted()
        checkpoint = run_state.load_state("run-1")
        assert checkpoint is not None and checkpoint["status"] == "resumable"

        # Resume: the model now completes; the completed tool must not re-run.
        monkeypatch.setattr(
            agents_mod,
            "llm_chat_safe",
            lambda *a, **k: {"content": "FINAL_ANSWER: done", "tool_calls": [], "usage": {}},
        )
        output = agents_mod.run_agent(
            1,
            sub_task,
            "m",
            "http://localhost:11434",
            max_tool_iterations=5,
            run_id="run-2",
            resume_state=checkpoint,
            resume_from_run_id="run-1",
        )
        assert "done" in output
        assert calls == ["called"]  # not repeated
        resumed = run_state.load_state("run-2")
        assert resumed is not None and resumed["status"] == "completed"
        old = run_state.load_state("run-1")
        assert old is not None and old["status"] == "resumed"
    finally:
        TOOL_REGISTRY.pop("_resume_probe", None)
        set_tool_context(None)


def test_resume_endpoints(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.agents.api as agents_api
    from palimind.agents.catalog import AgentDefinition

    defn = AgentDefinition.new("resume-endpoint-test")
    state = _state(run_id="run-api", agent_id=defn.id, status="resumable", resumable=True)
    run_state.save_state(state)

    class _Registry:
        def get_by_id(self, agent_id: str):
            return defn if agent_id == defn.id else None

    captured: dict = {}

    async def _fake_stream(defn_arg, input_text, session_id, **kwargs):
        captured.update(
            {
                "agent_id": defn_arg.id,
                "input": input_text,
                "session_id": session_id,
                **kwargs,
            }
        )
        yield {"type": "agent:completed", "output": "resumed", "status": "success"}

    monkeypatch.setattr(agents_api, "get_registry", lambda: _Registry())
    monkeypatch.setattr(agents_api, "stream_agent", _fake_stream)

    # Use the main app so the router is mounted with the rest of the API.
    import palimind.api_server as server

    client = TestClient(server.app)
    got = client.get(f"/api/agents/{defn.id}/runs/run-api/state")
    assert got.status_code == 200
    body = got.json()
    assert body["state"]["input"] == "do the task"
    assert body["resumable"] is True

    resumed = client.post(f"/api/agents/{defn.id}/runs/run-api/resume", json={})
    assert resumed.status_code == 200
    assert "resumed" in resumed.text
    assert captured["resume_state"]["run_id"] == "run-api"
    assert captured["resume_from_run_id"] == "run-api"
