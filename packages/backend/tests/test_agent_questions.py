"""Tests for mid-run questions (ask_user) and user-edited checklists."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from palimind.agents import questions


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(questions, "_PATH", tmp_path / "pending_questions.json")
    monkeypatch.setattr(questions, "_pending", {})
    monkeypatch.setattr(questions, "_events", {})
    monkeypatch.setattr(questions, "_entry_is_live", lambda _entry: True)
    yield
    monkeypatch.setattr(questions, "_pending", {})
    monkeypatch.setattr(questions, "_events", {})


def test_ask_blocks_until_answered() -> None:
    result: dict = {}
    emitted: list[tuple[str, dict]] = []

    def worker() -> None:
        result.update(
            questions.ask(
                "Which account?",
                agent_id="a1",
                run_id="r1",
                options=["work", "personal"],
                timeout_s=10,
                on_emit=lambda kind, payload: emitted.append((kind, payload)),
            )
        )

    thread = threading.Thread(target=worker)
    thread.start()
    for _ in range(50):
        pending = questions.list_pending()
        if pending:
            break
        time.sleep(0.02)
    assert pending, "question was not registered"
    assert emitted and emitted[0][0] == "agent:question"
    assert emitted[0][1]["options"] == ["work", "personal"]

    assert questions.answer(pending[0]["id"], choice="work") is True
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result["status"] == "answered"
    assert result["choice"] == "work"
    assert questions.list_pending() == []


def test_ask_times_out_without_answer() -> None:
    started = time.time()
    result = questions.ask("Still there?", agent_id="a1", run_id="r2", timeout_s=5)
    # timeout_s has a 5s floor; the call must not hang forever.
    assert result["status"] in {"timeout", "cancelled"}
    assert time.time() - started < 15


def test_ask_cancels_when_run_stops() -> None:
    result = questions.ask(
        "Continue?",
        agent_id="a1",
        run_id="r3",
        timeout_s=30,
        should_cancel=lambda: True,
    )
    assert result["status"] == "cancelled"


def test_answer_unknown_question_is_false() -> None:
    assert questions.answer("missing", answer="x") is False


def test_ask_user_tool_uses_context(monkeypatch) -> None:
    from palimind.llm.mixture_of_expert import tools

    monkeypatch.setattr(
        tools,
        "_get_context",
        lambda: {"agent_id": "a1", "run_id": "r4", "emit_event": None, "run_control": None},
    )
    result: dict = {}

    def worker() -> None:
        result["text"] = tools.ask_user("Pick one", options=["a", "b"], timeout_s=10)

    thread = threading.Thread(target=worker)
    thread.start()
    for _ in range(50):
        pending = questions.list_pending()
        if pending:
            break
        time.sleep(0.02)
    assert pending
    questions.answer(pending[0]["id"], choice="b")
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result["text"] == "User answered: b"


def test_user_plan_replaces_run_checklist(monkeypatch) -> None:
    from palimind.llm.mixture_of_expert import tools

    monkeypatch.setattr(tools, "_todo_key", lambda: "run-plan-test")
    tools.clear_todo("run-plan-test")
    tools.set_todo_items([{"label": "step one", "status": "completed"}])
    assert tools.get_todo_items()[0]["label"] == "step one"
    tools.set_todo_items(
        [
            {"label": "step one", "status": "completed"},
            {"label": "user added", "status": "pending"},
        ]
    )
    assert [item["label"] for item in tools.get_todo_items()] == ["step one", "user added"]
    tools.clear_todo("run-plan-test")
