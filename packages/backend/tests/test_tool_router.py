"""Tests for relevance-based tool routing and the tool_search meta-tool."""

from __future__ import annotations

import json

from palimind.agents.tool_router import score_tools, select_tools

REGISTRY = {
    "web_search": {"description": "Search the web", "parameters": {"query": "q"}},
    "fetch_url": {"description": "Fetch a URL", "parameters": {"url": "u"}},
    "read_file": {"description": "Read a workspace file", "parameters": {"path": "p"}},
    "write_file": {"description": "Write a workspace file", "parameters": {"path": "p"}},
    "run_tests": {"description": "Run the project test suite", "parameters": {}},
    "chart_generate": {"description": "Generate a chart from data", "parameters": {}},
    "git_diff": {"description": "Show git diff", "parameters": {}},
    "summarize": {"description": "Summarize text", "parameters": {"text": "t"}},
    "tool_search": {"description": "Find tools", "parameters": {"query": "q"}},
    "document_search": {"description": "Search indexed documents", "parameters": {"query": "q"}},
    "memory_search": {"description": "Search memory", "parameters": {"query": "q"}},
    "list_files": {"description": "List files", "parameters": {"path": "p"}},
    "grep_files": {"description": "Grep files", "parameters": {"pattern": "p"}},
    "delegate": {"description": "Delegate a task", "parameters": {"task": "t"}},
}


def test_explicit_tool_mention_ranks_first() -> None:
    scored = score_tools("Please use run_tests on the repo", list(REGISTRY), REGISTRY)
    assert scored[0][0] == "run_tests"


def test_family_hint_pulls_in_related_tool() -> None:
    picked = select_tools("make a chart of revenue", list(REGISTRY), REGISTRY, top_k=12)
    assert "chart_generate" in picked


def test_core_tools_and_tool_search_are_visible() -> None:
    picked = select_tools("hello", list(REGISTRY), REGISTRY, top_k=5)
    assert "tool_search" in picked
    assert "read_file" in picked
    assert len(picked) <= 5


def test_pinned_tool_is_always_included() -> None:
    picked = select_tools("unrelated words", list(REGISTRY), REGISTRY, top_k=2, pinned=["git_diff"])
    assert "git_diff" in picked


def test_write_tools_are_not_forced_by_core() -> None:
    picked = select_tools("just chat", list(REGISTRY), REGISTRY, top_k=12)
    assert "write_file" not in picked or "write" in "just chat"


def test_tool_search_returns_json_and_finds_matching_tool() -> None:
    from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, tool_search

    TOOL_REGISTRY["_router_probe"] = {
        "fn": lambda: "ok",
        "description": "Render a spreadsheet into a chart image",
        "parameters": {},
        "meta": {"tier": 1, "requires_approval": False},
    }
    try:
        raw = tool_search("chart spreadsheet", limit=5)
        items = json.loads(raw)
        names = [item["name"] for item in items]
        assert "_router_probe" in names
        assert all("parameters" in item for item in items)
    finally:
        TOOL_REGISTRY.pop("_router_probe", None)
