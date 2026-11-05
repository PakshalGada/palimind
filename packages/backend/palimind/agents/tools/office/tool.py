"""Office document tools: DOCX, PPTX and PDF manipulation.

All file paths are resolved through the same workspace sandbox as the file
tools, so an agent can only read/write inside its active scope. Read operations
are tier 1; operations that create or modify documents are tier 2 and go
through the approval gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _resolve(path: str, *, write: bool = False) -> Path | None:
    from palimind.llm.mixture_of_expert.tools import _resolve_in_workspace

    return _resolve_in_workspace(str(path), write=write)


def _rel(path: Path) -> str:
    from palimind.llm.mixture_of_expert.tools import _workspace_root

    root = _workspace_root()
    try:
        return str(path.relative_to(root)) if root else str(path)
    except Exception:
        return str(path)


def docx_read(path: str, max_chars: int = 20_000) -> str:
    """Read a Word document as plain text, including tables."""
    target = _resolve(path)
    if target is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    if not target.is_file():
        return f"Error: file not found at {path}"
    try:
        from docx import Document

        doc = Document(str(target))
        parts: list[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                style = str(getattr(para.style, "name", "") or "")
                prefix = "#" if "Heading 1" in style else "##" if "Heading 2" in style else ""
                parts.append(f"{prefix} {text}".strip())
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        out = "\n".join(parts) or "(empty document)"
        return out[: max(200, int(max_chars or 20_000))]
    except Exception as exc:  # noqa: BLE001
        return f"Error reading DOCX: {exc}"


def docx_write(path: str, content: str, title: str = "") -> str:
    """Create a Word document from simple Markdown-ish text."""
    target = _resolve(path, write=True)
    if target is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    try:
        from docx import Document

        doc = Document()
        if title.strip():
            doc.add_heading(title.strip(), level=0)
        for line in str(content or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("### "):
                doc.add_heading(stripped[4:], level=3)
            elif stripped.startswith("## "):
                doc.add_heading(stripped[3:], level=2)
            elif stripped.startswith("# "):
                doc.add_heading(stripped[2:], level=1)
            elif stripped.startswith(("- ", "* ")):
                doc.add_paragraph(stripped[2:], style="List Bullet")
            elif stripped.startswith("> "):
                doc.add_paragraph(stripped[2:], style="Quote")
            else:
                doc.add_paragraph(stripped)
        target.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(target))
        return f"Wrote DOCX ({len(str(content or ''))} chars) to {_rel(target)}"
    except Exception as exc:  # noqa: BLE001
        return f"Error writing DOCX: {exc}"


def pptx_read(path: str) -> str:
    """Read a PowerPoint deck as slide titles, text and bullet lists."""
    target = _resolve(path)
    if target is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    if not target.is_file():
        return f"Error: file not found at {path}"
    try:
        from pptx import Presentation

        prs = Presentation(str(target))
        parts: list[str] = []
        for idx, slide in enumerate(prs.slides, start=1):
            parts.append(f"## Slide {idx}")
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False):
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs).strip()
                    if not text:
                        continue
                    bullet = "- " if paragraph.level > 0 else ""
                    parts.append(f"{bullet}{text}")
        return "\n".join(parts) or "(empty presentation)"
    except Exception as exc:  # noqa: BLE001
        return f"Error reading PPTX: {exc}"


def _normalise_slides(slides: Any) -> list[dict[str, Any]]:
    if isinstance(slides, str):
        try:
            slides = json.loads(slides)
        except json.JSONDecodeError:
            slides = [{"title": "Slide", "bullets": [slides]}]
    if not isinstance(slides, list):
        slides = [{"title": "Slide", "bullets": [str(slides)]}]
    out: list[dict[str, Any]] = []
    for item in slides:
        if isinstance(item, str):
            out.append({"title": item, "bullets": []})
        elif isinstance(item, dict):
            bullets = item.get("bullets") or item.get("content") or []
            if isinstance(bullets, str):
                bullets = bullets.splitlines()
            out.append(
                {
                    "title": str(item.get("title") or "Slide"),
                    "bullets": [str(b) for b in bullets if str(b).strip()],
                }
            )
    return out


def pptx_write(path: str, slides: Any, title: str = "") -> str:
    """Create a PowerPoint deck from a list of {title, bullets} objects."""
    target = _resolve(path, write=True)
    if target is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    try:
        from pptx import Presentation

        prs = Presentation()
        deck = _normalise_slides(slides)
        if title.strip():
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = title.strip()
            if len(slide.placeholders) > 1:
                slide.placeholders[1].text = "Generated by PaliMind"
        for item in deck:
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = item["title"] or "Slide"
            body = slide.placeholders[1]
            text_frame = body.text_frame
            text_frame.clear()
            bullets = item["bullets"]
            if bullets:
                text_frame.text = bullets[0]
                for bullet in bullets[1:]:
                    text_frame.add_paragraph().text = bullet
            else:
                text_frame.text = ""
        target.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(target))
        return f"Wrote PPTX with {len(prs.slides)} slides to {_rel(target)}"
    except Exception as exc:  # noqa: BLE001
        return f"Error writing PPTX: {exc}"


def _parse_pages(spec: str, count: int) -> list[int]:
    """Parse 1-based page specs like ``1-3,5`` into unique 0-based indexes."""
    spec = str(spec or "").strip()
    if not spec:
        return list(range(count))
    pages: list[int] = []
    for atom in spec.split(","):
        atom = atom.strip()
        if not atom:
            continue
        if "-" in atom:
            a, b = atom.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            for page in range(max(1, start), min(count, end) + 1):
                pages.append(page - 1)
        else:
            try:
                page = int(atom)
            except ValueError:
                continue
            if 1 <= page <= count:
                pages.append(page - 1)
    return list(dict.fromkeys(pages))


def pdf_merge(paths: Any, output: str, output_dir: str = "") -> str:
    """Merge PDF files into one document."""
    if isinstance(paths, str):
        paths = [p.strip() for p in paths.split(",") if p.strip()]
    if not isinstance(paths, list) or len(paths) < 1:
        return "Error: paths must be a non-empty list"
    out_path = output if not output_dir else str(Path(output_dir) / output)
    target = _resolve(out_path, write=True)
    if target is None:
        return f"Error: access denied — '{out_path}' is outside the workspace"
    try:
        import fitz

        merged = fitz.open()
        try:
            for rel in paths:
                source = _resolve(str(rel))
                if source is None or not source.is_file():
                    return f"Error: PDF not found: {rel}"
                with fitz.open(str(source)) as doc:
                    merged.insert_pdf(doc)
            target.parent.mkdir(parents=True, exist_ok=True)
            merged.save(str(target))
            pages = len(merged)
        finally:
            merged.close()
        return f"Merged {len(paths)} PDFs into {_rel(target)} ({pages} pages)"
    except Exception as exc:  # noqa: BLE001
        return f"Error merging PDFs: {exc}"


def pdf_split(path: str, output_dir: str = "", pages: str = "") -> str:
    """Split selected pages into separate single-page PDFs."""
    source = _resolve(path)
    if source is None or not source.is_file():
        return f"Error: PDF not found: {path}"
    out_dir = _resolve(output_dir or ".", write=True)
    if out_dir is None:
        return "Error: output directory is outside the workspace"
    try:
        import fitz

        with fitz.open(str(source)) as doc:
            indexes = _parse_pages(pages, len(doc))
            if not indexes:
                return "Error: no matching pages"
            out_dir.mkdir(parents=True, exist_ok=True)
            created: list[str] = []
            for index in indexes:
                out = out_dir / f"{source.stem}_page_{index + 1}.pdf"
                with fitz.open() as part:
                    part.insert_pdf(doc, from_page=index, to_page=index)
                    part.save(str(out))
                created.append(_rel(out))
        return "Split into: " + ", ".join(created)
    except Exception as exc:  # noqa: BLE001
        return f"Error splitting PDF: {exc}"


def pdf_rotate(path: str, output: str, angle: int = 90, pages: str = "") -> str:
    """Rotate pages of a PDF by 90/180/270 degrees."""
    angle = int(angle or 90)
    if angle % 90 != 0:
        return "Error: angle must be a multiple of 90"
    source = _resolve(path)
    target = _resolve(output, write=True)
    if source is None or not source.is_file():
        return f"Error: PDF not found: {path}"
    if target is None:
        return f"Error: access denied — '{output}' is outside the workspace"
    try:
        import fitz

        with fitz.open(str(source)) as doc:
            indexes = _parse_pages(pages, len(doc))
            for index in indexes:
                page = doc[index]
                page.set_rotation((page.rotation + angle) % 360)
            target.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(target))
        return f"Rotated {len(indexes)} page(s) by {angle}° into {_rel(target)}"
    except Exception as exc:  # noqa: BLE001
        return f"Error rotating PDF: {exc}"


def _p(
    *,
    type: str = "string",
    description: str,
    required: bool = True,
    default: Any = None,
    items: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {"type": type, "description": description, "required": required}
    if default is not None:
        spec["default"] = default
        spec["required"] = False
    if items:
        spec["items"] = items
    return spec


TOOLS: dict[str, dict[str, Any]] = {
    "docx_read": {
        "fn": docx_read,
        "description": "Read a Word (.docx) document as text, including tables.",
        "parameters": {
            "path": _p(description="Workspace-relative path to the DOCX"),
            "max_chars": _p(type="integer", description="Maximum characters", default=20000),
        },
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "docx_write": {
        "fn": docx_write,
        "description": "Create or overwrite a Word (.docx) document from Markdown-ish text.",
        "parameters": {
            "path": _p(description="Output DOCX path"),
            "content": _p(description="Document body; supports #/##/### headings and - bullets"),
            "title": _p(description="Optional document title", required=False),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
    "pptx_read": {
        "fn": pptx_read,
        "description": "Read a PowerPoint (.pptx) deck as slide titles and text.",
        "parameters": {"path": _p(description="Workspace-relative path to the PPTX")},
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "pptx_write": {
        "fn": pptx_write,
        "description": "Create a PowerPoint deck from a title and a list of slide objects.",
        "parameters": {
            "path": _p(description="Output PPTX path"),
            "title": _p(description="Optional deck title", required=False),
            "slides": _p(
                type="array",
                description='List of {"title": "...", "bullets": ["..."]} objects',
                items={"type": "object"},
            ),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
    "pdf_merge": {
        "fn": pdf_merge,
        "description": "Merge PDF files into one output PDF.",
        "parameters": {
            "paths": _p(
                type="array",
                description="PDF paths to merge, in order",
                items={"type": "string"},
            ),
            "output": _p(description="Output PDF filename/path"),
            "output_dir": _p(description="Optional output directory", required=False),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
    "pdf_split": {
        "fn": pdf_split,
        "description": "Split selected PDF pages into separate single-page PDFs.",
        "parameters": {
            "path": _p(description="Source PDF path"),
            "output_dir": _p(description="Directory for split PDFs", required=False),
            "pages": _p(description='Optional 1-based pages, e.g. "1-3,5"', required=False),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
    "pdf_rotate": {
        "fn": pdf_rotate,
        "description": "Rotate PDF pages by 90, 180 or 270 degrees.",
        "parameters": {
            "path": _p(description="Source PDF path"),
            "output": _p(description="Output PDF path"),
            "angle": _p(type="integer", description="Rotation angle", default=90),
            "pages": _p(description='Optional 1-based pages, e.g. "1,3"', required=False),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
}
