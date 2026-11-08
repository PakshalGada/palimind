"""Per-tool allow / ask / deny policies gate execution before approval."""

from __future__ import annotations

from palimind.agents.catalog import AgentDefinition
from palimind.llm.mixture_of_expert.agents import _gate_tool


def _agent(**changes) -> AgentDefinition:
    return AgentDefinition.new("policy-test", **changes)


def test_deny_blocks_the_tool() -> None:
    agent = _agent(tool_policies={"web_search": "deny"})
    reason = _gate_tool("web_search", {}, definition=agent)
    assert reason is not None
    assert "tool policy" in reason


def test_allow_skips_the_approval_gate() -> None:
    agent = _agent(tool_policies={"write_file": "allow"}, write_access=True)
    assert _gate_tool("write_file", {"path": "a.txt", "content": "x"}, definition=agent) is None


def test_ask_keeps_the_normal_gate() -> None:
    agent = _agent(autonomy_level="supervised")
    assert _gate_tool("web_search", {}, definition=agent) is not None
    assert "approval" in (_gate_tool("web_search", {}, definition=agent) or "")


def test_invalid_policy_values_are_dropped_on_load() -> None:
    agent = AgentDefinition.from_dict(
        {
            "name": "policy-test",
            "tool_policies": {"web_search": "deny", "fetch_url": "maybe"},
        }
    )
    assert agent.tool_policies == {"web_search": "deny"}
