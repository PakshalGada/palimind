"""Agent tools for browser takeover and profile state."""

from __future__ import annotations

import json
from typing import Any

from palimind.agents import browser_profiles


def _ctx() -> dict[str, Any]:
    from palimind.llm.mixture_of_expert.tools import _get_context

    return _get_context()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def browser_request_takeover(reason: str, tab_id: str = "") -> str:
    caller = str(_ctx().get("agent_id") or "")
    if not caller:
        return "Error: no calling agent"
    takeover = browser_profiles.request_takeover(caller, tab_id=tab_id, reason=reason)
    try:
        from palimind.agents.tools.browser.tool import request_control

        request_control(agent_id=caller, takeover_id=str(takeover.get("id") or ""))
    except Exception:
        pass
    return _json(
        {
            "takeover": takeover,
            "message": "Ask the user to complete this step in the browser panel.",
        }
    )


def browser_list_profiles() -> str:
    return _json({"profiles": browser_profiles.list_profiles()})


TOOLS: dict[str, dict[str, Any]] = {
    "browser_request_takeover": {
        "fn": browser_request_takeover,
        "description": "Ask the user to take over the browser for a sign-in, password, OTP or CAPTCHA.",
        "parameters": {
            "reason": {"type": "string"},
            "tab_id": {"type": "string", "required": False},
        },
        "tier": 1,
        "requires_approval": False,
    },
    "browser_list_profiles": {
        "fn": browser_list_profiles,
        "description": "List browser profiles available to this agent.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
    },
}
