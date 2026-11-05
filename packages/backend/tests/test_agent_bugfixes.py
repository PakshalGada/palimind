"""Regression tests for agent runtime / scheduling / queue bug fixes."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from palimind.agents import activity, goals, queue, scheduler
from palimind.agents import runtime as rt
from palimind.agents.catalog import AgentDefinition, validate_cron

# ── cron ──────────────────────────────────────────────────────────────────


def test_cron_step_counts_from_field_minimum() -> None:
    # "*/2" day-of-month = 1,3,5,…; "*/3" month = Jan, Apr, Jul, Oct.
    assert scheduler.cron_matches("0 9 */2 * *", datetime(2026, 3, 1, 9, 0))
    assert not scheduler.cron_matches("0 9 */2 * *", datetime(2026, 3, 2, 9, 0))
    assert scheduler.cron_matches("0 9 1 */3 *", datetime(2026, 4, 1, 9, 0))
    assert not scheduler.cron_matches("0 9 1 */3 *", datetime(2026, 3, 1, 9, 0))
    # minutes/hours start at 0 so behaviour there is unchanged.
    assert scheduler.cron_matches("*/15 * * * *", datetime(2026, 3, 2, 9, 30))


def test_cron_dom_and_dow_are_ored_when_both_restricted() -> None:
    # 2026-03-02 is a Monday, 2026-03-01 a Sunday, 2026-03-04 a Wednesday.
    assert scheduler.cron_matches("0 9 1 * 1", datetime(2026, 3, 2, 9, 0))  # Monday
    assert scheduler.cron_matches("0 9 1 * 1", datetime(2026, 3, 1, 9, 0))  # the 1st
    assert not scheduler.cron_matches("0 9 1 * 1", datetime(2026, 3, 4, 9, 0))
    # With a wildcard day-of-month only the weekday restricts.
    assert not scheduler.cron_matches("0 9 * * 1", datetime(2026, 3, 1, 9, 0))


def test_cron_sunday_as_seven_in_ranges() -> None:
    assert scheduler.cron_matches("0 9 * * 5-7", datetime(2026, 3, 1, 9, 0))  # Sunday
    assert scheduler.cron_matches("0 9 * * 7", datetime(2026, 3, 1, 9, 0))


def test_validate_cron_rejects_never_firing_fields() -> None:
    assert validate_cron("*/0 * * * *") is not None
    assert validate_cron("0 17-9 * * *") is not None
    assert validate_cron("*/5 9-17 * * 1-5") is None


# ── runtime registry ──────────────────────────────────────────────────────


def test_cancel_unknown_run_id_does_not_cancel_other_runs() -> None:
    async def scenario() -> None:
        async def body() -> None:
            await rt.register_running("agent-x", "run-a", 2)
            await asyncio.sleep(10)

        task = asyncio.create_task(body())
        await asyncio.sleep(0)
        try:
            assert rt.cancel_agent("agent-x", "finished-run") == 0
            await asyncio.sleep(0)
            assert not task.cancelled()
            assert rt.cancel_agent("agent-x", "run-a") == 1
        finally:
            task.cancel()
            await rt.unregister_running("agent-x")

    asyncio.run(scenario())


def test_resolve_approval_without_run_id_targets_waiting_run() -> None:
    async def scenario() -> None:
        waiting = await rt.register_running("agent-y", "run-1", 2)
        newer = await rt.register_running("agent-y", "run-2", 2)
        try:
            waiting.pending = {"tool": "write_file"}
            assert await rt.resolve_approval("agent-y", True)
            assert waiting.approval_result == {"approved": True, "correction": ""}
            assert newer.approval_result is None
        finally:
            await rt.unregister_running("agent-y")

    asyncio.run(scenario())


def test_parallel_approvals_are_serialised(monkeypatch) -> None:
    monkeypatch.setattr(rt.approvals, "add", lambda *a, **k: None)
    monkeypatch.setattr(rt.approvals, "remove", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_tool_tier", lambda name: 2)

    async def scenario() -> None:
        ra = await rt.register_running("agent-z", "run-z", 1)
        events: list[dict] = []

        async def emit(etype: str, payload: dict) -> None:
            events.append(payload)

        provider = rt._make_approval_provider(ra, emit)
        results: dict[str, Any] = {}

        def worker(tool: str) -> None:
            results[tool] = provider({"tool": tool, "args": {}})

        t1 = threading.Thread(target=worker, args=("write_file",))
        t2 = threading.Thread(target=worker, args=("run_shell",))
        t1.start()
        t2.start()
        try:
            for _ in range(100):
                if events:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            # Only one request is surfaced at a time.
            assert len(events) == 1
            first = events[0]["tool"]
            assert await rt.resolve_approval("agent-z", True)
            for _ in range(100):
                if len(events) == 2:
                    break
                await asyncio.sleep(0.01)
            assert len(events) == 2
            second = events[1]["tool"]
            assert second != first
            assert await rt.resolve_approval("agent-z", False)
            await asyncio.to_thread(t1.join, 5)
            await asyncio.to_thread(t2.join, 5)
            assert results[first]["approved"] is True
            assert results[second]["approved"] is False
        finally:
            ra.release()
            await rt.unregister_running("agent-z")

    asyncio.run(scenario())


# ── run_with_definition cancellation ──────────────────────────────────────


@pytest.fixture
def _stub_run(monkeypatch):
    monkeypatch.setattr(rt, "set_tool_context", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_field_models", lambda root=None: ("m", "http://x", "light"))
    monkeypatch.setattr(rt, "_resolve_available_model", lambda *a, **k: ("m", ""))
    monkeypatch.setattr("palimind.opencode.router.resolve_model_url", lambda model, url: url)
    monkeypatch.setattr(rt, "recall_memory", lambda *a, **k: [])
    monkeypatch.setattr(rt, "append_chat", lambda *a, **k: None)
    monkeypatch.setattr(rt, "append_memory", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_workspace_context_block", lambda root: "")
    from palimind.agents import run_journal

    monkeypatch.setattr(run_journal, "start", lambda *a, **k: None)
    monkeypatch.setattr(run_journal, "append", lambda *a, **k: None)
    monkeypatch.setattr(run_journal, "finish", lambda *a, **k: None)
    records: list[dict] = []

    def fake_record(agent_id, run_id, input, output, status, duration, **kwargs):
        records.append({"output": output, "status": status})

    monkeypatch.setattr(rt, "record_run", fake_record)
    return records


def test_cancel_during_plan_review_releases_agent(monkeypatch, _stub_run) -> None:
    from palimind.agents import planner as pl

    plan = pl.new_plan("task", [{"title": "Step"}])
    monkeypatch.setattr(pl, "generate_plan", lambda *a, **k: plan)
    monkeypatch.setattr(pl, "save_plan", lambda p: p)

    defn = AgentDefinition.new("plan-cancel", reasoning_effort="off", planning_mode="review")

    async def emit(etype: str, payload: dict) -> None:
        return None

    async def scenario() -> None:
        task = asyncio.create_task(rt.run_with_definition(defn, "work", emit=emit))
        for _ in range(100):
            if pl._waiters:
                break
            await asyncio.sleep(0.01)
        assert rt.is_running(defn.id)
        assert rt.cancel_agent(defn.id) == 1
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not rt.is_running(defn.id)

    asyncio.run(scenario())
    assert _stub_run and _stub_run[0]["status"] == "cancelled"
    assert not any(r["agent_id"] == defn.id for r in activity.snapshot()["running"])


def test_cancel_stops_worker_thread_blocked_on_approval(monkeypatch, _stub_run) -> None:
    monkeypatch.setattr(rt.approvals, "add", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_tool_tier", lambda name: 2)
    worker_done = threading.Event()
    after_approval: list[str] = []

    def fake_run_agent(agent_id, sub_task, model, url, max_iters, on_step, **kwargs):
        try:
            result = kwargs["approval_provider"]({"tool": "write_file", "args": {}})
            after_approval.append(str(result.get("approved")))
            kwargs["event_cb"]("agent:tool_result", {"tool": "write_file", "result": "x"})
            after_approval.append("kept running")
            return "done"
        finally:
            worker_done.set()

    monkeypatch.setattr(rt, "run_agent", fake_run_agent)
    defn = AgentDefinition.new("approval-cancel", reasoning_effort="off", planning_mode="off")

    async def emit(etype: str, payload: dict) -> None:
        return None

    async def scenario() -> None:
        task = asyncio.create_task(rt.run_with_definition(defn, "work", emit=emit))
        for _ in range(200):
            ra = rt.get_running(defn.id)
            if ra is not None and ra.pending is not None:
                break
            await asyncio.sleep(0.01)
        assert rt.cancel_agent(defn.id) == 1
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert worker_done.wait(5), "worker thread stayed blocked after cancel"
    assert after_approval == ["False"]


# ── goals ─────────────────────────────────────────────────────────────────


@pytest.fixture
def _goal_files(monkeypatch, tmp_path: Path):
    from palimind.storage import state_store

    paths = (
        tmp_path / "goals.json",
        tmp_path / "tasks.json",
        tmp_path / "notifications.json",
    )
    for path in paths:
        state_store.delete_json(goals._namespace(path), "items")
    monkeypatch.setattr(goals, "GOALS_FILE", paths[0])
    monkeypatch.setattr(goals, "TASKS_FILE", paths[1])
    monkeypatch.setattr(goals, "NOTIFICATIONS_FILE", paths[2])


def test_loop_task_cancelled_while_running_stays_cancelled(_goal_files) -> None:
    task = goals.create_task(agent_id="a", prompt="p", kind="loop", interval_seconds=60)
    goals.mark_running(task["id"])
    goals.cancel_task(task["id"])
    done = goals.complete_task(task["id"], status="success", output="ok")
    assert done is not None and done["status"] == "cancelled"
    assert goals.due_tasks(now=done["last_run"] + 3600) == []


def test_stale_running_tasks_are_recovered(_goal_files) -> None:
    task = goals.create_task(agent_id="a", prompt="p")
    goals.mark_running(task["id"])
    assert goals.recover_stale_running() == 1
    assert [t["id"] for t in goals.due_tasks()] == [task["id"]]


# ── queue ─────────────────────────────────────────────────────────────────


@pytest.fixture
def _queue_store(monkeypatch):
    items: dict[str, dict] = {}
    store = queue.state_store
    monkeypatch.setattr(
        store, "upsert_queue_item", lambda item: items.__setitem__(item["id"], dict(item))
    )
    monkeypatch.setattr(
        store, "get_queue_item", lambda item_id: dict(items[item_id]) if item_id in items else None
    )
    monkeypatch.setattr(
        store,
        "list_queue_items",
        lambda target_type=None, target_id=None, limit=200: [dict(i) for i in items.values()][
            :limit
        ],
    )
    return items


def test_queue_limit_ignores_finished_items(monkeypatch, _queue_store) -> None:
    monkeypatch.setattr(queue, "QUEUE_LIMIT", 2)
    first = queue.enqueue("agent", "a", "one")
    second = queue.enqueue("agent", "a", "two")
    queue.update_item(first["id"], status="done")
    queue.update_item(second["id"], status="cancelled")
    queue.enqueue("agent", "a", "three")  # must not raise "queue limit reached"


def test_queue_item_for_busy_agent_is_requeued(monkeypatch, _queue_store) -> None:
    defn = AgentDefinition.new("busy-agent")

    class _Reg:
        def get_by_id(self, agent_id):
            return defn if agent_id == defn.id else None

    monkeypatch.setattr("palimind.agents.registry.get_registry", lambda: _Reg())
    monkeypatch.setattr(rt, "running_count", lambda agent_id: 1)
    item = queue.enqueue("agent", defn.id, "later")
    assert queue.next_due() is None  # busy target is skipped
    queue.update_item(item["id"], status="running")
    asyncio.run(queue._execute(queue.get_item(item["id"]) or {}))
    assert (queue.get_item(item["id"]) or {})["status"] == "queued"
    queue.update_item(item["id"], status="running")
    assert queue.recover_stale_running() == 1


# ── activity ──────────────────────────────────────────────────────────────


def test_activity_finish_of_older_run_keeps_newer_run_live() -> None:
    activity.start("act-agent", "Agent", "run-old")
    activity.start("act-agent", "Agent", "run-new")
    activity.finish("act-agent", "success", "", run_id="run-old")
    assert any(r["run_id"] == "run-new" for r in activity.snapshot()["running"])
    activity.finish("act-agent", "success", "", run_id="run-new")
    assert not any(r["agent_id"] == "act-agent" for r in activity.snapshot()["running"])
