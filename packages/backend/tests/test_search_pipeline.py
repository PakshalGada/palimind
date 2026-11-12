"""Search pipeline: decomposition, fusion, evidence and stream wiring."""

from __future__ import annotations

import asyncio
import json

import palimind.core.web_search as web_search
import palimind.settings as settings
from palimind.core.search_pipeline import (
    SearchAspect,
    expand_aspect_queries,
    extract_evidence,
    fuse_candidates,
    normalize_plan,
    run_search_pipeline,
)
from palimind.generative.citation import Source


def _search_text(query: str, results: list[tuple[str, str, str]]) -> str:
    parts = [
        f"=== WEB SEARCH RESULTS FOR: '{query}' ===",
        "Provider: ddg",
        f"Sources: {len(results)}",
    ]
    for index, (title, url, summary) in enumerate(results, start=1):
        parts.extend([f"Source [{index}]: {title}", f"URL: {url}", f"Summary: {summary}"])
    parts.append("=" * 39)
    return "\n".join(parts)


def test_fallback_plan_covers_comparison_queries() -> None:
    intent, entities, freshness, aspects = normalize_plan(
        None, "best laptop for machine learning 2026", 3
    )
    assert intent == "comparison"
    assert freshness == "any"
    assert entities == []
    assert 2 <= len(aspects) <= 3
    assert aspects[0].queries
    assert any("compare" in aspect.question.lower() for aspect in aspects)


def test_normalize_plan_tolerates_fenced_and_partial_json() -> None:
    raw = (
        "```json\n"
        '{"intent": "news", "entities": ["Acme"], "freshness": "recent", '
        '"aspects": [{"title": "Funding", "question": "Did Acme raise?", '
        '"queries": ["acme funding"]}]}\n'
        "```"
    )
    data = json.loads(raw.split("```")[1].removeprefix("json\n"))
    intent, entities, freshness, aspects = normalize_plan(data, "Acme news", 4)
    assert (intent, entities, freshness) == ("news", ["Acme"], "recent")
    assert aspects[0].title == "Funding"
    assert aspects[0].queries == ["acme funding"]


def test_expand_aspect_queries_adds_source_scoped_variants() -> None:
    aspect = SearchAspect(
        id=1,
        title="Papers",
        question="What do papers say about retrieval augmented generation?",
        queries=["retrieval augmented generation"],
        source_types=["academic", "code"],
    )
    queries = expand_aspect_queries(aspect, "any", 6)
    assert any("site:arxiv.org" in query for query in queries)
    assert any("site:github.com" in query for query in queries)
    assert len(queries) <= 6


def test_fuse_dedupes_by_url_and_keeps_distinct_domains() -> None:
    entries = [
        ("q1", 0, Source(marker=1, title="One", url="https://a.example/x", snippet="gpu vram")),
        (
            "q2",
            0,
            Source(marker=1, title="One again", url="https://a.example/x", snippet="gpu vram"),
        ),
        (
            "q2",
            1,
            Source(marker=2, title="Two", url="https://b.example/y", snippet="gpu vram price"),
        ),
    ]
    selected = fuse_candidates(entries, "gpu vram price", 4, mmr=True)
    assert [source.url for source in selected] == ["https://a.example/x", "https://b.example/y"]
    assert [source.marker for source in selected] == [1, 2]
    assert all(source.score > 0 for source in selected)


def test_extract_evidence_spreads_across_sources() -> None:
    aspects = [SearchAspect(id=1, title="GPU", question="What GPU is needed?")]
    sources = [
        Source(
            marker=1,
            title="Alpha",
            url="https://a.example/x",
            content="A strong GPU with 16 GB of VRAM is needed for training. "
            "Memory bandwidth matters more than raw compute here. ",
        ),
        Source(
            marker=2,
            title="Beta",
            url="https://b.example/y",
            content="Reviewers recommend at least 16 GB of VRAM for local training. "
            "Cloud GPUs remain a cheaper option for occasional use. ",
        ),
    ]
    evidence = extract_evidence(aspects, sources, "GPU for training", per_aspect=3)
    assert len(evidence) >= 1
    assert {item.url for item in evidence} <= {source.url for source in sources}
    assert aspects[0].status == "done"
    assert aspects[0].evidence_count >= 1


def test_pipeline_emits_plan_queries_sources_and_prompt(monkeypatch) -> None:
    seen_queries: list[str] = []

    def fake_search(query: str, max_results: int = 5, fetch_content: bool = True) -> str:
        seen_queries.append(query)
        if "alpha" in query.lower():
            return _search_text(
                query,
                [
                    (
                        "Alpha",
                        "https://alpha.example/page",
                        "Alpha says 16 GB of VRAM is needed for machine learning laptops.",
                    )
                ],
            )
        return _search_text(
            query,
            [
                (
                    "Beta",
                    "https://beta.example/page",
                    "Beta says battery life matters for portable machine learning.",
                )
            ],
        )

    def fake_fetch(url: str) -> str:
        if "alpha" in url:
            return "A laptop needs 16 GB of VRAM for machine learning workloads. Memory bandwidth matters too."
        return "Battery life matters when training on a laptop away from power. A typical model costs 2000 USD."

    def fake_llm(messages, model, url, **kwargs):
        return {
            "content": json.dumps(
                {
                    "intent": "comparison",
                    "entities": ["laptop"],
                    "freshness": "recent",
                    "aspects": [
                        {
                            "title": "GPU and memory",
                            "question": "What GPU and VRAM do ML laptops need?",
                            "queries": ["alpha ml laptop gpu"],
                            "source_types": ["web"],
                        },
                        {
                            "title": "Price and battery",
                            "question": "What do ML laptops cost and how is battery life?",
                            "queries": ["beta ml laptop battery"],
                            "source_types": ["web"],
                        },
                    ],
                }
            ),
            "usage": {},
        }

    monkeypatch.setattr(web_search, "perform_web_search", fake_search)
    monkeypatch.setattr(web_search, "_fetch_page_content", fake_fetch)
    monkeypatch.setattr(settings, "SEARCH_SECOND_HOP", False)

    events: list[dict] = []

    async def main():
        async def on_event(event):
            events.append(event)

        return await run_search_pipeline(
            "best laptop for machine learning",
            ollama_url="http://x",
            model="m",
            depth="quick",
            on_event=on_event,
            llm_fn=fake_llm,
        )

    bundle = asyncio.run(main())
    assert bundle.intent == "comparison"
    assert bundle.entities == ["laptop"]
    assert len(bundle.sources) == 2
    assert {source.url for source in bundle.sources} == {
        "https://alpha.example/page",
        "https://beta.example/page",
    }
    assert bundle.queries_run >= 2
    assert bundle.evidence
    prompt = bundle.to_prompt()
    assert "SEARCH BRIEFING" in prompt
    assert "WEB SEARCH RESULTS FOR" in prompt
    assert "Source [1]" in prompt
    types = [event["type"] for event in events]
    assert types[0] == "search_plan"
    assert "search_query" in types
    assert "search_source" in types
    assert types[-1] == "search_done"
    assert set(bundle.gaps) == set()


def test_pipeline_without_results_reports_gaps(monkeypatch) -> None:
    monkeypatch.setattr(web_search, "perform_web_search", lambda *a, **kw: "")
    monkeypatch.setattr(settings, "SEARCH_SECOND_HOP", False)

    async def main():
        return await run_search_pipeline(
            "an incredibly obscure query",
            ollama_url="",
            model="",
            depth="quick",
        )

    bundle = asyncio.run(main())
    assert bundle.available is False
    assert bundle.sources == []
    assert bundle.gaps
    assert bundle.to_prompt() == ""


def test_progress_events_are_forwarded_untouched() -> None:
    from palimind.llm.stream import _progress_event_to_sse

    for event_type in ("search_plan", "search_query", "search_source", "search_done"):
        chunks = _progress_event_to_sse({"type": event_type, "value": 1})
        assert len(chunks) == 1
        payload = json.loads(chunks[0][len("data: ") :])
        assert payload["type"] == event_type
