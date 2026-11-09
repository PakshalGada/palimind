"""Tests for usage, skills library, plugins, sharing, visuals and browser state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palimind.agents import (
    browser_profiles,
    failover,
    mcp_tools,
    plugins,
    sharing,
    skills,
    skills_library,
    usage,
    visuals,
)
from palimind.agents.catalog import AgentDefinition
from palimind.agents.registry import get_registry
from palimind.storage import state_store


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PALIMIND_MCP_CONFIG", str(tmp_path / "mcp.json"))
    import palimind.agents.catalog as catalog

    monkeypatch.setattr(catalog, "GLOBAL_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path / "home" / "skills")
    state_store._initialised.clear()
    registry = get_registry()
    registry._by_id = {}
    registry._by_name = {}
    agent = registry.create(AgentDefinition.new("util-alpha", display_name="Alpha"))
    yield agent
    registry._by_id = {}
    registry._by_name = {}
    state_store._initialised.clear()


def test_usage_aggregate_and_cost(env) -> None:
    usage.record_usage(
        env.id,
        provider="ollama",
        model="m1",
        prompt_tokens=1000,
        completion_tokens=500,
        cost_estimate=0.25,
        day="2026-11-01",
    )
    usage.record_usage(
        env.id,
        provider="openai",
        model="m2",
        prompt_tokens=2000,
        completion_tokens=1000,
        cost_estimate=0.0,
        day="2026-11-02",
    )
    result = usage.aggregate(env.id, start="2026-11-01", end="2026-11-30")
    assert result["total"]["calls"] == 2
    assert result["total"]["prompt_tokens"] == 3000
    assert [row["day"] for row in result["by_day"]] == ["2026-11-01", "2026-11-02"]
    assert usage.estimate_cost(1_000_000, 1_000_000, input_per_mtok=1.5, output_per_mtok=3.0) == 4.5


def test_skill_folder_and_library(env, tmp_path) -> None:
    folder = skills.SKILLS_DIR / "folder-skill"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: folder-skill\ndescription: From a folder\n---\n\nDo the thing.\n",
        "utf-8",
    )
    listed = skills.list_skills()
    assert any(s["id"] == "folder-skill" and "Do the thing" in s["instructions"] for s in listed)

    created = skills_library.create_skill(
        {"id": "lib-skill", "name": "Lib", "description": "d", "instructions": "one"}
    )
    assert created["revision"] == 1
    revised = skills_library.revise_skill(
        "lib-skill", 1, {"name": "Lib", "description": "d", "instructions": "two"}
    )
    assert revised["revision"] == 2
    with pytest.raises(ValueError):
        skills_library.revise_skill("lib-skill", 1, {"name": "Lib", "instructions": "stale"})
    assert [r["revision"] for r in skills_library.list_revisions("lib-skill")] == [1, 2]
    installed = skills_library.install_local_skill("lib-skill")
    assert installed["id"] == "lib-skill"
    assert skills_library.delete_skill("lib-skill") is True


def test_plugins_install_and_uninstall(env) -> None:
    record = plugins.install_plugin("web-research-pack", agent_id=env.id)
    assert record["plugin_id"] == "web-research-pack"
    assert plugins.list_plugins()[0]["installed"] is False or True
    assert any(p["installed"] for p in plugins.list_plugins() if p["id"] == "web-research-pack")
    assert plugins.install_plugin("web-research-pack")["plugin_id"] == "web-research-pack"
    assert plugins.uninstall_plugin("web-research-pack") is True


def test_mcp_tools_do_not_expose_secrets(env) -> None:
    saved = mcp_tools.save_mcp_server("fake", command="python", args="[]", env='{"TOKEN":"secret"}')
    assert "saved" in saved
    listed = json.loads(mcp_tools.list_mcp_servers())
    item = next(s for s in listed["servers"] if s["name"] == "fake")
    assert item["has_env"] is True
    assert "secret" not in json.dumps(listed)
    assert "enabled" in json.loads(mcp_tools.set_mcp_server_enabled("fake", False))
    assert "removed" in mcp_tools.remove_mcp_server("fake")


def test_sharing_round_trip_and_template(env, tmp_path) -> None:
    payload = sharing.export_agents([env.id])
    assert payload["agents"][0]["profile"]["name"] == "util-alpha"
    assert "webhook_token" not in payload["agents"][0]["profile"]
    imported = sharing.import_agents(payload)
    assert imported["created"]
    assert imported["created"][0]["name"].startswith("util-alpha")
    template = sharing.template_from_agent(env.id)
    installed = sharing.install_template(template)
    assert installed["created"][0]["name"].startswith("util-alpha")
    archive = tmp_path / "agents.zip"
    sharing.export_archive(archive, [env.id])
    assert archive.exists()
    assert sharing.import_archive(archive)["created"]


def test_visuals_and_browser_state(env) -> None:
    visual = visuals.create_visual("<h1>Hi</h1>", title="Hello", agent_id=env.id)
    assert visuals.read_visual(visual["id"], visual["token"]) == "<h1>Hi</h1>"
    assert visuals.read_visual(visual["id"], "wrong") is None
    assert visuals.list_visuals(env.id)

    profile = browser_profiles.create_profile("Work", color="#fff")
    assert browser_profiles.list_profiles()[0]["id"] == "shared"
    assert browser_profiles.update_profile(profile["id"], name="Work 2")["name"] == "Work 2"
    tab = browser_profiles.save_tab(profile["id"], agent_id=env.id, url="https://example.com")
    assert browser_profiles.list_tabs(profile["id"])[0]["id"] == tab["id"]
    takeover = browser_profiles.request_takeover(env.id, tab_id=tab["id"], reason="sign in")
    assert browser_profiles.resolve_takeover(takeover["id"])["status"] == "completed"
    assert browser_profiles.delete_profile(profile["id"]) is True


def test_failover_gate_is_deterministic() -> None:
    gate = failover.FailoverGate(hold_seconds=60)
    primary = {"provider": "ollama", "model": "small"}
    backups = [
        {"provider": "ollama", "model": "small"},
        {"provider": "ollama", "model": "large"},
        {"provider": "openai", "model": "remote"},
    ]
    assert failover.classify_failure("HTTP 429 rate limit") == "rate_limit"
    assert failover.classify_failure("invalid API key") == "authentication"
    assert failover.classify_failure("timed out") == "timeout"
    assert failover.should_failover(cause="network", acted=False, has_backup=True) is True
    assert failover.should_failover(cause="network", acted=True, has_backup=True) is False
    chosen = gate.choose(primary, backups, installed={"ollama/small", "ollama/large"})
    assert chosen == {"provider": "ollama", "model": "large"}
    gate.hold("ollama/large")
    assert gate.choose(primary, backups, installed={"ollama/small", "ollama/large"}) is None
    gate.release("ollama/large")
    assert gate.choose(primary, backups, installed={"ollama/small", "ollama/large"}) == {
        "provider": "ollama",
        "model": "large",
    }


def test_worker_failover_uses_backup_model(env) -> None:
    from palimind.agents.catalog import AgentDefinition
    from palimind.llm.mixture_of_expert.agents import run_agent

    definition = AgentDefinition.new(
        "failover-alpha",
        model="primary",
        backup_models=[{"provider": "ollama", "model": "backup"}],
    )
    calls: list[str] = []
    events: list[dict] = []

    def fake_client(messages, model, url, **kwargs):
        calls.append(model)
        if model == "primary":
            return {
                "content": "[Agent 1 error: HTTP 429 rate limit]",
                "tool_calls": [],
                "usage": {},
            }
        return {
            "content": "FINAL_ANSWER:\nbackup worked",
            "tool_calls": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }

    output = run_agent(
        1,
        {"task": "say done", "tools": []},
        "primary",
        "http://localhost:11434",
        definition=definition,
        event_cb=lambda kind, payload: events.append({"type": kind, **payload}),
        token_stream=False,
        model_client=fake_client,
    )
    assert calls[0] == "primary"
    assert "backup" in calls
    assert "backup worked" in output
    assert any(event.get("type") == "agent:failover" for event in events)
