"""
Hierarchical, section-aware document chunker.

Replaces the flat character-count chunker in ``ingestion/chunker.py`` for
analytical workloads (financial filings, reports, research papers).

Key improvements over the legacy chunker:
* Splits on section boundaries (Item 1A, PART II, Markdown headings) first.
* Detects and preserves table chunks separately so numeric data is not
  fragmented across chunk boundaries.
* Tags every chunk with rich metadata: section_title, parent_section,
  doc_year, doc_type, entity_name, page_number, word_count, token_estimate.
* Falls back to the legacy word-boundary split within each section so
  chunk sizes remain controllable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Data structures ────────────────────────────────────────────────────────────


@dataclass
class DocumentMeta:
    path: str
    doc_year: int | None = None
    doc_type: str = "other"
    entity_name: str = ""
    total_pages: int | None = None


@dataclass
class RichChunk:
    content: str
    chunk_type: str  # "text" | "table" | "caption" | "heading"
    chunk_index: int
    section_title: str = ""
    subsection: str = ""
    parent_section: str = ""
    main_section: str = ""  # Top-level SEC section (e.g. "Item 1 Business", "Item 1A Risk Factors")
    page_number: int | None = None
    doc_year: int | None = None
    fiscal_year: int | None = None  # Alias for doc_year
    doc_type: str = "other"
    entity_name: str = ""
    word_count: int = 0
    token_estimate: int = 0
    file_path: str = ""
    media_start_ts: float | None = None  # Video/audio transcript chunk start (seconds)
    media_end_ts: float | None = None  # Video/audio transcript chunk end (seconds)
    # Text actually sent to the embedding model. It carries a short context
    # header (document + section + page) so a bare child chunk is not embedded
    # out of context. ``content`` stays clean for display, FTS and citations.
    embed_text: str = ""

    def __post_init__(self):
        if self.fiscal_year is None and self.doc_year is not None:
            self.fiscal_year = self.doc_year
        elif self.fiscal_year is not None and self.doc_year is None:
            self.doc_year = self.fiscal_year


# ── Section pattern matchers ───────────────────────────────────────────────────

# SEC filing sections: "Item 1A.", "PART II", "NOTE 3"
_SEC_ITEM = re.compile(
    r"^(Item\s+\d+[A-Za-z]?\.?\s+[A-Za-z].{3,80})$",
    re.MULTILINE,
)
_SEC_PART = re.compile(
    r"^(PART\s+[IVXivx]+\.?\s*[A-Za-z].{0,80})$",
    re.MULTILINE | re.IGNORECASE,
)
_MD_HEADING = re.compile(
    r"^(#{1,3})\s+(.{3,100})$",
    re.MULTILINE,
)
# Numbered document headings: "1.2.4 System Design and Development Review (SDDR)".
# PDF text often keeps these on their own line even when no Markdown/SEC
# pattern matches, and without them every chunk inherits one giant section.
_NUMBERED_HEADING = re.compile(
    r"^(\d+(?:\.\d+){1,3}\.?\s+[A-Z][A-Za-z0-9&,'’()\- ]{3,90})$",
    re.MULTILINE,
)
_ALLCAPS_HEADING = re.compile(
    r"^([A-Z][A-Z\s\-]{5,60})$",
    re.MULTILINE,
)

# Table detection: markdown tables or runs of numeric data
_MD_TABLE = re.compile(
    r"(\|[^\n]+\|[ \t]*\n)+(\|[-:| ]+\|[ \t]*\n)(\|[^\n]+\|[ \t]*\n)*",
)
# Dense numeric lines (financial tables in plain text)
_NUMERIC_TABLE = re.compile(
    r"(^[ \t]*[\w\s,\-–—()\$%]+?\s{2,}[\d\s,\.\-–—()\$%]{5,}$\n?){3,}",
    re.MULTILINE,
)

# Year extractor from filenames
_YEAR_IN_FILENAME = re.compile(r"(20\d{2})")

# Page markers emitted by the PDF/PPTX parsers ("[Page 12]").
_PAGE_MARKER = re.compile(r"^[ \t]*\[Page (\d+)\][ \t]*$", re.MULTILINE)

# Document type heuristics (general-purpose, not domain-specific)
_DOCTYPE_PATTERNS = [
    (re.compile(r"annual\s+report", re.IGNORECASE), "report"),
    (re.compile(r"quarterly\s+report", re.IGNORECASE), "report"),
    (re.compile(r"financial\s+(statement|report)", re.IGNORECASE), "report"),
    (re.compile(r"invoice", re.IGNORECASE), "invoice"),
    (re.compile(r"contract|agreement", re.IGNORECASE), "contract"),
    (re.compile(r"presentation|slides?", re.IGNORECASE), "presentation"),
    (re.compile(r"memo|memorandum", re.IGNORECASE), "memo"),
    (re.compile(r"letter", re.IGNORECASE), "letter"),
    (re.compile(r"manual|handbook|guide", re.IGNORECASE), "manual"),
    (re.compile(r"research|paper|whitepaper", re.IGNORECASE), "paper"),
    (re.compile(r"transcript", re.IGNORECASE), "transcript"),
]


# ── Public helpers ─────────────────────────────────────────────────────────────


def extract_doc_year(filename: str, text_sample: str = "") -> int | None:
    """
    Try to extract a 4-digit year (20xx) from the filename first,
    then from the first 2000 characters of document text.
    """
    for source in [filename, text_sample[:2000]]:
        m = _YEAR_IN_FILENAME.search(source)
        if m:
            year = int(m.group(1))
            if 2000 <= year <= 2050:
                return year
    return None


def extract_doc_type(filename: str, text_sample: str = "") -> str:
    """
    Detect the document type from the filename or early document text.
    Returns a short string like '10-K', '10-Q', 'earnings_call', or 'other'.
    """
    for source in [filename, text_sample[:1000]]:
        for pattern, label in _DOCTYPE_PATTERNS:
            if pattern.search(source):
                return label
    return "other"


def extract_entity_name(text_sample: str) -> str:
    """
    Very lightweight entity extraction — looks for common annual report
    patterns like "Apple Inc." or "APPLE INC" near the start of a document.
    Returns an empty string if nothing found.
    """
    # Look for "Company Name Inc.", "Company Name Corp.", etc.
    m = re.search(
        r"\b([A-Z][a-zA-Z\s]{2,30}(?:Inc\.|Corp\.|Corporation|Ltd\.|LLC|PLC|Company))",
        text_sample[:3000],
    )
    if m:
        return m.group(1).strip()
    return ""


# ── Internal helpers ───────────────────────────────────────────────────────────


def _split_by_sections_with_offsets(
    text: str,
) -> list[tuple[str, str, str, str, int]]:
    """
    Return (section_title, subsection, main_section, section_text, start_offset)
    tuples, preserving order.

    ``start_offset`` is the absolute character offset of *section_text* inside
    *text*, which lets the caller map a child chunk back to its source page.
    Tries SEC patterns first, falls back to Markdown headings, then
    ALLCAPS headings, then treats the whole text as one section.

    ``main_section`` tracks the current top-level SEC heading (Item/PART)
    so that every chunk can be traced back to its containing section.
    """
    # Collect all candidate split points with their positions and labels
    splits: list[tuple[int, int, str, int]] = []  # (start, end_of_heading, label, level)

    for m in _SEC_PART.finditer(text):
        label = m.group(0).strip()
        splits.append((m.start(), m.end(), label, 1))

    for m in _SEC_ITEM.finditer(text):
        label = m.group(0).strip()
        splits.append((m.start(), m.end(), label, 2))

    for m in _MD_HEADING.finditer(text):
        hashes = m.group(1)
        label = m.group(2).strip()
        splits.append((m.start(), m.end(), label, 2 + len(hashes)))  # level 3, 4, 5

    for m in _NUMBERED_HEADING.finditer(text):
        label = m.group(1).strip()
        splits.append((m.start(), m.end(), label, 2))

    for m in _ALLCAPS_HEADING.finditer(text):
        label = m.group(0).strip()
        splits.append((m.start(), m.end(), label, 6))

    if not splits:
        return [("Preamble", "", "", text, 0)]

    # Sort by position, deduplicate overlapping spans
    splits.sort(key=lambda x: x[0])
    deduped: list[tuple[int, int, str, int]] = []
    last_end = -1
    for start, end, label, level in splits:
        if start >= last_end:
            deduped.append((start, end, label, level))
            last_end = end

    sections: list[tuple[str, str, str, str, int]] = []

    # Text before first heading
    first_start = deduped[0][0]
    if first_start > 0:
        preamble = text[:first_start].strip()
        if preamble:
            sections.append(("Preamble", "", "", preamble, 0))

    active_section = ""
    active_subsection = ""
    active_main_section = ""
    active_level = 0

    for i, (start, end, label, level) in enumerate(deduped):
        # Determine section vs subsection based on level
        if level <= 2:
            # Top-level: SEC Part/Item
            active_main_section = label
            active_section = label
            active_subsection = ""
            active_level = level
        elif active_section and level > active_level:
            # Subsection within current section
            active_subsection = label
            # Keep active_section as the containing section
        else:
            # Equal or lower level than active — becomes new section
            active_section = label
            active_subsection = ""
            active_level = level
            # If this is also a top-level SEC heading, update main_section too
            if level <= 2:
                active_main_section = label

        # Section text goes from end-of-heading to start of next heading
        next_start = deduped[i + 1][0] if i + 1 < len(deduped) else len(text)
        raw_slice = text[end:next_start]
        section_text = raw_slice.strip()
        if section_text:
            leading_ws = len(raw_slice) - len(raw_slice.lstrip())
            raw_slice_start = end + leading_ws
            sections.append(
                (
                    active_section,
                    active_subsection,
                    active_main_section,
                    section_text,
                    raw_slice_start,
                )
            )

    return sections if sections else [("Preamble", "", "", text, 0)]


def _split_by_sections(text: str) -> list[tuple[str, str, str, str]]:
    """Backward-compatible wrapper returning 4-tuples (without offsets)."""
    return [(a, b, c, d) for a, b, c, d, _ in _split_by_sections_with_offsets(text)]


def _extract_tables(text: str) -> tuple[list[tuple[str, int]], str]:
    """
    Extract table blocks from *text*.
    Returns (list of (table_text, start_offset), remaining_text_with_tables_removed).
    """
    tables: list[tuple[str, int]] = []
    remaining = text

    # Markdown tables first — offsets are captured against the original text.
    for m in _MD_TABLE.finditer(text):
        table_text = m.group(0).strip()
        if table_text:
            tables.append((table_text, m.start()))
    remaining = _MD_TABLE.sub("\n", remaining)

    # Numeric dense tables. ``find`` maps the match back to the original text
    # (the markdown-substitution step can shift offsets).
    for m in _NUMERIC_TABLE.finditer(remaining):
        table_text = m.group(0).strip()
        if table_text and len(table_text) > 40:
            pos = text.find(table_text)
            tables.append((table_text, pos if pos >= 0 else 0))
    remaining = _NUMERIC_TABLE.sub("\n", remaining)

    return tables, remaining.strip()


def _character_chunk_spans(
    text: str, chunk_size: int, chunk_overlap: int
) -> list[tuple[int, int, str]]:
    """Word-boundary character chunker returning ``(start, end, chunk)`` spans.

    Offsets are relative to *text* so callers can map a chunk back to its
    source page. The chunk string preserves the legacy ``strip()`` behaviour.
    """
    if not text:
        return []
    # A non-positive size would never advance ``start`` → infinite loop.
    chunk_size = max(1, chunk_size)
    spans: list[tuple[int, int, str]] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        prev_start = start
        end = start + chunk_size

        if end >= text_length:
            chunk = text[start:].strip()
            if chunk:
                spans.append((start, text_length, chunk))
            break

        # Snap to word boundary within ±50 chars of end
        # (clamp at 0: a negative slice start would wrap to the text's tail)
        lo = max(0, end - 50)
        m = re.search(r"\s+", text[lo : end + 50])
        if m:
            boundary = lo + m.start()
            if boundary > start:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            spans.append((start, end, chunk))

        start = end - chunk_overlap
        if start <= prev_start:
            start = end

    return spans


def _character_chunk(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Legacy word-boundary character chunker (kept as the within-section split).
    """
    return [chunk for _, _, chunk in _character_chunk_spans(text, chunk_size, chunk_overlap)]


def _page_offsets(text: str) -> list[tuple[int, int]]:
    """Return ``(char_offset, page_number)`` for every ``[Page N]`` marker."""
    return [(m.start(), int(m.group(1))) for m in _PAGE_MARKER.finditer(text)]


def _page_for_offset(offsets: list[tuple[int, int]], pos: int) -> int | None:
    """Return the page a character offset belongs to (last marker before it)."""
    page: int | None = None
    for start, number in offsets:
        if start > pos:
            break
        page = number
    return page


def _strip_page_markers(text: str) -> str:
    """Remove parser-emitted ``[Page N]`` lines from display content."""
    cleaned = _PAGE_MARKER.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _split_pages(text: str) -> list[tuple[int | None, int, str]]:
    """Split text into ``(page_number, start_offset, text)`` page segments.

    Chunks are built per page so a citation always names the page its passage
    starts on instead of a multi-page blob labelled with its first page.
    """
    segments: list[tuple[int | None, int, str]] = []
    last_page: int | None = None
    last_start = 0
    for match in _PAGE_MARKER.finditer(text):
        if last_page is not None and match.start() > last_start:
            segments.append((last_page, last_start, text[last_start : match.start()]))
        elif last_page is None and match.start() > 0:
            segments.append((None, 0, text[: match.start()]))
        last_page = int(match.group(1))
        last_start = match.end()
    if last_page is not None:
        segments.append((last_page, last_start, text[last_start:]))
    if not segments:
        segments.append((None, 0, text))
    return segments


def _context_header(
    doc_meta: DocumentMeta,
    main_section: str,
    section_title: str,
    subsection: str,
    page_number: int | None,
) -> str:
    """Short retrieval-only header that anchors a child chunk in its document.

    It is embedded with the chunk but never shown to the LLM (``content`` stays
    clean), so a passage such as "revenue grew 12%" is still retrievable as
    "Apple 10-K 2023 · Item 7 · MD&A · page 42 · revenue grew 12%".
    """
    parts: list[str] = []
    name = _document_title(doc_meta.path)
    if name:
        parts.append(name)
    section_path = " > ".join(
        piece.strip()
        for piece in (main_section, subsection, section_title)
        if piece and piece.strip()
    )
    if section_path:
        parts.append(section_path)
    if page_number is not None:
        parts.append(f"page {page_number}")
    meta_bits = []
    if doc_meta.doc_type and doc_meta.doc_type != "other":
        meta_bits.append(doc_meta.doc_type)
    if doc_meta.doc_year:
        meta_bits.append(str(doc_meta.doc_year))
    if doc_meta.entity_name:
        meta_bits.append(doc_meta.entity_name)
    if meta_bits:
        parts.append(" · ".join(meta_bits))
    return " | ".join(parts)


def _document_title(path: str) -> str:
    """Human-friendly document name from a relative path (no extension)."""
    name = (path or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, _ext = name.rpartition(".")
    return stem if dot and stem else name


def _make_embed_text(content: str, header: str) -> str:
    if not header:
        return content
    # Keep the header short so it cannot dominate the embedded passage.
    return f"{header[:300]}\n{content}"


def _token_estimate(text: str) -> int:
    """Rough token count estimate (1 token ≈ 4 chars)."""
    return max(1, len(text) // 4)


def _prefix_section(content: str, main_section: str, section_title: str) -> str:
    """Prepend the section heading to a chunk so FTS/embeddings see it."""
    heading = (main_section or section_title).strip()
    if not heading:
        return content
    if content.startswith(heading) or content.startswith(f"[{heading}]"):
        return content
    return f"{heading}\n{content}"


# ── Public API ─────────────────────────────────────────────────────────────────


def _make_chunk(
    chunk_content: str,
    chunk_type: str,
    page: int | None,
    *,
    doc_meta: DocumentMeta,
    section_title: str,
    subsection: str,
    main_section: str,
    parent_section: str,
    chunk_index: int,
) -> RichChunk | None:
    """Build one child chunk (or ``None`` when only page markers remain)."""
    content = _strip_page_markers(_prefix_section(chunk_content, main_section, section_title))
    if not content.strip():
        return None
    header = _context_header(doc_meta, main_section, section_title, subsection, page)
    return RichChunk(
        content=content,
        chunk_type=chunk_type,
        chunk_index=chunk_index,
        section_title=section_title,
        subsection=subsection,
        main_section=main_section,
        parent_section=parent_section,
        page_number=page,
        doc_year=doc_meta.doc_year,
        doc_type=doc_meta.doc_type,
        entity_name=doc_meta.entity_name,
        word_count=len(content.split()),
        token_estimate=_token_estimate(content),
        file_path=doc_meta.path,
        embed_text=_make_embed_text(content, header),
    )


def rich_chunk_document(
    text: str,
    doc_meta: DocumentMeta,
    chunk_size: int = 3000,
    chunk_overlap: int = 500,
    doc_extensions: list[str] | None = None,
) -> list[RichChunk]:
    """
    Hierarchical chunker: split by section → detect tables → child-chunk text.

    Every chunk carries:
    * clean ``content`` (page markers stripped, section heading prefixed),
    * ``page_number`` recovered from the parser's ``[Page N]`` markers,
    * ``embed_text`` with a document/section/page context header.

    Child chunks stay small (``chunk_size``) for precise matching; the
    retrieval layer reassembles the parent section for the LLM.

    Returns a list of :class:`RichChunk` objects with full metadata attached.
    """
    chunks: list[RichChunk] = []
    chunk_index = 0

    # Adaptive chunking: different sizes for code vs prose vs tables
    is_code = doc_meta.path and any(
        doc_meta.path.endswith(ext)
        for ext in [".py", ".js", ".ts", ".go", ".rs", ".c", ".cpp", ".h"]
    )
    is_table_heavy = doc_meta.doc_type in ("report", "presentation")

    # Adjust child chunk size based on content type.
    adaptive_chunk_size = max(200, chunk_size)
    adaptive_overlap = max(0, chunk_overlap)
    if is_code:
        adaptive_chunk_size = max(400, chunk_size // 2)
        adaptive_overlap = min(adaptive_overlap, 60)
    elif is_table_heavy:
        # Tables need more surrounding structure per child.
        adaptive_chunk_size = max(600, chunk_size)

    section_tuples = _split_by_sections_with_offsets(text)
    doc_pages = _page_offsets(text)

    for section_title, subsection, main_section, section_text, section_offset in section_tuples:
        parent_section = main_section if main_section else section_title
        # A page marker usually sits *before* the heading that starts a section,
        # so the section inherits the page that was active at its start.
        section_page = _page_for_offset(doc_pages, section_offset)

        # Extract tables before character-chunking the prose. Offsets are
        # relative to ``section_text`` so the page lookup stays accurate.
        table_items, remaining_text = _extract_tables(section_text)
        section_pages = _page_offsets(section_text)

        def append_piece(
            piece: str,
            piece_type: str,
            piece_page: int | None,
            *,
            section_title: str = section_title,
            subsection: str = subsection,
            main_section: str = main_section,
            parent_section: str = parent_section,
        ) -> None:
            nonlocal chunk_index
            chunk = _make_chunk(
                piece,
                piece_type,
                piece_page,
                doc_meta=doc_meta,
                section_title=section_title,
                subsection=subsection,
                main_section=main_section,
                parent_section=parent_section,
                chunk_index=chunk_index,
            )
            if chunk is not None:
                chunks.append(chunk)
                chunk_index += 1

        # ── Table chunks — kept intact unless genuinely enormous ──────────
        for table_text, table_pos in table_items:
            if len(table_text.strip()) < 20:
                continue
            page = _page_for_offset(section_pages, table_pos) or section_page
            if is_table_heavy and len(table_text) > adaptive_chunk_size:
                for _start, _end, table_chunk in _character_chunk_spans(
                    table_text, adaptive_chunk_size, adaptive_overlap
                ):
                    append_piece(table_chunk, "table", page)
            else:
                append_piece(table_text, "table", page)

        # ── Prose child chunks (never split across a page boundary) ──────
        for page_number, _segment_start, segment_text in _split_pages(remaining_text):
            for _span_start, _span_end, chunk_text in _character_chunk_spans(
                segment_text, adaptive_chunk_size, adaptive_overlap
            ):
                if not chunk_text.strip():
                    continue
                append_piece(chunk_text, "text", page_number or section_page)

    return chunks


def rich_chunk_caption(caption: str, doc_meta: DocumentMeta, chunk_index: int = 0) -> RichChunk:
    """Wrap a single image caption in a RichChunk."""
    header = _context_header(doc_meta, "", "", "", None)
    return RichChunk(
        content=caption,
        chunk_type="caption",
        chunk_index=chunk_index,
        section_title="",
        subsection="",
        main_section="",
        parent_section="",
        doc_year=doc_meta.doc_year,
        doc_type=doc_meta.doc_type,
        entity_name=doc_meta.entity_name,
        word_count=len(caption.split()),
        token_estimate=_token_estimate(caption),
        file_path=doc_meta.path,
        embed_text=_make_embed_text(caption, header),
    )


# ── Legacy compatibility wrapper ───────────────────────────────────────────────


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Legacy API — returns plain strings.
    Kept for backward compatibility with any code still calling this directly.
    """
    return _character_chunk(text, chunk_size, chunk_overlap)
