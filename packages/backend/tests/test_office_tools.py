"""Round-trip tests for DOCX, PPTX and PDF office tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.llm.mixture_of_expert.tools import set_tool_context


@pytest.fixture()
def workspace(tmp_path: Path):
    set_tool_context(tmp_path)
    try:
        yield tmp_path
    finally:
        set_tool_context(None)


def _pdf(path: Path, text: str) -> None:
    import fitz

    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        doc.save(str(path))


def test_docx_roundtrip(workspace: Path) -> None:
    from palimind.agents.tools.office.tool import docx_read, docx_write

    out = docx_write(
        "docs/report.docx",
        "# Title\n\nIntro paragraph\n\n- First bullet\n- Second bullet",
        title="Report",
    )
    assert "Wrote DOCX" in out
    assert (workspace / "docs" / "report.docx").is_file()
    text = docx_read("docs/report.docx")
    assert "Title" in text
    assert "Intro paragraph" in text
    assert "First bullet" in text


def test_pptx_roundtrip(workspace: Path) -> None:
    from palimind.agents.tools.office.tool import pptx_read, pptx_write

    out = pptx_write(
        "deck.pptx",
        [
            {"title": "Overview", "bullets": ["Point A", "Point B"]},
            {"title": "Results", "bullets": ["Up 20%"]},
        ],
        title="Quarterly",
    )
    assert "Wrote PPTX" in out
    assert (workspace / "deck.pptx").is_file()
    text = pptx_read("deck.pptx")
    assert "Overview" in text
    assert "Point A" in text
    assert "Results" in text


def test_pdf_merge_split_rotate(workspace: Path) -> None:
    import fitz

    from palimind.agents.tools.office.tool import pdf_merge, pdf_rotate, pdf_split

    _pdf(workspace / "a.pdf", "Page A")
    _pdf(workspace / "b.pdf", "Page B")

    merged = pdf_merge(["a.pdf", "b.pdf"], "merged.pdf")
    assert "Merged 2 PDFs" in merged
    with fitz.open(str(workspace / "merged.pdf")) as doc:
        assert len(doc) == 2

    split = pdf_split("merged.pdf", output_dir="parts", pages="2")
    assert "Split into" in split
    part = workspace / "parts" / "merged_page_2.pdf"
    assert part.is_file()
    with fitz.open(str(part)) as doc:
        assert len(doc) == 1
        assert "Page B" in doc[0].get_text()

    rotated = pdf_rotate("merged.pdf", "rotated.pdf", angle=90, pages="1")
    assert "Rotated 1 page" in rotated
    with fitz.open(str(workspace / "rotated.pdf")) as doc:
        assert doc[0].rotation == 90
        assert doc[1].rotation == 0


def test_office_tools_reject_paths_outside_workspace(workspace: Path) -> None:
    from palimind.agents.tools.office.tool import docx_read, pdf_merge

    assert "access denied" in docx_read("/etc/passwd")
    _pdf(workspace / "a.pdf", "A")
    assert "access denied" in pdf_merge(["a.pdf"], "../escape.pdf")


def test_office_tools_are_registered_with_typed_schemas() -> None:
    from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, _register_plugin_tools

    _register_plugin_tools()
    for name in (
        "docx_read",
        "docx_write",
        "pptx_read",
        "pptx_write",
        "pdf_merge",
        "pdf_split",
        "pdf_rotate",
    ):
        assert name in TOOL_REGISTRY, name
        assert isinstance(TOOL_REGISTRY[name]["parameters"], dict)
    assert TOOL_REGISTRY["docx_write"]["meta"]["tier"] == 2
    assert TOOL_REGISTRY["pdf_merge"]["parameters"]["paths"]["type"] == "array"
    assert TOOL_REGISTRY["docx_read"]["meta"]["tier"] == 1
