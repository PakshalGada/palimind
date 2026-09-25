"""Tests for the research/knowledge tools (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.agents.tools.research import tool as rt
from palimind.llm.mixture_of_expert.tools import (
    TOOL_REGISTRY,
    _register_plugin_tools,
    set_tool_context,
)

RESEARCH_TOOLS = [
    "semantic_scholar_search",
    "openalex_search",
    "crossref_search",
    "pubmed_search",
    "wikipedia_search",
    "wikipedia_page",
    "news_search",
    "hn_search",
    "github_search",
    "stackexchange_search",
    "open_meteo",
    "sec_edgar_search",
    "pdf_read",
]


def test_research_tools_registered_as_safe() -> None:
    _register_plugin_tools()
    for name in RESEARCH_TOOLS:
        assert name in TOOL_REGISTRY, f"{name} not registered"
        assert TOOL_REGISTRY[name]["meta"]["tier"] == 1
        assert TOOL_REGISTRY[name]["meta"]["requires_approval"] is False


def test_empty_query_errors() -> None:
    assert "query is required" in rt.semantic_scholar_search("")
    assert "query is required" in rt.news_search("   ")
    assert "query is required" in rt.github_search("")


def test_wikipedia_page_requires_title() -> None:
    assert "title is required" in rt.wikipedia_page("")


def test_open_meteo_validates_numbers() -> None:
    assert rt.open_meteo("north", "east").startswith("Error")


def test_pdf_read_extracts_text(tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), "Hello PaliMind PDF")
        pdf_path = tmp_path / "sample.pdf"
        doc.save(pdf_path)
    finally:
        doc.close()

    set_tool_context(tmp_path)
    try:
        out = rt.pdf_read("sample.pdf")
    finally:
        set_tool_context(None)
    assert "Hello PaliMind PDF" in out


def test_pdf_read_denies_outside_workspace(tmp_path: Path) -> None:
    set_tool_context(tmp_path)
    try:
        out = rt.pdf_read("/etc/hosts")
    finally:
        set_tool_context(None)
    assert "access denied" in out
