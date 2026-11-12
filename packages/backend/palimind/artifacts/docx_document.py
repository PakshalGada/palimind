"""DOCX pipeline: Markdown-ish text → a styled, print-ready Word document.

The renderer deliberately does more than drop paragraphs into a blank file:

* a cover page with a typographic title block
* real heading levels with consistent colour and spacing
* bold/italic/code runs preserved inside paragraphs
* shaded callouts for block quotes
* banded tables with a repeating header row and sensible column widths
* monospaced, shaded code blocks
* header and footer with page numbers

It stays dependency-light: only ``python-docx`` and the OOXML helpers that ship
with it are used, so it works in the same environment as the PPTX pipeline.
"""

from __future__ import annotations

import datetime as _dt
import io
import re

INK = "0F172A"
BODY = "334155"
MUTED = "64748B"
LINE = "CBD5E1"
ACCENT = "2563EB"
ACCENT_DARK = "1D4ED8"
SURFACE = "F1F5F9"
CODE_BG = "F6F8FA"
WHITE = "FFFFFF"

BODY_FONT = "Aptos"
HEAD_FONT = "Aptos Display"
MONO_FONT = "Cascadia Mono"

_BULLET_RE = re.compile(r"^(\s*)[-*+•]\s+(.*)$")
_NUMBER_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_RULE_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_FENCE_RE = re.compile(r"^\s*```")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")

_INLINE_RE = re.compile(
    r"(\*\*|__)(.+?)\1"
    r"|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"
    r"|`([^`]+)`"
    r"|~~(.+?)~~"
    r"|\[([^\]]+)\]\(([^)]+)\)"
)


# ── OOXML helpers ──────────────────────────────────────────────────────────
def _set_run_font(
    run, *, name: str | None = None, size: float | None = None, color: str | None = None
) -> None:
    from docx.shared import Pt, RGBColor

    if name:
        run.font.name = name
        try:
            from docx.oxml.ns import qn

            run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
        except Exception:
            pass
    if size is not None:
        run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def _shade(element, fill: str) -> None:
    """Apply ``w:shd`` to a paragraph or table-cell element."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    props = (
        element.get_or_add_tcPr()
        if hasattr(element, "get_or_add_tcPr")
        else element.get_or_add_pPr()
    )
    existing = props.find(qn("w:shd"))
    if existing is not None:
        props.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    props.append(shd)


def _para_border(
    paragraph, *, side: str = "bottom", color: str = LINE, size: int = 8, space: int = 6
) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    p_pr = paragraph._p.get_or_add_pPr()
    borders = p_pr.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        p_pr.append(borders)
    border = OxmlElement(f"w:{side}")
    border.set(qn("w:val"), "single")
    border.set(qn("w:sz"), str(size))
    border.set(qn("w:space"), str(space))
    border.set(qn("w:color"), color)
    borders.append(border)


def _para_spacing(
    paragraph, *, before: float | None = None, after: float | None = None, line: float | None = None
) -> None:
    from docx.shared import Pt

    fmt = paragraph.paragraph_format
    if before is not None:
        fmt.space_before = Pt(before)
    if after is not None:
        fmt.space_after = Pt(after)
    if line is not None:
        fmt.line_spacing = line


def _page_field(paragraph, instruction: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), instruction)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


# ── inline Markdown ────────────────────────────────────────────────────────
def _add_inline(paragraph, text: str, *, size: float = 10.5, color: str = BODY) -> None:
    """Add *text* to *paragraph* while preserving inline Markdown styling."""
    position = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > position:
            run = paragraph.add_run(text[position : match.start()])
            _set_run_font(run, name=BODY_FONT, size=size, color=color)
        bold, italic, code, strike, link_text = "", "", "", "", ""
        if match.group(2) is not None:
            bold = match.group(2)
        elif match.group(3) is not None:
            italic = match.group(3)
        elif match.group(4) is not None:
            code = match.group(4)
        elif match.group(5) is not None:
            strike = match.group(5)
        else:
            link_text = match.group(6) or ""
        if bold:
            run = paragraph.add_run(bold)
            run.bold = True
            _set_run_font(run, name=BODY_FONT, size=size, color=INK)
        elif italic:
            run = paragraph.add_run(italic)
            run.italic = True
            _set_run_font(run, name=BODY_FONT, size=size, color=color)
        elif code:
            run = paragraph.add_run(code)
            run.font.name = MONO_FONT
            _set_run_font(run, name=MONO_FONT, size=max(8.5, size - 0.6), color=ACCENT_DARK)
        elif strike:
            run = paragraph.add_run(strike)
            run.font.strike = True
            _set_run_font(run, name=BODY_FONT, size=size, color=MUTED)
        else:
            run = paragraph.add_run(link_text)
            run.font.underline = True
            _set_run_font(run, name=BODY_FONT, size=size, color=ACCENT)
        position = match.end()
    if position < len(text):
        run = paragraph.add_run(text[position:])
        _set_run_font(run, name=BODY_FONT, size=size, color=color)


# ── tables ─────────────────────────────────────────────────────────────────
def _table_rows(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    index = start
    while index < len(lines):
        line = lines[index].strip()
        if not (line.startswith("|") and line.endswith("|")):
            break
        if _TABLE_SEP_RE.match(line):
            index += 1
            continue
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
        index += 1
    return rows, index


def _set_cell_width(cell, width_emu: int) -> None:
    from docx.shared import Emu

    cell.width = Emu(width_emu)


def _cell_margins(
    table, top: int = 70, bottom: int = 70, left: int = 110, right: int = 110
) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tbl_pr = table._tbl.tblPr
    margins = OxmlElement("w:tblCellMar")
    for side, value in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")
        margins.append(node)
    tbl_pr.append(margins)


def _table_borders(table, color: str = LINE) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "4")
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)
        borders.append(node)
    tbl_pr.append(borders)


def _add_table(document, rows: list[list[str]]) -> None:
    from docx.shared import Inches

    if not rows:
        return
    columns = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=columns)
    table.style = "Table Grid"
    table.autofit = False
    _table_borders(table)
    _cell_margins(table)
    usable = 6.7
    width = Inches(usable / max(1, columns))
    for row_index, row in enumerate(rows):
        for column in range(columns):
            cell = table.cell(row_index, column)
            _set_cell_width(cell, int(width))
            text = row[column] if column < len(row) else ""
            paragraph = cell.paragraphs[0]
            paragraph.text = ""
            _para_spacing(paragraph, before=1, after=1, line=1.05)
            if row_index == 0:
                _add_inline(paragraph, text, size=9.5, color=WHITE)
                for run in paragraph.runs:
                    run.bold = True
                    run.font.color.rgb = _rgb(WHITE)
                _shade(cell._tc, ACCENT)
                # Repeat the header row when a table crosses a page boundary.
                if column == 0:
                    from docx.oxml import OxmlElement
                    from docx.oxml.ns import qn

                    tr_pr = cell._tc.getparent().get_or_add_trPr()
                    header = OxmlElement("w:tblHeader")
                    header.set(qn("w:val"), "true")
                    tr_pr.append(header)
            else:
                _add_inline(paragraph, text, size=9.5)
                if row_index % 2 == 0:
                    _shade(cell._tc, SURFACE)
                if column == 0:
                    for run in paragraph.runs:
                        run.bold = True
                        run.font.color.rgb = _rgb(INK)
    document.add_paragraph("")


def _rgb(value: str):
    from docx.shared import RGBColor

    return RGBColor.from_string(value)


# ── styles and cover ───────────────────────────────────────────────────────
def _configure_styles(document) -> None:
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Inches, Pt, RGBColor

    normal = document.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor.from_string(BODY)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    normal.paragraph_format.line_spacing = 1.14

    for name, size, color, before, after in (
        ("Title", 30, INK, 0, 10),
        ("Heading 1", 19, INK, 18, 6),
        ("Heading 2", 14.5, INK, 14, 4),
        ("Heading 3", 12, ACCENT_DARK, 10, 3),
        ("Heading 4", 10.5, MUTED, 8, 2),
    ):
        try:
            style = document.styles[name]
        except KeyError:
            continue
        style.font.name = HEAD_FONT if name != "Title" else HEAD_FONT
        style.font.size = Pt(size)
        style.font.bold = name not in {"Heading 4"}
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = name != "Title"
        try:
            from docx.oxml.ns import qn

            style.element.rPr.rFonts.set(qn("w:eastAsia"), HEAD_FONT)
        except Exception:
            pass

    for section in document.sections:
        section.top_margin = Inches(0.92)
        section.bottom_margin = Inches(0.92)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)


def _add_cover(document, title: str, subtitle: str = "") -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK

    eyebrow = document.add_paragraph()
    _para_spacing(eyebrow, before=48, after=4)
    run = eyebrow.add_run("DOCUMENT")
    _set_run_font(run, name=BODY_FONT, size=9.5, color=ACCENT)
    run.bold = True

    heading = document.add_paragraph(style="Title")
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _para_spacing(heading, before=2, after=10)
    run = heading.add_run(title or "Document")
    _set_run_font(run, name=HEAD_FONT, size=30, color=INK)
    run.bold = True

    accent = document.add_paragraph()
    _para_spacing(accent, before=0, after=18)
    _para_border(accent, side="bottom", color=ACCENT, size=18, space=1)

    if subtitle:
        sub = document.add_paragraph()
        _para_spacing(sub, before=8, after=8)
        _add_inline(sub, subtitle, size=12.5, color=MUTED)

    meta = document.add_paragraph()
    _para_spacing(meta, before=14, after=0)
    run = meta.add_run(f"{_dt.date.today().strftime('%B %d, %Y')}  ·  Prepared with PaliMind")
    _set_run_font(run, name=BODY_FONT, size=9, color=MUTED)

    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _add_header_footer(document, title: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    for section in document.sections:
        # A cover page should not repeat the running header or folio.
        section.different_first_page_header_footer = True
        first_header = section.first_page_header
        first_header.paragraphs[0].text = ""
        first_footer = section.first_page_footer
        first_footer.paragraphs[0].text = ""

        # Start numbering after the cover so the first content page is page 1.
        pg_num = OxmlElement("w:pgNumType")
        pg_num.set(qn("w:start"), "0")
        section._sectPr.append(pg_num)

        header = section.header
        paragraph = header.paragraphs[0]
        paragraph.text = ""
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = paragraph.add_run(title[:80])
        _set_run_font(run, name=BODY_FONT, size=8.5, color=MUTED)
        _para_border(paragraph, side="bottom", color=LINE, size=4, space=4)

        footer = section.footer
        footer_para = footer.paragraphs[0]
        footer_para.text = ""
        footer_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = footer_para.add_run("PaliMind  ·  ")
        _set_run_font(run, name=BODY_FONT, size=8, color=MUTED)
        _page_field(footer_para, "PAGE")


# ── body rendering ─────────────────────────────────────────────────────────
def _add_code_block(document, lines: list[str]) -> None:
    from docx.enum.text import WD_LINE_SPACING

    if not lines:
        return
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = 0
    paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    paragraph.paragraph_format.space_before = 4
    paragraph.paragraph_format.space_after = 8
    _shade(paragraph._p, CODE_BG)
    _para_border(paragraph, side="left", color="94A3B8", size=12, space=8)
    for index, line in enumerate(lines):
        run = paragraph.add_run(line or " ")
        _set_run_font(run, name=MONO_FONT, size=8.8, color="1F2937")
        if index < len(lines) - 1:
            run.add_break()


def _add_quote(document, text: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.left_indent = 180
    paragraph.paragraph_format.right_indent = 80
    _para_spacing(paragraph, before=4, after=8)
    _shade(paragraph._p, SURFACE)
    _para_border(paragraph, side="left", color=ACCENT, size=18, space=8)
    _add_inline(paragraph, text, size=10.5, color=INK)


def _add_list_item(document, text: str, level: int, *, numbered: bool) -> None:
    from docx.shared import Inches

    base = "List Number" if numbered else "List Bullet"
    style = base if level == 0 else f"{base} 2"
    try:
        paragraph = document.add_paragraph(style=style)
    except KeyError:
        paragraph = document.add_paragraph(style=base)
    paragraph.paragraph_format.left_indent = Inches(0.28 + level * 0.28)
    paragraph.paragraph_format.first_line_indent = Inches(-0.18)
    _para_spacing(paragraph, before=0, after=2, line=1.12)
    # LibreOffice renders the List Number marker tight against the first word;
    # a leading thin space keeps it readable in both LibreOffice and Word.
    _add_inline(paragraph, f"\u2009{text}" if numbered else text)


def _add_heading(document, level: int, text: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    style = f"Heading {min(4, max(1, level))}"
    try:
        paragraph = document.add_paragraph(style=style)
    except KeyError:
        paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _add_inline(
        paragraph,
        text,
        size={1: 19, 2: 14.5, 3: 12, 4: 10.5}.get(level, 10.5),
        color=INK if level <= 2 else ACCENT_DARK,
    )
    for run in paragraph.runs:
        run.bold = True
        run.font.name = HEAD_FONT
    if level == 1:
        _para_border(paragraph, side="bottom", color=LINE, size=6, space=4)


def _add_paragraph(document, text: str) -> None:
    paragraph = document.add_paragraph()
    _para_spacing(paragraph, before=0, after=6, line=1.14)
    _add_inline(paragraph, text)


def build_docx(title: str, content: str = "") -> bytes:
    """Turn Markdown-ish *content* into a styled .docx file."""
    from docx import Document

    document = Document()
    _configure_styles(document)
    _add_header_footer(document, title or "Document")

    lines = str(content or "").splitlines()
    # The first non-empty line often repeats the title; do not print it twice
    # on the page after the cover. The first real body sentence becomes the
    # cover subtitle so the title page has a point of view.
    cover_subtitle = ""
    seen_heading = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            if len(heading_match.group(1)) == 1:
                seen_heading = True
            continue
        if _RULE_RE.match(stripped) or stripped.startswith("|") or _BULLET_RE.match(stripped):
            continue
        candidate = re.sub(r"[*_`#>]", "", stripped).strip()
        if not candidate:
            continue
        sentence = re.split(r"(?<=[.!?])\s+", candidate, maxsplit=1)[0]
        cover_subtitle = sentence[:180].rstrip()
        if seen_heading:
            break
        break
    _add_cover(document, title or "Document", cover_subtitle)

    in_code = False
    code_lines: list[str] = []
    index = 0
    while index < len(lines):
        raw = lines[index].rstrip()
        index += 1

        if _FENCE_RE.match(raw):
            if in_code:
                _add_code_block(document, code_lines)
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(raw)
            continue

        line = raw.strip()
        if not line:
            continue

        if line.startswith("|") and line.endswith("|"):
            rows, index = _table_rows(lines, index - 1)
            if rows:
                _add_table(document, rows)
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            text = heading.group(2).strip()
            if len(heading.group(1)) == 1 and text and title and _same_title(text, title):
                continue
            _add_heading(document, len(heading.group(1)), text)
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            _add_quote(document, quote.group(1))
            continue

        bullet = _BULLET_RE.match(raw)
        if bullet:
            level = min(2, len(bullet.group(1)) // 2)
            _add_list_item(document, bullet.group(2), level, numbered=False)
            continue

        numbered = _NUMBER_RE.match(raw)
        if numbered:
            level = min(2, len(numbered.group(1)) // 2)
            _add_list_item(document, numbered.group(2), level, numbered=True)
            continue

        if _RULE_RE.match(line):
            continue

        _add_paragraph(document, line)

    if in_code and code_lines:
        _add_code_block(document, code_lines)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _same_title(a: str, b: str) -> bool:
    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    left, right = norm(a), norm(b)
    return bool(left and right and (left == right or left in right or right in left))


def validate_docx(data: bytes) -> list[str]:
    """Cheap structural checks used by the office pipeline."""
    try:
        from docx import Document

        document = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        return [f"not a readable Word document: {exc}"]
    warnings: list[str] = []
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    if not text.strip() and not document.tables:
        warnings.append("document has no body text")
    return warnings
