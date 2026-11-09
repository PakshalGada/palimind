"""Server-side artifact export fallbacks.

The UI performs most exports client-side (jsPDF/DOCX/PPTX/canvas). These
helpers keep the API contract working for clients that prefer a server-side
download, and they persist generated binaries in the owning project.
"""

from __future__ import annotations

import html as html_lib
import io
import json
import re
from pathlib import Path
from typing import Any

_FORMATS = {
    "md": ("md", "text/markdown; charset=utf-8"),
    "html": ("html", "text/html; charset=utf-8"),
    "pdf": ("pdf", "application/pdf"),
    "docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "pptx": ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    "png": ("png", "image/png"),
}


def _plain_text(content: str) -> str:
    text = re.sub(r"```[^\n]*\n?", "", content)
    text = text.replace("```", "")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    return text


def _html_document(title: str, content: str, artifact_type: str) -> str:
    if artifact_type == "html" and "<html" in content.lower():
        return content
    body = content if artifact_type in {"html", "svg"} else f"<pre>{html_lib.escape(content)}</pre>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{html_lib.escape(title)}</title>
<style>
body {{ margin: 0; padding: 40px; font: 15px/1.65 system-ui, sans-serif; background: #fff; color: #18181b; }}
main {{ max-width: 860px; margin: 0 auto; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #f4f4f5; padding: 16px; border-radius: 10px; }}
svg, img {{ max-width: 100%; height: auto; }}
</style></head><body><main>{body}</main></body></html>"""


def _pdf_bytes(title: str, content: str, artifact_type: str) -> bytes:
    try:
        from weasyprint import HTML

        return HTML(string=_html_document(title, content, artifact_type)).write_pdf()
    except Exception:
        return _minimal_pdf(title, _plain_text(content))


def _minimal_pdf(title: str, text: str) -> bytes:
    """Dependency-free text PDF fallback (Helvetica, A4, simple line wrap)."""
    width, height = 595, 842
    margin, line_height = 48, 15
    max_chars = 86
    lines: list[str] = [title, ""]
    for raw in text.splitlines():
        if not raw:
            lines.append("")
            continue
        while len(raw) > max_chars:
            split_at = raw.rfind(" ", 0, max_chars)
            if split_at <= 0:
                split_at = max_chars
            lines.append(raw[:split_at])
            raw = raw[split_at:].lstrip()
        lines.append(raw)

    pages: list[list[str]] = []
    current: list[str] = []
    capacity = (height - margin * 2) // line_height
    for line in lines:
        if len(current) >= capacity:
            pages.append(current)
            current = []
        current.append(line)
    if current:
        pages.append(current)
    if not pages:
        pages = [[""]]

    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_ids = [4 + i * 2 for i in range(len(pages))]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, page in enumerate(pages):
        page_id = 4 + index * 2
        content_id = page_id + 1
        lines_pdf = []
        y = height - margin
        for line in page:
            lines_pdf.append(f"BT /F1 10 Tf 1 0 0 1 {margin} {y} Tm ({escape(line)}) Tj ET")
            y -= line_height
        stream = "\n".join(lines_pdf).encode("latin-1", "replace")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode())
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def _markdown_table_rows(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    """Read one contiguous Markdown table beginning at *start*."""
    rows: list[list[str]] = []
    index = start
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("|") or not line.endswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        # Skip the separator row (`| --- | :---: |`).
        if not rows and all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells):
            index += 1
            continue
        if all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells):
            index += 1
            continue
        rows.append([cell.replace("**", "").replace("__", "") for cell in cells])
        index += 1
    return rows, index


def _docx_bytes(title: str, content: str) -> bytes:
    from docx import Document

    document = Document()
    document.add_heading(title or "Artifact", level=0)
    in_code = False
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        index += 1
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            paragraph = document.add_paragraph()
            run = paragraph.add_run(line or " ")
            run.font.name = "Courier New"
            continue

        # Markdown table → real Word table.
        if line.strip().startswith("|") and line.strip().endswith("|"):
            rows, index = _markdown_table_rows(lines, index - 1)
            if rows:
                columns = max(len(row) for row in rows)
                table = document.add_table(rows=len(rows), cols=columns)
                table.style = "Table Grid"
                for row_index, row in enumerate(rows):
                    for column in range(columns):
                        table.cell(row_index, column).text = (
                            row[column] if column < len(row) else ""
                        )
                document.add_paragraph("")
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            document.add_heading(
                _inline_text(heading.group(2)), level=min(4, len(heading.group(1)))
            )
            continue
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if bullet:
            document.add_paragraph(_inline_text(bullet.group(1)), style="List Bullet")
            continue
        numbered = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if numbered:
            document.add_paragraph(_inline_text(numbered.group(1)), style="List Number")
            continue
        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            document.add_paragraph(_inline_text(quote.group(1)), style="Quote")
            continue
        if re.fullmatch(r"\s*([-*_])\1{2,}\s*", line):
            continue
        document.add_paragraph(_inline_text(line))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _inline_text(value: str) -> str:
    """Strip the inline Markdown Word cannot represent as plain text."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return text.replace("~~", "")


def office_bytes(
    fmt: str,
    title: str,
    content: str = "",
    slides: Any | None = None,
) -> tuple[bytes, str, str]:
    """Build a real Office file for the chat composer's document pipeline.

    Returns ``(bytes, extension, media_type)``. DOCX consumes Markdown-ish
    text; PPTX consumes either a slide outline in *content* or an explicit
    ``[{title, bullets}]`` list in *slides*.
    """
    normalized = normalize_format(fmt)
    if normalized == "docx":
        return (
            _docx_bytes(title, content),
            "docx",
            _FORMATS["docx"][1],
        )
    if normalized == "pptx":
        return (
            _pptx_bytes(title, content, "slide-outline", slides=slides),
            "pptx",
            _FORMATS["pptx"][1],
        )
    raise ValueError(f"Unsupported office format: {fmt}")


def _slide_specs(title: str, content: str, artifact_type: str) -> list[tuple[str, list[str]]]:
    slides: list[tuple[str, list[str]]] = []
    current_title = ""
    bullets: list[str] = []

    def flush() -> None:
        nonlocal current_title, bullets
        if current_title or bullets:
            slides.append((current_title or title or "Slide", bullets))
        current_title, bullets = "", []

    if artifact_type != "slide-outline":
        current_title = title or "Artifact"
        for line in content.splitlines():
            text = re.sub(r"^#{1,6}\s*", "", line).strip()
            text = re.sub(r"^[-*]\s+", "", text)
            if text:
                bullets.append(text)
        flush()
        return slides or [(title or "Artifact", [])]

    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^-{3,}$", line):
            flush()
            continue
        heading = re.match(r"^#{1,4}\s+(.+)$", line) or re.match(
            r"^slide\s*\d+\s*[:.-]\s*(.+)$", line, re.IGNORECASE
        )
        if heading:
            flush()
            current_title = heading.group(1)
            continue
        bullets.append(re.sub(r"^\s*[-*•]\s+", "", line))
    flush()
    return slides or [(title or "Artifact", [])]


def _normalise_slides(slides: Any) -> list[tuple[str, list[str]]]:
    """Accept the shapes models and tools produce for a deck."""
    if isinstance(slides, str):
        try:
            slides = json.loads(slides)
        except json.JSONDecodeError:
            slides = [{"title": "Slide", "bullets": [slides]}]
    if not isinstance(slides, list):
        slides = [{"title": "Slide", "bullets": [str(slides)]}]
    out: list[tuple[str, list[str]]] = []
    for item in slides:
        if isinstance(item, str):
            out.append((item, []))
            continue
        if not isinstance(item, dict):
            continue
        bullets = item.get("bullets") or item.get("content") or []
        if isinstance(bullets, str):
            bullets = bullets.splitlines()
        out.append(
            (
                str(item.get("title") or "Slide"),
                [str(b).strip() for b in bullets if str(b).strip()],
            )
        )
    return out


_DECK_INK = "0F172A"
_DECK_MUTED = "64748B"
_DECK_ACCENT = "2563EB"
_DECK_ACCENT_2 = "7C3AED"
_DECK_CARD = "F1F5F9"
_DECK_LINE = "CBD5E1"
_DECK_DARK = "0B1220"
_DECK_WHITE = "FFFFFF"
_DECK_SOFT = "F8FAFC"


def _rgb(value: str):
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(value)


def _add_text(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: int = 14,
    bold: bool = False,
    color: str = _DECK_INK,
    align=None,
    anchor=None,
    font: str = "Aptos",
    line_spacing: float | None = None,
):
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = Inches(0.04)
    frame.margin_right = Inches(0.04)
    frame.margin_top = Inches(0.02)
    frame.margin_bottom = Inches(0.02)
    if anchor is not None:
        frame.vertical_anchor = anchor
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    if align is not None:
        paragraph.alignment = align
    if line_spacing is not None:
        paragraph.line_spacing = line_spacing
    for run in paragraph.runs:
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = _rgb(color)
    return box


def _add_rect(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str,
    line: str | None = None,
    rounded: bool = False,
    line_width: float = 1.0,
):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(fill)
    if line:
        shape.line.color.rgb = _rgb(line)
        shape.line.width = Pt(line_width)
    else:
        shape.line.fill.background()
    if rounded:
        try:
            shape.adjustments[0] = 0.06
        except (IndexError, ValueError):
            pass
    return shape


def _split_label(text: str) -> tuple[str, str]:
    """'Revenue: up 20%' → ('Revenue', 'up 20%'); no colon stays one label."""
    raw = re.sub(r"^[-*•]\s+", "", str(text or "")).strip()
    if ":" in raw:
        label, _, detail = raw.partition(":")
        if len(label.strip()) <= 48:
            return label.strip(), detail.strip()
    if "—" in raw:
        label, _, detail = raw.partition("—")
        if len(label.strip()) <= 48:
            return label.strip(), detail.strip()
    return raw[:90], ""


_METRIC_RE = re.compile(
    r"[~$€£]?\d[\d.,]*\s?(?:%|x|k|m|b|bn|million|billion)?",
    re.IGNORECASE,
)


def _metric_of(text: str) -> tuple[str, str] | None:
    """Extract a short KPI value plus its label from a bullet.

    ``Revenue: $4.8M in Q3`` → ``("Revenue", "$4.8M")`` so the card's large
    value stays on one line and the narrative does not collide with the label.
    """
    label, detail = _split_label(text)
    candidate = detail or label
    match = _METRIC_RE.search(candidate)
    if match is None:
        return None
    value = match.group(0).strip().rstrip(".,")
    if not value:
        return None
    if detail:
        return label or "Metric", value
    remainder = (candidate[: match.start()] + candidate[match.end() :]).strip(" ,.-")
    return (remainder[:48] or "Metric"), value


def _add_deck_footer(slide, deck_title: str, number: int, total: int) -> None:
    from pptx.enum.text import PP_ALIGN

    _add_rect(slide, 0.62, 7.02, 12.1, 0.012, fill=_DECK_LINE)
    _add_text(
        slide,
        deck_title[:70],
        0.62,
        7.08,
        8.5,
        0.28,
        size=9,
        color=_DECK_MUTED,
    )
    _add_text(
        slide,
        f"{number} / {total}",
        11.2,
        7.08,
        1.5,
        0.28,
        size=9,
        color=_DECK_MUTED,
        align=PP_ALIGN.RIGHT,
    )


def _render_cover(
    prs,
    title: str,
    specs: list[tuple[str, list[str]]],
    subtitle_override: str | None = None,
) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(_DECK_DARK)
    # Geometric accents: a large translucent-looking panel and two bars.
    _add_rect(slide, 10.1, 0, 3.24, 7.5, fill="111C33")
    _add_rect(slide, 10.1, 0, 0.08, 7.5, fill=_DECK_ACCENT)
    _add_rect(slide, 0.72, 1.35, 0.9, 0.08, fill=_DECK_ACCENT)
    _add_text(
        slide,
        "PRESENTATION",
        0.72,
        1.55,
        7.5,
        0.35,
        size=11,
        bold=True,
        color="93C5FD",
    )
    _add_text(
        slide,
        title or "Presentation",
        0.72,
        2.0,
        8.9,
        2.0,
        size=42,
        bold=True,
        color=_DECK_WHITE,
        anchor=MSO_ANCHOR.TOP,
    )
    subtitle = subtitle_override or "A PaliMind deck"
    if not subtitle_override and specs:
        first_bullets = specs[0][1]
        if first_bullets:
            subtitle = first_bullets[0][:110]
    _add_text(slide, subtitle, 0.75, 4.45, 8.0, 0.7, size=16, color="CBD5E1")
    _add_text(
        slide,
        "Generated with PaliMind · local-first AI workspace",
        0.75,
        6.75,
        8.5,
        0.35,
        size=10,
        color="94A3B8",
    )
    _add_text(
        slide,
        "01",
        10.55,
        5.3,
        2.1,
        1.0,
        size=54,
        bold=True,
        color="1E40AF",
        align=PP_ALIGN.RIGHT,
    )


def _render_section(prs, slide_title: str, number: int, total: int, deck_title: str) -> None:
    from pptx.enum.text import MSO_ANCHOR

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(_DECK_DARK)
    _add_rect(slide, 0, 0, 0.18, 7.5, fill=_DECK_ACCENT)
    _add_text(slide, "SECTION", 0.85, 2.2, 3.0, 0.4, size=11, bold=True, color="93C5FD")
    _add_text(
        slide,
        slide_title[:90],
        0.85,
        2.65,
        10.8,
        2.0,
        size=38,
        bold=True,
        color=_DECK_WHITE,
        anchor=MSO_ANCHOR.TOP,
    )
    _add_text(slide, deck_title[:70], 0.85, 6.65, 8.0, 0.3, size=9, color="94A3B8")
    _add_text(slide, f"{number:02d} / {total:02d}", 11.3, 6.65, 1.4, 0.3, size=9, color="94A3B8")


def _render_cards(slide, bullets: list[str]) -> None:
    cards = [_split_label(bullet) for bullet in bullets[:6]]
    columns = 2 if len(cards) <= 4 else 3
    rows = (len(cards) + columns - 1) // columns
    gap_x = 0.22
    gap_y = 0.24
    left, top = 0.72, 1.62
    total_w = 11.9
    total_h = 4.95
    card_w = (total_w - gap_x * (columns - 1)) / columns
    card_h = (total_h - gap_y * (rows - 1)) / max(1, rows)
    for index, (label, detail) in enumerate(cards):
        column = index % columns
        row = index // columns
        x = left + column * (card_w + gap_x)
        y = top + row * (card_h + gap_y)
        _add_rect(slide, x, y, card_w, card_h, fill=_DECK_CARD, line="E2E8F0", rounded=True)
        _add_rect(
            slide, x, y, 0.07, card_h, fill=_DECK_ACCENT if index % 2 == 0 else _DECK_ACCENT_2
        )
        _add_text(
            slide, label or "Point", x + 0.24, y + 0.22, card_w - 0.42, 0.5, size=15, bold=True
        )
        if detail:
            _add_text(
                slide,
                detail[:240],
                x + 0.24,
                y + 0.82,
                card_w - 0.42,
                card_h - 0.95,
                size=12,
                color="334155",
                line_spacing=1.08,
            )


def _render_metrics(slide, metrics: list[tuple[str, str]]) -> None:
    metrics = metrics[:4]
    count = max(1, len(metrics))
    gap = 0.25
    left, top = 0.72, 1.78
    width = (11.9 - gap * (count - 1)) / count
    height = 3.2
    for index, (label, value) in enumerate(metrics):
        x = left + index * (width + gap)
        value_size = 32 if len(value) <= 7 else 24 if len(value) <= 10 else 18
        _add_rect(slide, x, top, width, height, fill=_DECK_CARD, line="E2E8F0", rounded=True)
        _add_rect(
            slide, x, top, width, 0.07, fill=_DECK_ACCENT if index % 2 == 0 else _DECK_ACCENT_2
        )
        _add_text(
            slide,
            value,
            x + 0.22,
            top + 0.5,
            width - 0.4,
            0.85,
            size=value_size,
            bold=True,
            color=_DECK_INK,
        )
        _add_text(
            slide,
            label[:90],
            x + 0.22,
            top + 1.45,
            width - 0.4,
            1.3,
            size=12,
            color="475569",
            line_spacing=1.05,
        )


def _render_row_cards(slide, bullets: list[str]) -> None:
    """Short lists become stacked rows so a slide never reads as bare bullets."""
    items = [str(b).strip() for b in bullets if str(b).strip()][:6]
    if not items:
        return
    gap = 0.14
    left, top = 0.72, 1.68
    width, available = 11.9, 5.0
    height = (available - gap * (len(items) - 1)) / len(items)
    for index, item in enumerate(items):
        y = top + index * (height + gap)
        _add_rect(slide, left, y, width, height, fill=_DECK_CARD, line="E2E8F0", rounded=True)
        _add_rect(
            slide, left, y, 0.08, height, fill=_DECK_ACCENT if index % 2 == 0 else _DECK_ACCENT_2
        )
        _add_text(
            slide,
            f"{index + 1:02d}",
            left + 0.22,
            y + (height - 0.34) / 2,
            0.6,
            0.34,
            size=11,
            bold=True,
            color=_DECK_MUTED,
        )
        _add_text(
            slide,
            item[:260],
            left + 0.9,
            y + 0.08,
            width - 1.15,
            max(0.3, height - 0.16),
            size=14,
            color="1E293B",
            line_spacing=1.05,
        )


def _render_bullets(slide, bullets: list[str]) -> None:
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Inches, Pt

    items = [str(b).strip() for b in bullets if str(b).strip()][:12]
    if not items:
        return
    two_columns = len(items) > 6
    columns = 2 if two_columns else 1
    gap = 0.35
    left, top = 0.78, 1.7
    width = (11.8 - gap) / columns
    height = 4.9
    per_column = (len(items) + columns - 1) // columns
    for column in range(columns):
        chunk = items[column * per_column : (column + 1) * per_column]
        if not chunk:
            continue
        box = slide.shapes.add_textbox(
            Inches(left + column * (width + gap)), Inches(top), Inches(width), Inches(height)
        )
        frame = box.text_frame
        frame.word_wrap = True
        frame.vertical_anchor = MSO_ANCHOR.TOP
        for index, item in enumerate(chunk):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.space_after = Pt(10)
            paragraph.line_spacing = 1.08
            glyph = paragraph.add_run()
            glyph.text = "▸  "
            glyph.font.name = "Aptos"
            glyph.font.size = Pt(14)
            glyph.font.bold = True
            glyph.font.color.rgb = _rgb(_DECK_ACCENT)
            label, detail = _split_label(item)
            run = paragraph.add_run()
            run.text = label
            run.font.name = "Aptos"
            run.font.size = Pt(15)
            run.font.bold = True
            run.font.color.rgb = _rgb(_DECK_INK)
            if detail:
                run2 = paragraph.add_run()
                run2.text = f" — {detail}"
                run2.font.name = "Aptos"
                run2.font.size = Pt(13)
                run2.font.color.rgb = _rgb("334155")


def _render_content(
    prs, slide_title: str, bullets: list[str], number: int, total: int, deck_title: str
) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(_DECK_WHITE)
    _add_rect(slide, 0, 0, 13.333, 0.08, fill=_DECK_ACCENT)
    _add_rect(slide, 0.72, 0.72, 0.5, 0.07, fill=_DECK_ACCENT_2)
    _add_text(slide, "DETAIL", 1.3, 0.55, 3.0, 0.3, size=9, bold=True, color=_DECK_ACCENT)
    _add_text(slide, slide_title[:100], 0.72, 0.9, 11.6, 0.75, size=27, bold=True)
    _add_rect(slide, 0.72, 1.7, 12.0, 0.012, fill="E2E8F0")
    _add_text(slide, f"{number:02d}", 12.1, 0.48, 0.55, 0.4, size=12, bold=True, color=_DECK_MUTED)

    metrics = [m for m in (_metric_of(b) for b in bullets) if m]
    if not bullets:
        _add_text(
            slide,
            "Add detail in the next revision.",
            0.8,
            2.2,
            4.0,
            0.5,
            size=14,
            color=_DECK_MUTED,
        )
    elif len(metrics) >= 2 and len(metrics) >= len(bullets) - 1:
        _render_metrics(slide, metrics)
    elif sum(1 for b in bullets if ":" in b or "—" in b) >= 2 and len(bullets) <= 6:
        _render_cards(slide, bullets)
    elif 3 <= len(bullets) <= 6:
        _render_row_cards(slide, bullets)
    else:
        _render_bullets(slide, bullets)
    _add_deck_footer(slide, deck_title, number, total)


def _pptx_from_specs(title: str, specs: list[tuple[str, list[str]]]) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    # A leading title-only slide is the deck title, already rendered as the
    # designed cover. Drop it instead of duplicating the cover.
    deck_specs = list(specs)
    cover_subtitle: str | None = None
    if deck_specs:
        first = deck_specs[0][0].strip().lower()
        deck = (title or "").strip().lower()
        if not deck or first == deck or first in deck or deck in first:
            first_bullets = deck_specs[0][1]
            if first_bullets:
                cover_subtitle = first_bullets[0][:110]
            deck_specs = deck_specs[1:]
    total = len(deck_specs) + 1
    _render_cover(prs, title or "Presentation", deck_specs, cover_subtitle)
    for index, (slide_title, bullets) in enumerate(deck_specs, start=2):
        if not bullets:
            _render_section(prs, slide_title, index, total, title or "Presentation")
        else:
            _render_content(prs, slide_title, bullets, index, total, title or "Presentation")
    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def _pptx_bytes(
    title: str,
    content: str,
    artifact_type: str,
    slides: Any | None = None,
) -> bytes:
    specs = (
        _normalise_slides(slides)
        if slides is not None
        else _slide_specs(title, content, artifact_type)
    )
    return _pptx_from_specs(title, specs)


def _png_bytes(title: str, content: str) -> bytes:
    from PIL import Image, ImageDraw

    width, height = 1600, 2000
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.text((70, 60), title or "Artifact", fill="#18181b")
    y = 130
    for line in _plain_text(content).splitlines():
        if y > height - 80:
            break
        draw.text((70, y), line[:140], fill="#3f3f46")
        y += 26
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def export_filename(title: str, extension: str) -> str:
    # ASCII only: the name goes into a raw Content-Disposition header, which
    # Starlette encodes as latin-1 — a CJK/emoji title used to raise and 500.
    base = re.sub(r"[^\w.-]+", "_", title or "artifact", flags=re.ASCII).strip("._") or "artifact"
    return f"{base}.{extension}"


_ALIASES = {
    "markdown": "md",
    "htm": "html",
    "word": "docx",
    "powerpoint": "pptx",
    "image": "png",
}


def normalize_format(fmt: str) -> str:
    normalized = fmt.lower().lstrip(".")
    return _ALIASES.get(normalized, normalized)


def export_bytes(artifact: dict[str, Any], fmt: str) -> tuple[bytes, str, str]:
    """Return ``(bytes, extension, media_type)`` for an artifact export."""
    normalized = normalize_format(fmt)
    if normalized not in _FORMATS:
        raise ValueError(f"Unsupported export format: {fmt}")
    artifact_type = str(artifact.get("type") or "code")
    title = str(artifact.get("title") or "Artifact")
    content = str(artifact.get("content") or "")

    if normalized == "md":
        extension, media = _FORMATS[normalized]
        if artifact_type in {"markdown", "document", "table", "slide-outline"}:
            text = content
        else:
            text = f"# {title}\n\n```{artifact.get('language') or artifact_type}\n{content}\n```\n"
        return text.encode("utf-8"), extension, media
    if normalized == "html":
        extension, media = _FORMATS[normalized]
        return _html_document(title, content, artifact_type).encode("utf-8"), extension, media
    if normalized == "pdf":
        extension, media = _FORMATS[normalized]
        return _pdf_bytes(title, content, artifact_type), extension, media
    if normalized == "docx":
        extension, media = _FORMATS[normalized]
        return _docx_bytes(title, content), extension, media
    if normalized == "pptx":
        extension, media = _FORMATS[normalized]
        return _pptx_bytes(title, content, artifact_type), extension, media
    extension, media = _FORMATS["png"]
    return _png_bytes(title, content), extension, media


def store_export(
    *,
    artifact_id: str,
    fmt: str,
    data: bytes,
    project_id: str = "",
) -> Path:
    """Persist an exported binary in the project (or global) artifact folder."""
    from palimind.projects.store import project_dir
    from palimind.security.tokens import palimind_home

    extension = _FORMATS[normalize_format(fmt)][0]
    if project_id:
        root = project_dir(project_id) / "artifacts" / "exports"
    else:
        root = palimind_home() / "artifacts" / "exports"
    root.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", artifact_id)[:80] or "artifact"
    path = root / f"{safe_id}.{extension}"
    path.write_bytes(data)
    return path
