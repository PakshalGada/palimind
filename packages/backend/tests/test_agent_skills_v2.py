"""Tests for the Phase 4.3 skill enhancements: YAML, commands, compose, market."""

from __future__ import annotations

import json
from pathlib import Path

from palimind.agents import skills as sk


def test_validate_skill_accepts_and_rejects() -> None:
    assert sk.validate_skill({"id": "ok-skill", "name": "OK", "tools": ["read_file"]}) is None
    assert sk.validate_skill({"id": "bad id", "name": "x"}) is not None
    assert sk.validate_skill({"id": "x", "name": ""}) is not None
    assert sk.validate_skill({"id": "x", "name": "x", "tools": ["nope_not_real"]}) is not None
    assert sk.validate_skill({"id": "x", "name": "x", "command": "not-a-command"}) is not None
    assert sk.validate_skill({"id": "x", "name": "x", "command": "/good"}) is None


def test_commands_and_resolve() -> None:
    commands = {c["command"] for c in sk.skill_commands()}
    assert "/research" in commands and "/review" in commands
    resolved = sk.resolve_command("/review src/app.py")
    assert resolved is not None
    assert resolved["skill"]["id"] == "code-review"
    assert resolved["input"] == "src/app.py"
    assert sk.resolve_command("hello") is None
    assert sk.resolve_command("/nope") is None


def test_yaml_skill_loading(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sk, "SKILLS_DIR", tmp_path)
    (tmp_path / "y.yaml").write_text(
        "id: yaml-skill\nname: YAML Skill\ndescription: from yaml\ntools:\n  - read_file\n"
        "instructions: Always do YAML.\n",
        "utf-8",
    )
    skill = sk.get_skill("yaml-skill")
    assert skill is not None and skill["name"] == "YAML Skill"
    assert skill["tools"] == ["read_file"]


def test_skill_composition(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sk, "SKILLS_DIR", tmp_path)
    (tmp_path / "base.json").write_text(
        json.dumps(
            {
                "id": "base",
                "name": "Base",
                "tools": ["read_file"],
                "instructions": "Base instruction.",
            }
        ),
        "utf-8",
    )
    (tmp_path / "child.json").write_text(
        json.dumps(
            {
                "id": "child",
                "name": "Child",
                "compose": ["base"],
                "tools": ["web_search"],
                "instructions": "Child instruction.",
            }
        ),
        "utf-8",
    )
    expanded = sk.expand_skill("child")
    assert set(expanded["tools"]) == {"read_file", "web_search"}
    assert "Base instruction." in expanded["instructions"]
    assert "Child instruction." in expanded["instructions"]


def test_composition_cycle_is_safe(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sk, "SKILLS_DIR", tmp_path)
    (tmp_path / "a.json").write_text(
        json.dumps({"id": "a", "name": "A", "compose": ["b"]}), "utf-8"
    )
    (tmp_path / "b.json").write_text(
        json.dumps({"id": "b", "name": "B", "compose": ["a"]}), "utf-8"
    )
    assert sk.expand_skill("a") is not None


def test_install_uninstall_and_marketplace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sk, "SKILLS_DIR", tmp_path)
    installed = sk.install_skill(
        {"id": "mine", "name": "Mine", "tools": ["read_file"], "instructions": "x"}
    )
    assert installed["source"] == "user"
    assert (tmp_path / "mine.json").exists()
    assert sk.uninstall_skill("mine") is True
    assert sk.uninstall_skill("web-research") is False  # built-in protected

    # Marketplace
    listed = sk.list_marketplace()
    assert any(s["id"] == "release-notes" for s in listed)
    market = sk.install_from_marketplace("release-notes")
    assert market["source"] == "marketplace"
    assert sk.get_skill("release-notes") is not None


def test_export_skill(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sk, "SKILLS_DIR", tmp_path)
    exported = sk.export_skill("web-research")
    assert exported is not None and exported["id"] == "web-research"
    assert exported["instructions"]
    assert sk.export_skill("missing") is None


def test_register_plugin_skill() -> None:
    skill = sk.register_plugin_skill({"id": "plugin-x", "name": "Plugin X", "tools": []})
    assert skill["source"] == "plugin"
    assert sk.get_skill("plugin-x") is not None
    # Clean up so the process-wide registry does not leak into other tests.
    sk._PLUGIN_SKILLS.pop("plugin-x", None)
