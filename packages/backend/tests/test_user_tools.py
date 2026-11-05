"""Tests for drop-in user tools in ~/.palimind/tools."""

from __future__ import annotations

import json
from pathlib import Path

from palimind.agents.tools import registry
from palimind.agents.tools.base import ToolContext


def _write_tool(base: Path, name: str = "echo-tool") -> Path:
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tool.json").write_text(
        json.dumps(
            {
                "name": "echo_tool",
                "version": "1.0.0",
                "description": "Echo text back",
                "entrypoint": "tool.py",
                "function": "run",
                "permissions": [],
                "timeout_s": 5,
                "parameters": {
                    "text": {"type": "string", "description": "Text to echo"},
                },
                "tier": 1,
                "requires_approval": False,
                "parallel_safe": True,
                "idempotent": True,
            }
        ),
        encoding="utf-8",
    )
    (folder / "tool.py").write_text(
        "def run(text: str) -> str:\n    return f'echo:{text}'\n",
        encoding="utf-8",
    )
    return folder


def test_discovers_and_calls_user_tool(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registry, "USER_TOOLS_DIR", tmp_path)
    _write_tool(tmp_path)
    tools = registry.discover_user_tools()
    assert "echo_tool" in tools
    tool = tools["echo_tool"]
    assert tool.source == "user"
    assert tool.spec().to_schema()["properties"]["text"]["type"] == "string"

    import asyncio

    result = asyncio.run(tool.run(ToolContext(workspace_root=tmp_path), text="hi"))
    assert result.ok and result.output == "echo:hi"


def test_user_tool_merges_into_live_registry(monkeypatch, tmp_path: Path) -> None:
    from palimind.llm.mixture_of_expert import tools as live

    monkeypatch.setattr(registry, "USER_TOOLS_DIR", tmp_path)
    _write_tool(tmp_path)
    try:
        live._register_plugin_tools(force=True)
        assert "echo_tool" in live.TOOL_REGISTRY
        entry = live.TOOL_REGISTRY["echo_tool"]
        assert entry["source"] == "user"
        assert entry["parallel_safe"] is True
        assert live.call_tool("echo_tool", text="hi") == "echo:hi"
    finally:
        live.TOOL_REGISTRY.pop("echo_tool", None)
        live._user_tool_names.discard("echo_tool")


def test_removed_user_tool_disappears_on_reload(monkeypatch, tmp_path: Path) -> None:
    from palimind.llm.mixture_of_expert import tools as live

    monkeypatch.setattr(registry, "USER_TOOLS_DIR", tmp_path)
    folder = _write_tool(tmp_path)
    try:
        live._register_plugin_tools(force=True)
        assert "echo_tool" in live.TOOL_REGISTRY
        (folder / "tool.json").unlink()
        (folder / "tool.py").unlink()
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
        live._register_plugin_tools(force=True)
        assert "echo_tool" not in live.TOOL_REGISTRY
    finally:
        live.TOOL_REGISTRY.pop("echo_tool", None)
        live._user_tool_names.discard("echo_tool")


def test_builtin_wins_on_name_collision(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registry, "USER_TOOLS_DIR", tmp_path)
    _write_tool(tmp_path, "collision")
    # Rename the user tool to an existing built-in id.
    manifest = tmp_path / "collision" / "tool.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["name"] = "web_search"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    tools = registry.discover_user_tools()
    # discover_user_tools itself has no built-in context; the collision rule is
    # enforced when merging into the live registry.
    assert "web_search" in tools
    from palimind.llm.mixture_of_expert import tools as live

    original = live.TOOL_REGISTRY["web_search"]
    try:
        live._register_plugin_tools(force=True)
        assert live.TOOL_REGISTRY["web_search"] is original
    finally:
        live._user_tool_names.discard("web_search")
