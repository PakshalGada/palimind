"""Agent tools for quiet and failed routine runs."""

from __future__ import annotations

import json
from typing import Any

from palimind.agents import routine_signals


def _ctx() -> dict[str, Any]:
    from palimind.llm.mixture_of_expert.tools import _get_context

    return _get_context()


def routine_no_update(reason: str = "") -> str:
    run_id = str(_ctx().get("run_id") or "")
    if not run_id:
        return "Error: routine_no_update is only valid inside a routine run"
    routine_signals.mark_quiet(run_id, reason)
    return json.dumps({"status": "quiet", "run_id": run_id})


def routine_report_failure(reason: str) -> str:
    run_id = str(_ctx().get("run_id") or "")
    if not run_id:
        return "Error: routine_report_failure is only valid inside a routine run"
    routine_signals.report_failure(run_id, reason)
    return json.dumps({"status": "failed", "run_id": run_id, "reason": reason})


TOOLS: dict[str, dict[str, Any]] = {
    "routine_no_update": {
        "fn": routine_no_update,
        "description": "End a routine run quietly when there is no update for the user.",
        "parameters": {"reason": {"type": "string", "required": False}},
        "tier": 1,
        "requires_approval": False,
    },
    "routine_report_failure": {
        "fn": routine_report_failure,
        "description": "Report that a routine task could not be done, with a short reason.",
        "parameters": {"reason": {"type": "string"}},
        "tier": 1,
        "requires_approval": False,
    },
}
