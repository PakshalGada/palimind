"""Tests for agent skills, webhook tokens and the run-trace store."""

from __future__ import annotations

import json
from pathlib import Path

from palimind.agents import runtime as rt
from palimind.agents import skills as sk
from palimind.agents.catalog import AgentCatalog, AgentDefinition


def test_builtin_skills_present() -> None:
    ids = {s["id"] for s in sk.list_skills()}
    assert {"web-research", "deep-analysis", "code-review", "fact-check"}.issubset(ids)


def test_skill_tools_union_deduplicates() -> None:
    tools = sk.skill_tools(["web-research", "code-review"])
    assert "web_search" in tools
    assert "read_file" in tools
    assert len(tools) == len(set(tools))


def test_skill_instructions_block() -> None:
    text = sk.skill_instructions(["concise-writer"])
    assert "[SKILLS]" in text
    assert "Concise writer" in text


def test_unknown_skill_ignored() -> None:
    assert sk.skill_tools(["does-not-exist"]) == []
    assert sk.skill_instructions(["does-not-exist"]) == ""


def test_user_skill_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sk, "SKILLS_DIR", tmp_path)
    (tmp_path / "custom.json").write_text(
        json.dumps(
            {
                "id": "custom",
                "name": "Custom",
                "description": "d",
                "tools": ["summarize"],
                "instructions": "Always X",
            }
        ),
        "utf-8",
    )
    skill = sk.get_skill("custom")
    assert skill is not None and skill["builtin"] is False
    assert sk.skill_tools(["custom"]) == ["summarize"]
    assert "Always X" in sk.skill_instructions(["custom"])


def test_webhook_token_and_skills_roundtrip() -> None:
    defn = AgentDefinition.new("hooked", skills=["web-research"])
    assert defn.webhook_token
    restored = AgentDefinition.from_dict(defn.to_dict())
    assert restored.skills == ["web-research"]
    assert restored.webhook_token == defn.webhook_token


def test_catalog_lookup_by_webhook_token() -> None:
    defn = AgentDefinition.new("a", webhook_token="tok123")
    cat = AgentCatalog()
    cat._by_name = {defn.name: defn}
    cat._by_id = {defn.id: defn}
    assert cat.get_by_webhook_token("tok123") is defn
    assert cat.get_by_webhook_token("wrong") is None
    assert cat.get_by_webhook_token("") is None


def test_record_and_get_run_with_usage_and_trace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rt, "_runs_dir", lambda: tmp_path)
    rt.record_run(
        "agent-1",
        "run-1",
        "input",
        "output",
        "success",
        1.25,
        usage={"prompt_tokens": 3, "completion_tokens": 4},
        trace=[{"type": "agent:thought", "text": "hi"}],
    )
    record = rt.get_run("agent-1", "run-1")
    assert record is not None
    assert record["usage"] == {"prompt_tokens": 3, "completion_tokens": 4}
    assert record["trace"] == [{"type": "agent:thought", "text": "hi"}]
    assert rt.get_run("agent-1", "missing") is None
