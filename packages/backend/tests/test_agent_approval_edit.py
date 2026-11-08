"""Edit-before-run approvals: args overrides are validated and applied."""

from __future__ import annotations

import asyncio

import pytest

from palimind.agents import runtime as rt
from palimind.llm.mixture_of_expert.agents import _request_approval


def _running(agent_id: str = "a1", run_id: str = "r1", tool: str = "write_file"):
    ra = rt.RunningAgent(agent_id, run_id, asyncio.new_event_loop())
    ra.pending = {"tool": tool, "args": {"path": "old.txt", "content": "old"}}
    return ra


def test_override_replaces_the_tool_args() -> None:
    args = {"path": "old.txt", "content": "old"}

    def provider(_pending):
        return {
            "approved": True,
            "args": {"path": "new.txt", "content": "reviewed content"},
        }

    assert _request_approval("write_file", args, provider, "") is None
    assert args == {"path": "new.txt", "content": "reviewed content"}


def test_rejection_keeps_the_original_args() -> None:
    args = {"path": "old.txt", "content": "old"}

    def provider(_pending):
        return {"approved": False, "correction": "do not write this"}

    reason = _request_approval("write_file", args, provider, "")
    assert reason is not None
    assert "rejected" in reason
    assert args == {"path": "old.txt", "content": "old"}


def test_schema_validation_accepts_and_rejects_overrides(monkeypatch) -> None:
    ra = _running()
    monkeypatch.setattr(rt, "_running", {"a1": {"r1": ra}})

    assert rt.validate_approval_args("a1", {"path": "x.txt", "content": "ok"}, "r1") is None
    error = rt.validate_approval_args("a1", {"path": "x.txt"}, "r1")
    assert error is not None
    assert "content" in error


def test_resolve_stores_the_override(monkeypatch) -> None:
    ra = _running()
    monkeypatch.setattr(rt, "_running", {"a1": {"r1": ra}})

    ok = asyncio.run(
        rt.resolve_approval(
            "a1",
            True,
            run_id="r1",
            args={"path": "x.txt", "content": "edited"},
        )
    )
    assert ok is True
    assert ra.approval_result == {
        "approved": True,
        "correction": "",
        "args": {"path": "x.txt", "content": "edited"},
    }
    assert ra.approval_event.is_set()


@pytest.mark.parametrize("tool", ["run_shell", "write_file"])
def test_validation_uses_the_pending_tool(tool: str, monkeypatch) -> None:
    from palimind.llm.mixture_of_expert.tools import _register_plugin_tools

    _register_plugin_tools()
    ra = _running(tool=tool)
    monkeypatch.setattr(rt, "_running", {"a1": {"r1": ra}})
    # Both tools reject an empty argument object.
    error = rt.validate_approval_args("a1", {}, "r1")
    assert error is not None
