"""Web search quality + per-mode web augmentation (no live network)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from palimind.core import web_search
from palimind.llm import stream as llm_stream
from palimind.llm.mixture_of_expert import orchestrator

FORMATTED_SEARCH = """=== WEB SEARCH RESULTS FOR: 'quantum news' ===

Provider: ddg
Sources: 1

Source [1]: Quantum breakthrough
URL: https://example.com/quantum
Summary: Researchers report a new quantum result.
Page Content:
A detailed page about the quantum breakthrough.

=======================================
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    web_search._cache.clear()
    yield
    web_search._cache.clear()


def test_query_variants_strip_questions_and_add_year_for_fresh_queries() -> None:
    variants = web_search._build_query_variants("What is the latest news on quantum computing?")
    assert variants[0] == "What is the latest news on quantum computing?"
    assert "latest news on quantum computing" in variants
    assert any(str(web_search.time.gmtime().tm_year) in variant for variant in variants)
    assert len(variants) <= web_search.MAX_QUERY_VARIANTS


def test_results_are_ranked_by_query_relevance_and_domain_quality() -> None:
    results = web_search._dedupe_results(
        [
            {
                "title": "Unrelated social post",
                "url": "https://twitter.com/x/1",
                "snippet": "nothing useful",
            },
            {
                "title": "Quantum computing explained",
                "url": "https://example.edu/quantum",
                "snippet": "quantum computing research",
            },
            {
                "title": "Other",
                "url": "https://example.com/other",
                "snippet": "other",
            },
        ],
        2,
        "quantum computing",
    )
    assert results[0]["url"] == "https://example.edu/quantum"
    assert len(results) == 2
    assert all(item["url"] != "https://twitter.com/x/1" for item in results)


def test_perform_web_search_fetches_pages_in_parallel(monkeypatch) -> None:
    from palimind.core import search_providers as sp

    monkeypatch.setattr(
        sp.SearchRouter,
        "search_many",
        lambda self, queries, max_results=4: (
            [
                sp.SearchResult("A", "https://a.example/1", "quantum result"),
                sp.SearchResult("B", "https://b.example/2", "quantum result"),
            ],
            "ddg",
        ),
    )
    fetched: list[str] = []

    def fake_fetch(url: str) -> str:
        fetched.append(url)
        return f"content for {url}"

    monkeypatch.setattr(web_search, "_fetch_page_content", fake_fetch)
    out = web_search.perform_web_search("quantum computing", max_results=2, fetch_content=True)
    assert "Source [1]" in out
    assert "Page Content:" in out
    assert "content for https://a.example/1" in out
    assert len(fetched) == 2


def _sse_events(chunks: list[str]) -> list[dict]:
    return [json.loads(chunk[len("data: ") :]) for chunk in chunks if chunk.startswith("data: ")]


def test_default_llm_mode_searches_web_and_emits_citations(monkeypatch) -> None:
    calls: dict = {}

    def fake_search(query, max_results=4, fetch_content=True):
        calls["query"] = query
        return FORMATTED_SEARCH

    def fake_generate(**kwargs):
        calls["kwargs"] = kwargs
        return iter(["The quantum result is real [1]."])

    monkeypatch.setattr("palimind.core.web_search.perform_web_search", fake_search)
    monkeypatch.setattr(
        "palimind.generative.responder.generate_response_stream", fake_generate
    )

    async def main():
        response = await llm_stream.llm_mode_stream(
            "quantum news",
            None,
            None,
            None,
            None,
            "http://x",
            "model",
            Path("/nonexistent"),
            "true",
        )
        return [chunk async for chunk in response.body_iterator]

    events = _sse_events(asyncio.run(main()))
    assert calls["query"] == "quantum news"
    # The web results are injected into the model prompt.
    assert "WEB RESEARCH RESULTS" in calls["kwargs"]["query"]
    assert "https://example.com/quantum" in calls["kwargs"]["query"]
    assert any(event["type"] == "token" for event in events)
    calls_seen = [event for event in events if event["type"] == "agent:tool_call"]
    results_seen = [event for event in events if event["type"] == "agent:tool_result"]
    assert calls_seen and calls_seen[0]["tool"] == "web_search"
    assert results_seen and results_seen[0]["result"][0]["url"] == "https://example.com/quantum"
    citation = next(event for event in events if event["type"] == "citation_map")
    assert citation["sources"][0]["url"] == "https://example.com/quantum"
    assert events[-1]["type"] == "done"


def test_progress_events_stream_agent_tools_live() -> None:
    call = llm_stream._progress_event_to_sse(
        {"type": "agent:tool_call", "agent_id": 2, "tool": "fetch_url", "args": {"url": "x"}}
    )
    result = llm_stream._progress_event_to_sse(
        {"type": "agent:tool_result", "agent_id": 2, "tool": "fetch_url", "result": "ok"}
    )
    thought = llm_stream._progress_event_to_sse(
        {"type": "agent:thought", "agent_id": 2, "text": "Reading the page"}
    )
    assert json.loads(call[0][len("data: ") :])["type"] == "agent:tool_call"
    assert json.loads(result[0][len("data: ") :])["type"] == "agent:tool_result"
    assert json.loads(thought[0][len("data: ") :])["type"] == "agent_thinking"


def test_moe_force_web_skips_direct_path_and_adds_researcher(monkeypatch) -> None:
    calls: list[str] = []

    def fake_search(query, max_results=4, fetch_content=True):
        calls.append(query)
        return FORMATTED_SEARCH

    plan = json.dumps(
        [{"agent_id": 1, "label": "Analyst", "task": "answer", "tools": []}]
    )
    monkeypatch.setattr(
        orchestrator,
        "llm_chat_safe",
        lambda messages, model, url, *, error_prefix="[LLM error", **kw: {
            "content": plan,
            "tool_calls": [],
            "usage": {},
        },
    )
    monkeypatch.setattr(orchestrator, "MOE_VERIFY", False)
    monkeypatch.setattr(orchestrator, "MOE_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(orchestrator, "run_agent", lambda *a, **kw: "agent output")
    monkeypatch.setattr("palimind.core.web_search.perform_web_search", fake_search)

    result = asyncio.run(
        orchestrator.run_moe_pipeline(
            "hi",
            "http://x",
            "orch",
            "worker",
            num_workers=2,
            force_web=True,
        )
    )
    assert calls == ["hi"]
    assert result["route"]["needs_web"] is True
    assert any("web_search" in agent.get("tools", []) for agent in result["plan"])
