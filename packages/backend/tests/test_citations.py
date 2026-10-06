"""Tests for the citation engine (Phase 3.3)."""

from __future__ import annotations

from palimind.generative.citation import (
    Source,
    attach_citations,
    build_bibliography,
    existing_markers,
    parse_web_sources,
    score_citation_accuracy,
    sources_from_text_refs,
)

WEB_OUTPUT = """=== WEB SEARCH RESULTS FOR: 'quantum computing' ===

Source [1]: Quantum computing - Wikipedia
URL: https://en.wikipedia.org/wiki/Quantum_computing
Summary: Quantum computing is a type of computation that harnesses quantum mechanics.
Page Content: Quantum computers use qubits which can be in superposition.

Source [2]: IBM Quantum roadmap
URL: https://ibm.com/quantum/roadmap
Summary: IBM plans to scale superconducting quantum processors to thousands of qubits.

=========================================================================
"""


def test_parse_web_sources() -> None:
    sources = parse_web_sources(WEB_OUTPUT)
    assert len(sources) == 2
    assert sources[0].marker == 1
    assert sources[0].url == "https://en.wikipedia.org/wiki/Quantum_computing"
    assert "qubits" in sources[0].content
    assert sources[1].marker == 2


def test_sources_from_text_refs_dedupes() -> None:
    refs = [
        {"file": "a.pdf", "section": "Intro", "snippet": "hello world"},
        {"file": "a.pdf", "section": "Intro", "snippet": "duplicate"},
        {"file": "b.pdf", "section": "Methods", "snippet": "other"},
    ]
    sources = sources_from_text_refs(refs)
    assert [s.marker for s in sources] == [1, 2]
    assert sources[0].kind == "document"
    assert sources[0].section == "Intro"


def test_attach_citations_links_matching_sentences() -> None:
    sources = [
        Source(
            marker=1,
            title="Quantum computing",
            snippet="Quantum computers use qubits which can exist in superposition.",
        ),
        Source(
            marker=2,
            title="Gardening",
            snippet="Tomatoes need plenty of sunlight and regular watering.",
        ),
    ]
    answer = (
        "Quantum computers use qubits that can exist in superposition states. "
        "Tomatoes need sunlight and regular watering to grow well."
    )
    result = attach_citations(answer, sources)
    assert "[1]" in result.text
    assert "[2]" in result.text
    assert len(result.citations) == 2
    assert result.cited_markers == [1, 2]
    assert result.accuracy > 0


def test_attach_citations_skips_code_and_headings() -> None:
    sources = [Source(marker=1, title="Code", snippet="def compute_qubits superposition")]
    answer = (
        "## Code\n\n"
        "```python\n"
        "def compute_qubits():\n"
        "    return superposition_qubits()\n"
        "```\n\n"
        "The function computes qubits in superposition states for the system."
    )
    result = attach_citations(answer, sources)
    # The code block itself must be untouched; only the prose gets a marker.
    assert "return superposition_qubits()\n```" in result.text
    assert result.text.count("[1]") == 1


def test_attach_citations_respects_threshold() -> None:
    sources = [Source(marker=1, title="Astronomy", snippet="Galaxies contain billions of stars.")]
    answer = "I enjoy baking sourdough bread on weekends with my family."
    result = attach_citations(answer, sources)
    assert "[1]" not in result.text
    assert result.citations == []
    assert result.accuracy == 0.0


def test_build_bibliography_formats_web_and_document() -> None:
    sources = [
        Source(marker=1, title="Wikipedia", kind="web", url="https://en.wikipedia.org/wiki/X"),
        Source(marker=2, title="Report", kind="document", file="docs/report.pdf", section="Intro"),
    ]
    bib = build_bibliography(sources)
    assert "1. [Wikipedia](https://en.wikipedia.org/wiki/X)" in bib
    assert "2. `docs/report.pdf → Intro`" in bib


def test_existing_markers_and_accuracy() -> None:
    text = "Claim one [1] and claim two [3]."
    assert existing_markers(text) == [1, 3]
    sources = [Source(marker=1, title="a"), Source(marker=2, title="b")]
    # Only marker 1 is valid → 0.5 accuracy.
    assert score_citation_accuracy(text, sources) == 0.5
