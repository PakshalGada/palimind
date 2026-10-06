"""Tests for research source scoring and plan registry (Phase 3.1/3.5)."""

from __future__ import annotations

import asyncio

from palimind.generative.citation import Source
from palimind.research.plan_registry import (
    discard_plan,
    get_pending_plan,
    register_plan,
    resolve_plan,
)
from palimind.research.sources import (
    dedupe_sources,
    score_source,
    score_sources,
    sources_from_collected,
)


def test_score_source_authority_and_low_quality() -> None:
    nature = Source(marker=1, title="n", kind="web", url="https://www.nature.com/articles/x")
    quora = Source(marker=2, title="q", kind="web", url="https://quora.com/q")
    gov = Source(marker=3, title="g", kind="web", url="https://nasa.gov/report")
    doc = Source(marker=4, title="d", kind="document", file="a.pdf")

    assert score_source(nature) >= 0.9
    assert score_source(quora) <= 0.2
    assert score_source(gov) >= 0.9
    assert score_source(doc) == 0.8


def test_dedupe_sources_renumbers() -> None:
    collected = [
        {"url": "https://a.com/1", "title": "A"},
        {"url": "https://a.com/1", "title": "A duplicate"},
        {"url": "https://b.com/2", "title": "B"},
    ]
    sources = dedupe_sources(sources_from_collected(collected))
    assert [s.marker for s in sources] == [1, 2]
    assert sources[0].url == "https://a.com/1"
    score_sources(sources)
    assert all(s.score >= 0 for s in sources)


def test_plan_registry_approve_with_edits() -> None:
    event = asyncio.Event()
    pending = register_plan("query", [{"subtopic_id": 1, "title": "A"}], event)
    assert get_pending_plan(pending.plan_id) is not None
    assert resolve_plan(pending.plan_id, plan=[{"subtopic_id": 1, "title": "Edited"}])
    resolved = get_pending_plan(pending.plan_id)
    assert resolved is not None
    assert resolved.approved is True
    assert resolved.edited_plan == [{"subtopic_id": 1, "title": "Edited"}]
    discard_plan(pending.plan_id)
    assert get_pending_plan(pending.plan_id) is None


def test_plan_registry_cancel() -> None:
    event = asyncio.Event()
    pending = register_plan("query", [{"subtopic_id": 1}], event)
    assert resolve_plan(pending.plan_id, cancelled=True)
    resolved = get_pending_plan(pending.plan_id)
    assert resolved is not None
    assert resolved.cancelled is True
    discard_plan(pending.plan_id)


def test_resolve_unknown_plan_returns_false() -> None:
    assert resolve_plan("does-not-exist", plan=[]) is False


def test_project_store_crud(monkeypatch, tmp_path) -> None:
    import palimind.research.project_store as ps

    monkeypatch.setattr(ps, "projects_dir", lambda: tmp_path)

    project = ps.create_project("My Research", "what is X?")
    assert project["title"] == "My Research"
    assert any(e["type"] == "created" for e in project["timeline"])

    ps.add_finding(project["id"], "Finding 1", "Some insight")
    ps.add_sources(
        project["id"],
        [
            {"url": "https://a.com/1", "title": "A"},
            {"url": "https://a.com/1", "title": "A duplicate"},
        ],
    )
    loaded = ps.load_project(project["id"])
    assert loaded is not None
    assert len(loaded["findings"]) == 1
    assert len(loaded["sources"]) == 1  # deduplicated
    assert any(e["type"] == "finding" for e in loaded["timeline"])

    summaries = ps.list_projects()
    assert summaries[0]["source_count"] == 1
    assert summaries[0]["finding_count"] == 1

    assert ps.delete_project(project["id"]) is True
    assert ps.load_project(project["id"]) is None
