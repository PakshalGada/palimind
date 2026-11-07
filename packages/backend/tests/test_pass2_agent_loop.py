"""Pass-2 regressions: agent loop event order, cancellation, run status, proxy."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from palimind.agents import queue, scheduler
from palimind.agents.catalog import AgentDefinition
from palimind.llm.mixture_of_expert import agents as moe_agents
from palimind.opencode import router as oc_router


@pytest.fixture(autouse=True)
def _no_plugins(monkeypatch) -> None:
    monkeypatch.setattr(moe_agents, "_register_plugin_tools", lambda: None)
    from palimind.llm.mixture_of_expert import tools as moe_tools

    moe_tools.clear_todo()
    yield
    moe_tools.clear_todo()


def _scripted_llm(monkeypatch, replies: list[dict[str, Any]], calls: list[int]) -> None:
    def fake_chat(*_a, **_k) -> dict[str, Any]:
        calls.append(1)
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        return {"content": reply.get("content", ""), "tool_calls": reply.get("tool_calls", [])}

    monkeypatch.setattr(moe_agents, "llm_chat_safe", fake_chat)


# ── 1. text-protocol tool branch ordering ─────────────────────────────────


def test_text_tool_call_emitted_before_approval_and_allowlist_before_gate(monkeypatch) -> None:
    events: list[tuple[str, dict]] = []
    approvals: list[dict] = []
    calls: list[int] = []
    _scripted_llm(
        monkeypatch,
        [
            {"content": 'TOOL: write_file\nARGS: {"path": "a.txt", "content": "x"}'},
            {"content": "FINAL_ANSWER:\ndone"},
        ],
        calls,
    )
    monkeypatch.setattr(moe_agents, "call_tool", lambda *_a, **_k: "should not run")

    def approval(pending: dict) -> dict:
        approvals.append(pending)
        events.append(("approval", {}))
        return {"approved": True}

    # write_file is not in the explicit allow-list: it must be denied without
    # ever prompting the human.
    out = moe_agents.run_agent(
        1,
        {"task": "t", "tools": ["web_search"]},
        "m",
        "http://x",
        max_tool_iterations=3,
        event_cb=lambda t, p: events.append((t, p)),
        approval_provider=approval,
    )
    assert out == "done"
    assert approvals == []
    kinds = [e[0] for e in events if e[0] in ("agent:tool_call", "agent:tool_result")]
    assert kinds == ["agent:tool_call", "agent:tool_result"]
    result = next(p for t, p in events if t == "agent:tool_result")
    assert "allowlist" in result["result"]


def test_text_tool_call_precedes_approval_prompt(monkeypatch) -> None:
    order: list[str] = []
    calls: list[int] = []
    _scripted_llm(
        monkeypatch,
        [
            {"content": 'TOOL: write_file\nARGS: {"path": "a.txt", "content": "x"}'},
            {"content": "FINAL_ANSWER:\ndone"},
        ],
        calls,
    )
    monkeypatch.setattr(moe_agents, "call_tool", lambda *_a, **_k: "ok")

    def approval(_pending: dict) -> dict:
        order.append("approval")
        return {"approved": True}

    def cb(t: str, p: dict) -> None:
        if t in ("agent:tool_call", "agent:tool_result"):
            order.append(t)
            assert p["tool"] == "write_file"

    # Definition-less run: write_file needs approval.
    moe_agents.run_agent(
        1,
        {"task": "t", "tools": ["write_file"]},
        "m",
        "http://x",
        max_tool_iterations=3,
        event_cb=cb,
        approval_provider=approval,
    )
    assert order == ["agent:tool_call", "approval", "agent:tool_result"]


# ── 2. cancellation via run_control ───────────────────────────────────────


class _Control:
    def __init__(self) -> None:
        self.paused = threading.Event()
        self.cancelled = threading.Event()

    def drain_steer(self) -> list[str]:
        return []


def test_cancelled_run_control_skips_llm(monkeypatch) -> None:
    calls: list[int] = []
    _scripted_llm(monkeypatch, [{"content": "FINAL_ANSWER:\nx"}], calls)
    ctl = _Control()
    ctl.cancelled.set()
    usage: list[dict] = []
    out = moe_agents.run_agent(
        1,
        {"task": "t"},
        "m",
        "http://x",
        max_tool_iterations=3,
        run_control=ctl,
        usage_cb=usage.append,
    )
    assert out == moe_agents.CANCELLED_ANSWER
    assert calls == []
    assert usage  # usage still reported once


def test_cancel_between_llm_and_tool_skips_tool(monkeypatch) -> None:
    ctl = _Control()
    tool_runs: list[str] = []

    def fake_chat(*_a, **_k) -> dict[str, Any]:
        ctl.cancelled.set()  # Stop pressed while the model was thinking.
        return {
            "content": "",
            "tool_calls": [{"name": "web_search", "arguments": {"query": "q"}}],
        }

    monkeypatch.setattr(moe_agents, "llm_chat_safe", fake_chat)
    monkeypatch.setattr(moe_agents, "call_tool", lambda name, **_k: tool_runs.append(name) or "r")
    out = moe_agents.run_agent(
        1,
        {"task": "t", "tools": ["web_search"]},
        "m",
        "http://x",
        max_tool_iterations=3,
        run_control=ctl,
    )
    assert out == moe_agents.CANCELLED_ANSWER
    assert tool_runs == []


def test_cancel_text_protocol_skips_tool(monkeypatch) -> None:
    ctl = _Control()
    tool_runs: list[str] = []

    def fake_chat(*_a, **_k) -> dict[str, Any]:
        ctl.cancelled.set()
        return {"content": 'TOOL: web_search\nARGS: {"query": "q"}', "tool_calls": []}

    monkeypatch.setattr(moe_agents, "llm_chat_safe", fake_chat)
    monkeypatch.setattr(moe_agents, "call_tool", lambda name, **_k: tool_runs.append(name) or "r")
    out = moe_agents.run_agent(
        1,
        {"task": "t", "tools": ["web_search"]},
        "m",
        "http://x",
        max_tool_iterations=3,
        run_control=ctl,
    )
    assert out == moe_agents.CANCELLED_ANSWER
    assert tool_runs == []


def test_no_run_control_is_noop(monkeypatch) -> None:
    calls: list[int] = []
    _scripted_llm(monkeypatch, [{"content": "FINAL_ANSWER:\nhello"}], calls)
    out = moe_agents.run_agent(1, {"task": "t"}, "m", "http://x", max_tool_iterations=2)
    assert out == "hello"
    assert calls == [1]


# ── 3. errored runs reported as failures ──────────────────────────────────


def _fake_history(monkeypatch, records: list[dict]) -> None:
    from palimind.agents import runtime

    monkeypatch.setattr(runtime, "get_run_history", lambda _aid, limit=50: list(records))


def test_recorded_run_status_prefers_matching_record(monkeypatch) -> None:
    _fake_history(
        monkeypatch,
        [
            {"input": "a", "output": "[Agent run error] boom", "status": "error"},
            {"input": "b", "output": "fine", "status": "success"},
        ],
    )
    assert scheduler.recorded_run_status("x", "a", "[Agent run error] boom") == "error"
    assert scheduler.recorded_run_status("x", "b", "fine") == "success"


def test_fire_agent_posts_error_status(monkeypatch) -> None:
    defn = AgentDefinition.new("sched-bot")
    posted: list[str] = []

    async def fake_run(*_a, **_k) -> str:
        return "[Agent run error] boom"

    async def fake_post(_d, _out, status, _src) -> None:
        posted.append(status)

    monkeypatch.setattr(scheduler, "run_agent", fake_run)
    monkeypatch.setattr(scheduler, "post_result", fake_post)
    _fake_history(
        monkeypatch, [{"input": "go", "output": "[Agent run error] boom", "status": "error"}]
    )
    asyncio.run(scheduler._fire_agent(defn, "go", "scheduled"))
    assert posted == ["error"]


def test_queue_execute_marks_errored_run_failed(monkeypatch) -> None:
    defn = AgentDefinition.new("queue-bot")
    from palimind.agents import goals, registry, runtime, service

    updates: list[dict] = []
    notified: list[str] = []

    async def fake_run(*_a, **_k) -> str:
        return "[Agent run error] boom"

    monkeypatch.setattr(service, "run_agent", fake_run)
    monkeypatch.setattr(
        registry, "get_registry", lambda: SimpleNamespace(get_by_id=lambda _i: defn)
    )
    monkeypatch.setattr(runtime, "running_count", lambda _i: 0)
    monkeypatch.setattr(
        queue,
        "update_item",
        lambda _id, status=None, **kw: updates.append({"status": status, **kw}),
    )
    monkeypatch.setattr(goals, "notify", lambda *a, **k: notified.append(a[0]))
    _fake_history(
        monkeypatch, [{"input": "do", "output": "[Agent run error] boom", "status": "error"}]
    )
    asyncio.run(
        queue._execute({"id": "q1", "target_type": "agent", "target_id": defn.id, "input": "do"})
    )
    assert updates[-1]["status"] == "failed"
    assert "boom" in updates[-1]["error"]
    assert "queue_done" not in notified


# ── 4. opencode proxy respawn ─────────────────────────────────────────────


class _Proc:
    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


def test_ensure_proxy_respawns_dead_proxy(monkeypatch, tmp_path) -> None:
    spawned: list[_Proc] = []

    def fake_popen(*_a, **_k) -> _Proc:
        proc = _Proc()
        spawned.append(proc)
        return proc

    monkeypatch.setattr(oc_router, "_proxy_alive", lambda: False)
    monkeypatch.setattr(oc_router, "_key_configured", lambda: True)
    monkeypatch.setattr(oc_router, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(oc_router.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(oc_router, "_proxy_proc", None)
    monkeypatch.setattr(oc_router, "_proxy_last_spawn", float("-inf"))
    monkeypatch.setattr(oc_router, "_PROXY_RESPAWN_INTERVAL", 0.0)

    assert oc_router.ensure_proxy() is False
    assert len(spawned) == 1
    # Still running (starting up): no second spawn.
    oc_router.ensure_proxy()
    assert len(spawned) == 1
    # Proxy died: respawned.
    spawned[0].returncode = 1
    oc_router.ensure_proxy()
    assert len(spawned) == 2


def test_ensure_proxy_respawn_is_rate_limited(monkeypatch, tmp_path) -> None:
    spawned: list[_Proc] = []

    def fake_popen(*_a, **_k) -> _Proc:
        proc = _Proc()
        proc.returncode = 1  # crashes immediately
        spawned.append(proc)
        return proc

    monkeypatch.setattr(oc_router, "_proxy_alive", lambda: False)
    monkeypatch.setattr(oc_router, "_key_configured", lambda: True)
    monkeypatch.setattr(oc_router, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(oc_router.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(oc_router, "_proxy_proc", None)
    monkeypatch.setattr(oc_router, "_proxy_last_spawn", float("-inf"))
    for _ in range(5):
        oc_router.ensure_proxy()
    assert len(spawned) == 1


# ── 5. routine run endpoint returns without waiting ───────────────────────


def test_routine_run_endpoint_returns_immediately(monkeypatch) -> None:
    from palimind.agents import routines, teams_api

    defn = AgentDefinition.new("routine-bot")
    release: dict[str, Any] = {}
    notes: list[str] = []

    async def slow_run(_rid: str) -> str:
        release["ev"] = asyncio.Event()
        await release["ev"].wait()
        return "run-1"

    async def fake_notify(_r, status, _err="") -> None:
        notes.append(status)

    routine = {"id": "r1", "target_type": "agent", "target_id": defn.id, "name": "R"}
    monkeypatch.setattr(routines, "get_routine", lambda _rid: routine)
    monkeypatch.setattr(routines, "run_routine", slow_run)
    monkeypatch.setattr(
        teams_api, "get_registry", lambda: SimpleNamespace(get_by_id=lambda _i: defn)
    )
    monkeypatch.setattr(scheduler, "post_routine_notification", fake_notify)

    async def main() -> None:
        resp = await asyncio.wait_for(teams_api.run_routine("r1"), timeout=2)
        assert resp == {"status": "started"}
        for _ in range(50):
            if "ev" in release:
                break
            await asyncio.sleep(0.01)
        release["ev"].set()
        for _ in range(50):
            if notes:
                break
            await asyncio.sleep(0.01)

    asyncio.run(main())
    assert notes == ["success"]


def test_routine_run_endpoint_reports_missing_routine(monkeypatch) -> None:
    from palimind.agents import routines, teams_api

    monkeypatch.setattr(routines, "get_routine", lambda _rid: None)
    assert asyncio.run(teams_api.run_routine("nope")) == {"error": "Routine not found"}


# ── 4. live todo checklist + tool-result compaction ───────────────────────


def test_todo_write_normalizes_statuses_and_formats_progress() -> None:
    from palimind.llm.mixture_of_expert import tools as moe_tools

    moe_tools.apply_tool_context({})
    out = moe_tools.todo_write(
        [
            {"label": "Find sources", "status": "done"},
            {"title": "Read the top three", "status": "doing"},
            "Write the brief",
        ]
    )
    assert "Todo list — 1/3 completed" in out
    assert "[x] 1. Find sources" in out
    assert "[~] 2. Read the top three" in out
    assert "[ ] 3. Write the brief" in out
    items = moe_tools.get_todo_items()
    assert [item["status"] for item in items] == ["completed", "in_progress", "pending"]


def test_todo_write_accepts_json_string_and_clears() -> None:
    from palimind.llm.mixture_of_expert import tools as moe_tools

    moe_tools.apply_tool_context({})
    moe_tools.todo_write('[{"label": "A", "status": "completed"}, {"label": "B"}]')
    assert len(moe_tools.get_todo_items()) == 2
    assert moe_tools.todo_write([]) == "Todo list cleared."
    assert moe_tools.get_todo_items() == []


def test_todo_write_emits_live_todo_event(monkeypatch) -> None:
    from palimind.llm.mixture_of_expert import tools as moe_tools

    moe_tools.apply_tool_context({})
    calls: list[int] = []
    _scripted_llm(
        monkeypatch,
        [
            {
                "content": (
                    'TOOL: todo_write\nARGS: {"items": [{"label": "Step one", '
                    '"status": "in_progress"}, {"label": "Step two"}]}'
                )
            },
            {"content": "FINAL_ANSWER:\ndone"},
        ],
        calls,
    )
    events: list[tuple[str, dict]] = []
    out = moe_agents.run_agent(
        1,
        {"task": "t", "tools": ["todo_write"]},
        "m",
        "http://x",
        max_tool_iterations=3,
        event_cb=lambda t, p: events.append((t, p)),
    )
    assert out == "done"
    todo = next(p for t, p in events if t == "agent:todo")
    assert todo["items"][0]["status"] == "in_progress"
    assert todo["items"][1]["label"] == "Step two"


def test_compact_tool_result_keeps_head_and_tail() -> None:
    text = "HEAD-" + ("x" * 9000) + "-TAIL"
    out = moe_agents._compact_tool_result(text, limit=1000)
    assert len(out) <= 1000
    assert out.startswith("HEAD-")
    assert out.endswith("-TAIL")
    assert "characters elided" in out


def test_compact_tool_result_leaves_short_output_alone() -> None:
    assert moe_agents._compact_tool_result("short output", limit=1000) == "short output"


def test_sandbox_propagates_run_context_to_tool_thread() -> None:
    from palimind.agents.tools.sandbox import run_sandboxed_sync
    from palimind.llm.mixture_of_expert import tools as moe_tools

    moe_tools.set_tool_context(None, agent_id="ctx-agent", run_id="ctx-run")
    out = run_sandboxed_sync(
        lambda: moe_tools.todo_write([{"label": "Context-safe", "status": "in_progress"}]),
        timeout_s=5,
        tool_name="todo_write",
    )
    assert "Context-safe" in out
    # The checklist is keyed by the run id seen inside the sandbox thread.
    assert moe_tools.get_todo_items()[0]["label"] == "Context-safe"
    moe_tools.clear_todo("ctx-run")
    assert moe_tools.get_todo_items() == []


def test_agent_finishes_open_checklist_before_final_answer(monkeypatch) -> None:
    from palimind.llm.mixture_of_expert import tools as moe_tools

    moe_tools.apply_tool_context({})
    moe_tools.clear_todo()
    calls: list[int] = []
    _scripted_llm(
        monkeypatch,
        [
            {
                "content": (
                    'TOOL: todo_write\nARGS: {"items": [{"label": "Gather facts", '
                    '"status": "in_progress"}]}'
                )
            },
            {"content": "FINAL_ANSWER:\nearly answer"},
            {
                "content": (
                    'TOOL: todo_write\nARGS: {"items": [{"label": "Gather facts", '
                    '"status": "completed"}]}'
                )
            },
            {"content": "FINAL_ANSWER:\nfinished answer"},
        ],
        calls,
    )
    events: list[tuple[str, dict]] = []
    out = moe_agents.run_agent(
        1,
        {"task": "t", "tools": ["todo_write"]},
        "m",
        "http://x",
        max_tool_iterations=6,
        event_cb=lambda t, p: events.append((t, p)),
    )
    assert out == "finished answer"
    assert len(calls) == 4  # answer was rejected once, then the checklist finished
    thoughts = [p.get("text", "") for t, p in events if t == "agent:thought"]
    assert any("Checklist still has 1 open item" in text for text in thoughts)


# ── 5. live usage + automatic model escalation ────────────────────────────


def test_agent_emits_cumulative_usage_after_each_call(monkeypatch) -> None:
    def fake_chat(*_a, **_k) -> dict[str, Any]:
        return {
            "content": "FINAL_ANSWER:\ndone",
            "tool_calls": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    monkeypatch.setattr(moe_agents, "llm_chat_safe", fake_chat)
    events: list[tuple[str, dict]] = []
    out = moe_agents.run_agent(
        1,
        {"task": "t"},
        "m",
        "http://x",
        max_tool_iterations=2,
        event_cb=lambda t, p: events.append((t, p)),
    )
    assert out == "done"
    usage = [p for t, p in events if t == "agent:usage"]
    assert usage[-1] == {"prompt_tokens": 10, "completion_tokens": 5}


def test_exhausted_agent_escalates_to_stronger_model(monkeypatch) -> None:
    replies = [
        {"content": "I am still working.", "tool_calls": [], "usage": {}},
        {"content": "FINAL_ANSWER:\nstrong answer", "tool_calls": [], "usage": {}},
    ]
    seen: list[tuple[str, str]] = []

    def fake_chat(_messages, model, url, **_kwargs) -> dict[str, Any]:
        seen.append((model, url))
        return replies[min(len(seen) - 1, len(replies) - 1)]

    monkeypatch.setattr(moe_agents, "llm_chat_safe", fake_chat)
    events: list[tuple[str, dict]] = []
    out = moe_agents.run_agent(
        1,
        {"task": "t"},
        "small-model",
        "http://small",
        max_tool_iterations=1,
        event_cb=lambda t, p: events.append((t, p)),
        escalation_model="strong-model",
        escalation_url="http://strong",
    )
    assert out == "strong answer"
    assert seen[-1] == ("strong-model", "http://strong")
    escalation = next(p for t, p in events if t == "agent:escalation")
    assert escalation["from"] == "small-model"
    assert escalation["to"] == "strong-model"
    assert "budget exhausted" in escalation["reason"]


def test_escalation_is_skipped_above_cost_ceiling(monkeypatch) -> None:
    replies = [
        {"content": "still working on it", "tool_calls": [], "usage": {}},
        {"content": "FINAL_ANSWER:\nfinal from the original model", "tool_calls": [], "usage": {}},
    ]
    seen: list[str] = []

    def fake_chat(_messages, model, _url, **_kwargs) -> dict[str, Any]:
        seen.append(model)
        return replies[min(len(seen) - 1, len(replies) - 1)]

    monkeypatch.setattr(moe_agents, "llm_chat_safe", fake_chat)
    monkeypatch.setattr(
        "palimind.agents.pricing.estimate_cost_usd",
        lambda _usage: 2.5,
    )
    events: list[tuple[str, dict]] = []
    out = moe_agents.run_agent(
        1,
        {"task": "t"},
        "small-model",
        "http://small",
        max_tool_iterations=1,
        event_cb=lambda t, p: events.append((t, p)),
        escalation_model="strong-model",
        escalation_url="http://strong",
        escalation_max_cost_usd=1.0,
    )
    assert out == "final from the original model"
    assert seen[-1] == "small-model"
    escalation = next(p for t, p in events if t == "agent:escalation")
    assert escalation["skipped"] is True
    assert "cost ceiling" in escalation["reason"]


def test_plain_answer_is_accepted_as_final() -> None:
    assert moe_agents._final_answer_candidate("The answer is 42.") == "The answer is 42."
    assert moe_agents._final_answer_candidate("FINAL_ANSWER:\nmarked answer") == "marked answer"


def test_narration_and_tool_text_are_not_final_answers() -> None:
    assert moe_agents._final_answer_candidate("Let me search for that now.") == ""
    assert moe_agents._final_answer_candidate("I am still working on it.") == ""
    assert moe_agents._final_answer_candidate("TOOL: web_search") == ""
    assert moe_agents._final_answer_candidate("[tool call: fetch_url]") == ""
    assert moe_agents._final_answer_candidate("Using fetch_url.") == ""
    assert moe_agents._final_answer_candidate("Calling read_file.") == ""
    assert moe_agents._final_answer_candidate("short") == ""


def test_repeated_search_tool_triggers_early_synthesis(monkeypatch) -> None:
    replies = [
        {"content": "TOOL: web_search\nARGS: {&#x22;query&#x22;: &#x22;one&#x22;}"},
        {"content": "TOOL: web_search\nARGS: {&#x22;query&#x22;: &#x22;two&#x22;}"},
        {"content": "TOOL: web_search\nARGS: {&#x22;query&#x22;: &#x22;three&#x22;}"},
        {"content": "TOOL: web_search\nARGS: {&#x22;query&#x22;: &#x22;four&#x22;}"},
        {"content": "TOOL: web_search\nARGS: {&#x22;query&#x22;: &#x22;five&#x22;}"},
        {"content": "FINAL_ANSWER:\nsynthesised"},
    ]
    calls: list[int] = []
    _scripted_llm(monkeypatch, replies, calls)
    monkeypatch.setattr(moe_agents, "call_tool", lambda *_a, **_k: "result")
    out = moe_agents.run_agent(
        1,
        {"task": "t", "tools": ["web_search"]},
        "m",
        "http://x",
        max_tool_iterations=12,
    )
    assert out == "synthesised"
    assert len(calls) <= 6


def test_todo_update_limit_requires_progress() -> None:
    from palimind.llm.mixture_of_expert import tools as moe_tools

    moe_tools.apply_tool_context({})
    moe_tools.set_tool_context(None, run_id="todo-limit-test")
    same = [{"label": "A", "status": "in_progress"}, {"label": "B", "status": "pending"}]
    for _ in range(4):
        assert "limit reached" not in moe_tools.todo_write(same)
    blocked = moe_tools.todo_write(same)
    assert "limit reached" in blocked
    allowed = moe_tools.todo_write(
        [{"label": "A", "status": "completed"}, {"label": "B", "status": "pending"}]
    )
    assert "limit reached" not in allowed
    assert moe_tools.get_todo_items()[0]["status"] == "completed"
    moe_tools.clear_todo("todo-limit-test")


def test_runtime_closes_leftover_checklist_after_final_answer(monkeypatch) -> None:
    from palimind.llm.mixture_of_expert import tools as moe_tools

    moe_tools.apply_tool_context({})
    _scripted_llm(
        monkeypatch,
        [
            {
                "content": (
                    'TOOL: todo_write\nARGS: {"items": [{"label": "Do the work", '
                    '"status": "in_progress"}]}'
                )
            },
            {"content": "FINAL_ANSWER:\nthe answer"},
            {"content": "FINAL_ANSWER:\nthe answer"},
        ],
        [],
    )
    events: list[tuple[str, dict]] = []
    out = moe_agents.run_agent(
        1,
        {"task": "t", "tools": ["todo_write"]},
        "m",
        "http://x",
        max_tool_iterations=6,
        event_cb=lambda t, p: events.append((t, p)),
    )
    assert out == "the answer"
    todos = [p for t, p in events if t == "agent:todo"]
    assert todos[-1]["closed_by"] == "runtime_finalize"
    assert all(item["status"] == "completed" for item in todos[-1]["items"])


def test_openai_tool_calls_use_native_tool_roles(monkeypatch) -> None:
    calls: list[list[dict]] = []

    def fake_chat(messages, _model, _url, **_kwargs):
        calls.append([dict(message) for message in messages])
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "web_search",
                        "arguments": {"query": "q"},
                        "openai": True,
                    }
                ],
                "usage": {},
            }
        return {"content": "FINAL_ANSWER:\ndone", "tool_calls": [], "usage": {}}

    monkeypatch.setattr(moe_agents, "llm_chat_safe", fake_chat)
    monkeypatch.setattr(moe_agents, "call_tool", lambda *_a, **_k: "search result")
    out = moe_agents.run_agent(
        1, {"task": "t", "tools": ["web_search"]}, "m", "http://x", max_tool_iterations=4
    )
    assert out == "done"
    second = calls[1]
    assistant = next(m for m in second if m.get("tool_calls"))
    assert assistant["tool_calls"][0]["id"] == "call_1"
    tool_message = next(m for m in second if m.get("role") == "tool")
    assert tool_message["tool_call_id"] == "call_1"
    assert "search result" in tool_message["content"]
