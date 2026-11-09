"""Access-gate and agent-definition tests for computer use."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from palimind.agents.catalog import AgentDefinition, validate_definition
from palimind.llm.mixture_of_expert.agents import _desktop_app_allowed, _gate_tool
from palimind.llm.mixture_of_expert.tools import _register_plugin_tools


@pytest.fixture(autouse=True, scope="module")
def _registered_tools():
    # The tier gate reads TOOL_REGISTRY; the app registers plugins at run
    # start, so tests do the same rather than guessing a tool's tier.
    _register_plugin_tools()


def _def(**overrides):
    values = {
        "tier_policy": "tier1+2",
        "autonomy_level": "off",
        "write_access": False,
        "shell_access": False,
        "always_allow_tools": [],
        "desktop_access": True,
        "desktop_control": True,
        "desktop_allowed_apps": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_desktop_tools_require_desktop_access():
    denied = _gate_tool("desktop_snapshot", {"app": "demo"}, definition=_def(desktop_access=False))
    assert denied and "desktop_access" in denied


def test_observe_is_allowed_with_access_only():
    assert _gate_tool("desktop_snapshot", {"app": "demo"}, definition=_def()) is None
    assert _gate_tool("desktop_apps", {"kind": "windows"}, definition=_def()) is None


def test_mutation_requires_desktop_control():
    denied = _gate_tool(
        "desktop_act",
        {"action": "click", "ref": "@s1:e1", "app": "demo"},
        definition=_def(desktop_control=False),
    )
    assert denied and "desktop_control" in denied


def test_per_agent_allowlist_narrows_observation():
    definition = _def(desktop_allowed_apps=["calculator"])
    assert (
        _gate_tool("desktop_snapshot", {"app": "gnome-calculator"}, definition=definition) is None
    )
    denied = _gate_tool("desktop_snapshot", {"app": "firefox"}, definition=definition)
    assert denied and "desktop_allowed_apps" in denied


def test_definition_less_runs_cannot_use_desktop_tools():
    denied = _gate_tool("desktop_status", {}, definition=None)
    assert denied and "desktop_access" in denied


def test_policy_is_still_user_approved_in_semi_autonomy():
    prompts = []

    def approve(payload):
        prompts.append(payload)
        return {"approved": True}

    definition = _def(autonomy_level="semi")
    assert (
        _gate_tool(
            "desktop_act",
            {"action": "click", "ref": "@s1:e1", "app": "demo"},
            definition=definition,
            approval_provider=approve,
        )
        is None
    )
    assert prompts and prompts[0]["tool"] == "desktop_act"


def test_app_allowlist_normalizes_desktop_ids():
    assert _desktop_app_allowed("org.gnome.Calculator", ["calculator"])
    assert _desktop_app_allowed("gnome-calculator", ["org.gnome.Calculator"])
    assert not _desktop_app_allowed("firefox", ["calculator"])


def test_agent_definition_round_trips_desktop_flags():
    definition = AgentDefinition.new(
        "desktop-copilot",
        tool_pack="desktop",
        desktop_access=True,
        desktop_control=True,
        desktop_allowed_apps=["calculator", "gnome-text-editor"],
    )
    restored = AgentDefinition.from_dict(definition.to_dict())
    assert restored.desktop_access is True
    assert restored.desktop_control is True
    assert restored.desktop_allowed_apps == ["calculator", "gnome-text-editor"]
    assert validate_definition(restored) is None


def test_control_implies_access_and_validation_catches_bad_legacy_data():
    definition = AgentDefinition.new("x", desktop_control=True)
    assert definition.desktop_access is True
    # A definition written before this feature has both flags false.
    legacy = AgentDefinition.from_dict({"name": "old"})
    assert legacy.desktop_access is False
    assert legacy.desktop_control is False
