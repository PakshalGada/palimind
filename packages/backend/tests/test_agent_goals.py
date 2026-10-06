"""Tests for goals and background tasks."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from palimind.agents import goals as g


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(g, "GOALS_FILE", tmp_path / "goals.json")
    monkeypatch.setattr(g, "TASKS_FILE", tmp_path / "tasks.json")
    monkeypatch.setattr(g, "NOTIFICATIONS_FILE", tmp_path / "notifications.json")
    yield


def test_parse_duration() -> None:
    assert g.parse_duration("30s") == 30
    assert g.parse_duration("5m") == 300
    assert g.parse_duration("2h") == 7200
    assert g.parse_duration("1d") == 86400
    assert g.parse_duration("0m") is None
    assert g.parse_duration("soon") is None


def test_parse_loop_command() -> None:
    parsed = g.parse_loop_command("/loop 5m check tests")
    assert parsed == {"interval_seconds": 300, "prompt": "check tests"}
    assert g.parse_loop_command("/loop 5m") == {"interval_seconds": 300, "prompt": "Run your task."}
    assert g.parse_loop_command("/loop nonsense") is None
    assert g.parse_loop_command("not a loop") is None


def test_goal_lifecycle() -> None:
    goal = g.create_goal("Ship v1", "release the product", agent_id="a1")
    assert g.get_goal(goal["id"]) is not None
    assert any(x["id"] == goal["id"] for x in g.list_goals())

    updated = g.update_goal(goal["id"], {"status": "paused", "progress": 2.0})
    assert updated["status"] == "paused" and updated["progress"] == 1.0

    assert g.delete_goal(goal["id"]) is True
    assert g.get_goal(goal["id"]) is None


def test_progress_completes_goal_and_notifies() -> None:
    goal = g.create_goal("Finish", "finish it")
    g.set_progress(goal["id"], 1.0, note="done")
    refreshed = g.get_goal(goal["id"])
    assert refreshed["status"] == "completed"
    assert any(n["kind"] == "goal_completed" for n in g.list_notifications())


def test_task_limits_and_cancel() -> None:
    task = g.create_task(agent_id="a1", prompt="do work", kind="once")
    assert g.get_task(task["id"])["status"] == "pending"
    assert g.list_tasks()
    cancelled = g.cancel_task(task["id"])
    assert cancelled["status"] == "cancelled"
    assert g.delete_task(task["id"]) is True


def test_loop_task_requires_interval() -> None:
    with pytest.raises(ValueError):
        g.create_task(agent_id="a1", prompt="x", kind="loop", interval_seconds=2)


def test_max_task_limit(monkeypatch) -> None:
    monkeypatch.setattr(g, "GOALS_MAX_TASKS", 2)
    g.create_task(agent_id="a", prompt="1")
    g.create_task(agent_id="a", prompt="2")
    with pytest.raises(ValueError):
        g.create_task(agent_id="a", prompt="3")


def test_due_and_complete_loop_reschedules() -> None:
    now = time.time()
    task = g.create_task(agent_id="a", prompt="loop", kind="loop", interval_seconds=60)
    due = g.due_tasks(now=now + 1)
    assert any(t["id"] == task["id"] for t in due)
    g.complete_task(task["id"], status="success", output="ok", now=now + 2)
    refreshed = g.get_task(task["id"])
    assert refreshed["status"] == "pending"
    assert refreshed["run_count"] == 1
    assert refreshed["next_run"] > now + 2


def test_due_expires_stale_tasks() -> None:
    task = g.create_task(agent_id="a", prompt="x", kind="once")
    # Force it into the past.
    g._update_task(task["id"], {"expires_at": time.time() - 10})
    assert g.due_tasks() == []
    assert g.get_task(task["id"])["status"] == "expired"


def test_recompute_progress_from_tasks() -> None:
    goal = g.create_goal("g", "obj")
    t1 = g.create_task(agent_id="a", prompt="1", goal_id=goal["id"])
    g.create_task(agent_id="a", prompt="2", goal_id=goal["id"])
    g.complete_task(t1["id"], status="success", output="ok")
    refreshed = g.get_goal(goal["id"])
    assert 0.0 < refreshed["progress"] < 1.0


def test_notifications_read_and_clear() -> None:
    g.notify("info", "hello")
    assert g.list_notifications(unread_only=True)
    assert g.mark_notifications_read() == 1
    assert g.list_notifications(unread_only=True) == []
    g.clear_notifications()
    assert g.list_notifications() == []
