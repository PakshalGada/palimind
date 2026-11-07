"""Regression tests for the onboarding/settings v2 model."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from palimind.agents import lifecycle, scope
from palimind.agents import runtime as rt
from palimind.agents.catalog import AgentDefinition, validate_definition


def test_display_name_and_autonomy_migration() -> None:
    defn = AgentDefinition.from_dict(
        {"name": "legacy", "title": "Legacy Title", "human_in_loop_threshold": 0.0}
    )
    assert defn.display_name == "Legacy Title"
    assert defn.autonomy_level == "off"
    assert defn.knowledge_scope["mode"] == "all"

    defn = AgentDefinition.from_dict(
        {"name": "legacy-2", "human_in_loop_threshold": 0.5}
    )
    assert defn.autonomy_level == "semi"


def test_memory_mode_migration() -> None:
    off = AgentDefinition.from_dict({"name": "no-mem", "memory_scope": "none"})
    assert off.memory_mode == "off"

    private = AgentDefinition.from_dict({"name": "mem", "memory_scope": "field"})
    assert private.memory_mode == "private"

    # Old "shared" meant per-agent global memory; migrate it to private.
    old_shared = AgentDefinition.from_dict({"name": "old-shared", "memory_mode": "shared"})
    assert old_shared.memory_mode == "private"

    new_shared = AgentDefinition.from_dict(
        {"name": "new-shared", "schema_version": 2, "memory_mode": "shared"}
    )
    assert new_shared.memory_mode == "shared"


def test_validation_cron_and_bounds() -> None:
    bad_cron = AgentDefinition.new(
        "bad-cron", run_mode="scheduled", schedule="99 99 * * *"
    )
    assert validate_definition(bad_cron) is not None

    good_cron = AgentDefinition.new(
        "good-cron", run_mode="scheduled", schedule="*/15 * * * *"
    )
    assert validate_definition(good_cron) is None

    bad_concurrency = AgentDefinition.new("too-many", max_concurrent_runs=0)
    assert validate_definition(bad_concurrency) is not None


def test_scope_resolution(tmp_path: Path, monkeypatch) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    c = tmp_path / "c"
    for path in (a, b, c):
        path.mkdir()
    monkeypatch.setattr(scope, "configured_fields", lambda: [a, b, c])
    monkeypatch.setattr(scope, "GLOBAL_AGENTS_DIR", tmp_path / "agents")

    all_scope = AgentDefinition.new(
        "all-scope",
        knowledge_scope={"mode": "all", "primary_field": str(a), "extra_fields": []},
    )
    primary, extras = scope.resolve_scope(all_scope)
    assert primary == a
    assert set(extras) == {b, c}

    project = AgentDefinition.new(
        "project-scope",
        knowledge_scope={
            "mode": "project",
            "primary_field": str(b),
            "extra_fields": [str(c)],
        },
    )
    primary, extras = scope.resolve_scope(project)
    assert primary == b
    assert extras == [c]

    personal = AgentDefinition.new(
        "personal-scope",
        knowledge_scope={"mode": "personal", "primary_field": "", "extra_fields": []},
    )
    primary, extras = scope.resolve_scope(personal)
    assert primary is not None
    assert "personal-scope" in str(primary) or personal.id in str(primary)
    assert extras == []


def test_memory_store_resolution(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(scope, "GLOBAL_AGENTS_DIR", tmp_path / "agents")
    kb = tmp_path / "kb"
    kb.mkdir()
    monkeypatch.setattr(scope, "configured_fields", lambda: [kb])

    private = AgentDefinition.new("private-mem", memory_mode="private")
    assert scope.memory_file_for(private).name == f"{private.id}.json"

    shared = AgentDefinition.new("shared-mem", memory_mode="shared")
    assert scope.memory_file_for(shared).name == "_shared.json"

    project = AgentDefinition.new(
        "project-mem",
        memory_mode="project",
        knowledge_scope={"mode": "project", "primary_field": str(kb), "extra_fields": []},
    )
    path = scope.memory_file_for(project)
    assert path is not None
    assert str(kb) in str(path)

    off = AgentDefinition.new("off-mem", memory_mode="off")
    assert scope.memory_file_for(off) is None


def test_autonomy_gate_matrix() -> None:
    from palimind.llm.mixture_of_expert.agents import _gate_tool

    calls: list[str] = []

    def provider(pending: dict) -> dict:
        calls.append(str(pending.get("tool")))
        return {"approved": True}

    base = dict(
        write_access=True,
        shell_access=True,
        tier_policy="all",
    )

    off = AgentDefinition.new("gate-off", autonomy_level="off", **base)
    assert _gate_tool("write_file", {}, definition=off, approval_provider=provider) is None
    assert calls == []

    supervised = AgentDefinition.new("gate-sup", autonomy_level="supervised", **base)
    assert _gate_tool("read_file", {}, definition=supervised, approval_provider=provider) is None
    assert calls == ["read_file"]

    semi = AgentDefinition.new("gate-semi", autonomy_level="semi", **base)
    calls.clear()
    assert _gate_tool("read_file", {}, definition=semi, approval_provider=provider) is None
    assert calls == []
    assert _gate_tool("write_file", {}, definition=semi, approval_provider=provider) is None
    assert calls == ["write_file"]

    high = AgentDefinition.new("gate-high", autonomy_level="high", **base)
    calls.clear()
    assert _gate_tool("write_file", {}, definition=high, approval_provider=provider) is None
    assert calls == []
    assert _gate_tool("run_shell", {}, definition=high, approval_provider=provider) is None
    assert calls == ["run_shell"]


def test_concurrent_run_registry() -> None:
    async def scenario() -> None:
        agent_id = "concurrency-test"
        await rt.register_running(agent_id, "run-1", max_concurrent=2)
        await rt.register_running(agent_id, "run-2", max_concurrent=2)
        assert rt.running_count(agent_id) == 2
        with pytest.raises(rt.AgentBusyError):
            await rt.register_running(agent_id, "run-3", max_concurrent=2)

        await rt.unregister_running(agent_id, "run-1")
        assert rt.running_count(agent_id) == 1
        assert rt.is_running(agent_id)
        await rt.unregister_running(agent_id, "run-2")
        assert not rt.is_running(agent_id)

    asyncio.run(scenario())


def test_purge_agent_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lifecycle, "GLOBAL_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(scope, "GLOBAL_AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(scope, "configured_fields", lambda: [])
    agent_id = "purge-me"
    session_root = tmp_path / "agents" / agent_id
    session_root.mkdir(parents=True)
    (session_root / ".palimind").mkdir()
    memory = tmp_path / "agents" / "memory"
    memory.mkdir(parents=True)
    (memory / f"{agent_id}.json").write_text("[]", "utf-8")

    lifecycle.purge_agent_data(agent_id)

    assert not session_root.exists()
    assert not (memory / f"{agent_id}.json").exists()
