"""Tests for the in-app agent tools registry and sandbox."""

from __future__ import annotations

import asyncio

import pytest

from palimind.agents.tools import get_tool, list_tools
from palimind.agents.tools.base import ToolContext
from palimind.agents.tools.sandbox import clamp_output

EXPECTED_TOOLS = {
    "arxiv-search",
    "browse-url",
    "csv-query",
    "knowledge-graph",
    "mqtt",
    "python-exec",
    "rss-fetch",
    "shell-exec",
    "sqlite-query",
    "web-search",
}


def test_all_builtin_tools_register() -> None:
    names = {t["name"] for t in list_tools()}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


def test_manifests_have_permissions_and_timeout() -> None:
    for entry in list_tools():
        assert isinstance(entry["timeout_s"], int) and entry["timeout_s"] > 0
        assert isinstance(entry["permissions"], list)


def test_python_exec_runs_code_in_sandbox() -> None:
    tool = get_tool("python-exec")
    result = asyncio.run(tool.run(ToolContext(), code="print(21 * 2)"))
    assert result.ok
    assert "42" in result.output


def test_python_exec_reports_errors() -> None:
    tool = get_tool("python-exec")
    result = asyncio.run(tool.run(ToolContext(), code="raise ValueError('boom')"))
    assert not result.ok
    assert "boom" in (result.error or "")


def test_clamp_output_truncates() -> None:
    assert clamp_output("x" * 10, limit=5).endswith("[output truncated at 5 chars]")
    assert clamp_output("short", limit=10) == "short"


@pytest.mark.integration
def test_web_search_live() -> None:
    tool = get_tool("web-search")
    result = asyncio.run(tool.run(ToolContext(), query="palimind", max_results=1))
    assert result.ok or "not installed" in result.output.lower()
