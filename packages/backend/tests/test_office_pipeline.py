"""The chat composer's DOCX/PPTX pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def office_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "palimind-home"
    monkeypatch.setenv("PALIMIND_HOME", str(home))
    return home


def test_docx_pipeline_creates_a_real_word_file(office_home: Path) -> None:
    from docx import Document
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    response = client.post(
        "/api/office/generate",
        json={
            "format": "docx",
            "title": "Quarterly Report",
            "content": (
                "# Summary\n\n"
                "Revenue **up 20%**.\n\n"
                "## Highlights\n\n"
                "- Point A\n"
                "- Point B\n\n"
                "| Metric | Value |\n| --- | --- |\n| Revenue | 20% |\n"
            ),
        },
    )
    assert response.status_code == 200
    assert "wordprocessingml" in response.headers["content-type"]
    assert response.headers["x-palimind-filename"] == "Quarterly_Report.docx"
    target = Path(response.headers["x-palimind-path"])
    assert target.is_file()
    assert target.stat().st_size > 1000

    document = Document(str(target))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    assert "Quarterly Report" in paragraphs
    assert "Summary" in paragraphs
    assert "Revenue up 20%." in paragraphs
    assert any("Point A" == text for text in paragraphs)
    assert len(document.tables) == 1
    assert document.tables[0].cell(0, 0).text == "Metric"

    download = client.get(f"/api/office/file/{target.name}")
    assert download.status_code == 200
    assert download.content[:2] == b"PK"


def test_pptx_pipeline_creates_a_real_deck(office_home: Path) -> None:
    from fastapi.testclient import TestClient
    from pptx import Presentation

    import palimind.api_server as server

    client = TestClient(server.app)
    response = client.post(
        "/api/office/generate",
        json={
            "format": "pptx",
            "title": "Q3 Results",
            "slides": [
                {"title": "Overview", "bullets": ["Point A", "Point B"]},
                {"title": "Results", "bullets": ["Up 20%"]},
            ],
        },
    )
    assert response.status_code == 200
    assert "presentationml" in response.headers["content-type"]
    assert response.headers["x-palimind-filename"] == "Q3_Results.pptx"
    target = Path(response.headers["x-palimind-path"])
    assert target.is_file()

    deck = Presentation(str(target))
    assert len(deck.slides) == 3  # cover + two content slides
    text = "\n".join(
        shape.text
        for slide in deck.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "Q3 Results" in text
    assert "Overview" in text
    assert "Point B" in text
    assert "20%" in text
    assert "Up" in text


def test_designed_deck_has_cards_metrics_and_sections(office_home: Path) -> None:
    from fastapi.testclient import TestClient
    from pptx import Presentation

    import palimind.api_server as server

    client = TestClient(server.app)
    response = client.post(
        "/api/office/generate",
        json={
            "format": "pptx",
            "title": "Q3 Business Review",
            "slides": [
                {"title": "Q3 Business Review", "bullets": ["Board update · October 2026"]},
                {"title": "Performance", "bullets": []},
                {
                    "title": "Overview",
                    "bullets": [
                        "Revenue: $4.8M in Q3",
                        "Growth: 28% year over year",
                        "Customers: 12,400 active accounts",
                        "Churn: 2.1%, down from 3.4%",
                    ],
                },
                {
                    "title": "Roadmap",
                    "bullets": [
                        "Q4: enterprise SSO and audit logs",
                        "Q1: mobile offline mode",
                        "Q2: partner marketplace",
                        "Long term: agentic workflows for every team",
                    ],
                },
            ],
        },
    )
    assert response.status_code == 200
    target = Path(response.headers["x-palimind-path"])
    deck = Presentation(str(target))
    assert len(deck.slides) == 4  # cover + section + two content slides
    text = "\n".join(
        shape.text
        for slide in deck.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "$4.8M" in text and "Revenue" in text
    assert "28%" in text and "Growth" in text
    assert "Q4" in text and "enterprise SSO and audit logs" in text
    assert "SECTION" in text
    # Cards and KPI tiles are real shapes, not only text boxes.
    assert sum(len(slide.shapes) for slide in deck.slides) > 35


def test_pipeline_rejects_unknown_formats_and_escapes_paths(office_home: Path) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    bad = client.post("/api/office/generate", json={"format": "xlsx", "content": "x"})
    assert bad.status_code == 400
    outside = client.get("/api/office/file/..%2F..%2Fapi_token")
    assert outside.status_code in (403, 404)
