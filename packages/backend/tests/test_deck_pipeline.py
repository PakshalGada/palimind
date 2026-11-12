"""Tests for the staged presentation and Word pipelines."""

from __future__ import annotations

import io

import pytest


def _specs():
    return [
        {"title": "Agenda", "bullets": ["Where we are", "What changed"]},
        {"title": "Performance", "bullets": ["Revenue: $4.8M", "Growth: 28%"]},
        {
            "title": "Risks",
            "bullets": ["Support: response up from 4h to 7h", "Onboarding: 11 days"],
        },
        {"title": "Q4 roadmap", "bullets": ["Q4: SSO", "Q1: mobile", "Q2: partners"]},
        {
            "title": "Current vs proposed",
            "bullets": ["Current: one plan", "Proposed: three tiers"],
        },
        {"title": "Thank you", "bullets": ["Questions?"]},
    ]


def test_parse_outline_accepts_markdown_hints_and_slide_lists() -> None:
    from palimind.artifacts.deck import parse_outline

    markdown = "\n".join(
        [
            "# Cover",
            "- Board update",
            "",
            "# Numbers [layout: metrics]",
            "- Revenue: $4.8M",
            "- Growth: 28%",
            "",
            "# Section",
        ]
    )
    specs = parse_outline("Deck", markdown)
    assert [title for title, _bullets, _hint in specs] == ["Cover", "Numbers", "Section"]
    assert specs[1][2] == "metrics"

    listed = parse_outline("Deck", slides=[{"title": "One", "bullets": "A\nB"}])
    assert listed == [("One", ["A", "B"], "")]


def test_plan_deck_infers_a_layout_for_each_slide() -> None:
    from palimind.artifacts.deck import plan_deck

    plan = plan_deck(
        "Quarterly review", [(item["title"], item["bullets"], "") for item in _specs()]
    )
    assert [slide.layout for slide in plan.slides] == [
        "agenda",
        "metrics",
        "cards",
        "timeline",
        "comparison",
        "closing",
    ]
    assert plan.slides[1].bullets == ("Revenue: $4.8M", "Growth: 28%")


def test_plan_deck_splits_long_lists_instead_of_shrinking_text() -> None:
    from palimind.artifacts.deck import plan_deck

    bullets = [f"Priority {index}" for index in range(1, 10)]
    plan = plan_deck("Deck", [("Priorities", bullets, "")])
    assert len(plan.slides) == 2
    assert len(plan.slides[0].bullets) == 6
    assert plan.slides[1].title.endswith("(cont.)")


def test_render_deck_is_a_valid_presentation() -> None:
    pptx = pytest.importorskip("pptx")
    from palimind.artifacts.deck import build_deck, validate_deck

    data, plan, warnings = build_deck("Quarterly review", slides=_specs())
    assert warnings == []
    deck = pptx.Presentation(io.BytesIO(data))
    assert len(deck.slides) == len(plan.slides) + 1
    text = "\n".join(
        shape.text
        for slide in deck.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "Quarterly review" in text
    assert "Revenue" in text and "$4.8M" in text
    assert "CURRENT" in text and "PROPOSED" in text
    assert "Q4" in text and "SSO" in text
    assert validate_deck(data, expected_slides=len(deck.slides)) == []
    assert validate_deck(b"not a deck")[0].startswith("not a readable presentation")


def test_build_docx_preserves_formatting_tables_and_structure() -> None:
    docx = pytest.importorskip("docx")
    from palimind.artifacts.docx_document import build_docx, validate_docx

    data = build_docx(
        "Quarterly Report",
        "\n".join(
            [
                "# Quarterly Report",
                "",
                "Revenue **up 20%** and churn is *improving*.",
                "",
                "## Highlights",
                "",
                "- Point A",
                "- Point B",
                "",
                "> The next quarter is about execution.",
                "",
                "| Metric | Value |",
                "| --- | --- |",
                "| Revenue | 20% |",
                "",
                "```python",
                "print('ok')",
                "```",
            ]
        ),
    )
    document = docx.Document(io.BytesIO(data))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    assert "Quarterly Report" in paragraphs
    assert "Highlights" in paragraphs
    assert "Revenue up 20% and churn is improving." in paragraphs
    assert any("Point A" == text for text in paragraphs)
    assert any("execution" in text for text in paragraphs)
    assert len(document.tables) == 1
    assert document.tables[0].cell(0, 0).text == "Metric"
    assert validate_docx(data) == []
    assert validate_docx(b"not a docx")[0].startswith("not a readable Word document")
