"""Tests for agent source ledgers and citation attachment."""

from __future__ import annotations

from palimind.agents.citations import finalize_agent_citations


def test_web_source_becomes_cited_payload() -> None:
    collected = [
        {
            "url": "https://example.com/sky",
            "title": "Why the sky is blue",
            "snippet": "Rayleigh scattering makes the sky blue.",
            "content": "Rayleigh scattering makes the sky blue in every direction.",
        }
    ]
    text, payload = finalize_agent_citations("Rayleigh scattering makes the sky blue.", collected)
    assert payload is not None
    assert payload["sources"][0]["kind"] == "web"
    assert payload["sources"][0]["url"] == "https://example.com/sky"
    assert "[1]" in text


def test_document_source_becomes_cited_payload() -> None:
    collected = [
        {
            "url": "",
            "file": "docs/report.pdf",
            "section": "Results",
            "title": "Results",
            "snippet": "Revenue grew 20 percent in 2025.",
            "content": "Revenue grew 20 percent in 2025.",
        }
    ]
    text, payload = finalize_agent_citations("Revenue grew 20 percent in 2025.", collected)
    assert payload is not None
    source = payload["sources"][0]
    assert source["kind"] == "document"
    assert source["file"] == "docs/report.pdf"
    assert "[1]" in text


def test_empty_input_is_a_noop() -> None:
    assert finalize_agent_citations("answer", []) == ("answer", None)
    assert finalize_agent_citations("", [{"url": "https://x"}]) == ("", None)


def test_bad_source_records_do_not_raise() -> None:
    assert finalize_agent_citations("answer", [{"bad": "record"}]) == ("answer", None)
