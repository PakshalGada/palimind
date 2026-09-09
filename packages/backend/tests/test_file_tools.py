"""Tests for Phase 3 file tools: registry, sandboxed search, patching, gating."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from palimind.llm.mixture_of_expert.agents import _gate_tool
from palimind.llm.mixture_of_expert.tools import (
    TOOL_REGISTRY,
    glob_files,
    grep_files,
    search_replace,
    set_tool_context,
    write_file,
)


def test_plugin_tools_registered() -> None:
    from palimind.llm.mixture_of_expert.tools import _register_plugin_tools

    _register_plugin_tools()
    for name in ("run_shell", "csv_query", "sqlite_query", "query_graph"):
        assert name in TOOL_REGISTRY
        assert "meta" in TOOL_REGISTRY[name]
    assert TOOL_REGISTRY["run_shell"]["meta"]["tier"] == 2
    assert TOOL_REGISTRY["run_shell"]["meta"]["requires_approval"] is True
    assert TOOL_REGISTRY["grep_files"]["meta"]["tier"] == 1
    assert TOOL_REGISTRY["search_replace"]["meta"]["tier"] == 2


def test_write_and_search_replace_sandboxed(tmp_path: Path) -> None:
    set_tool_context(tmp_path)
    try:
        write_file("a.py", "x = 1\ny = 2\nx = 3\n")
        res = search_replace("a.py", "x = ", "z = ", count=1)
        assert "Replaced 1 of 2" in res
        assert (tmp_path / "a.py").read_text() == "z = 1\ny = 2\nx = 3\n"

        # Second occurrence untouched by default
        search_replace("a.py", "x = ", "z = ", count=1)
        assert (tmp_path / "a.py").read_text() == "z = 1\ny = 2\nz = 3\n"

        # Outside the workspace is denied
        out = search_replace("/etc/hosts", "a", "b")
        assert "access denied" in out
    finally:
        set_tool_context(None)


def test_grep_and_glob(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("hello world\nfoo bar\n", "utf-8")
    (tmp_path / "b.py").write_text("print('hi')\n", "utf-8")

    set_tool_context(tmp_path)
    try:
        out = grep_files("hello", path=".")
        assert "docs/a.md:1" in out

        files = glob_files("**/*.py", path=".")
        assert "b.py" in files

        # Outside workspace denied
        assert "access denied" in grep_files("x", path="/etc")
    finally:
        set_tool_context(None)


def test_search_replace_missing_old_string(tmp_path: Path) -> None:
    set_tool_context(tmp_path)
    try:
        write_file("f.txt", "abc")
        out = search_replace("f.txt", "zzz", "q")
        assert "not found" in out
    finally:
        set_tool_context(None)


def _defn(tier_policy="tier1+2", write_access=True, shell_access=True, threshold=0.0):
    return SimpleNamespace(
        tier_policy=tier_policy,
        write_access=write_access,
        shell_access=shell_access,
        human_in_loop_threshold=threshold,
    )


def test_gate_tool_enforces_tier_policy() -> None:
    from palimind.llm.mixture_of_expert.tools import _register_plugin_tools

    _register_plugin_tools()
    d1 = _defn(tier_policy="tier1")
    denial = _gate_tool("write_file", {}, definition=d1)
    assert denial and "tier" in denial

    d2 = _defn(tier_policy="tier1+2")
    assert _gate_tool("write_file", {}, definition=d2) is None


def test_gate_tool_enforces_access_flags() -> None:
    assert "write_access" in _gate_tool(
        "write_file", {}, definition=_defn(write_access=False)
    )
    assert "shell_access" in _gate_tool(
        "run_shell", {"command": "ls"}, definition=_defn(shell_access=False)
    )


def test_gate_tool_moe_denies_mutations_without_approval() -> None:
    denial = _gate_tool("write_file", {}, definition=None, approval_provider=None)
    assert denial and "human approval" in denial

    denial2 = _gate_tool(
        "run_shell", {"command": "ls"}, definition=None, approval_provider=None
    )
    assert denial2 is not None

    # Isolated compute stays allowed for MoE
    assert _gate_tool("run_python", {"code": "print(1)"}, definition=None) is None


def test_gate_tool_moe_allows_with_approval() -> None:
    provider = lambda pending: {"approved": True, "correction": ""}  # noqa: E731
    assert _gate_tool(
        "write_file", {"path": "x", "content": "y"}, definition=None,
        approval_provider=provider,
    ) is None
    rejector = lambda pending: {"approved": False, "correction": "no"}  # noqa: E731
    denial = _gate_tool(
        "write_file", {"path": "x"}, definition=None, approval_provider=rejector
    )
    assert denial and "rejected" in denial
