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

# Document type heuristics
_DOCTYPE_PATTERNS = [
    (re.compile(r"10-?k\b", re.IGNORECASE), "10-K"),
    (re.compile(r"10-?q\b", re.IGNORECASE), "10-Q"),
    (re.compile(r"8-?k\b", re.IGNORECASE), "8-K"),
    (re.compile(r"annual\s+report", re.IGNORECASE), "annual_report"),
    (re.compile(r"earnings\s+(call|transcript)", re.IGNORECASE), "earnings_call"),
    (re.compile(r"proxy\s+(statement|report)", re.IGNORECASE), "proxy"),
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


def _split_by_sections(text: str) -> list[tuple[str, str, str, str]]:
    """
    Return (section_title, subsection, main_section, section_text) tuples, preserving order.
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

    for m in _ALLCAPS_HEADING.finditer(text):
        label = m.group(0).strip()
        splits.append((m.start(), m.end(), label, 6))

    if not splits:
        return [("Preamble", "", "", text)]

    # Sort by position, deduplicate overlapping spans
    splits.sort(key=lambda x: x[0])
    deduped: list[tuple[int, int, str, int]] = []
    last_end = -1
    for start, end, label, level in splits:
        if start >= last_end:
            deduped.append((start, end, label, level))
            last_end = end

    sections: list[tuple[str, str, str, str]] = []

    # Text before first heading
    first_start = deduped[0][0]
    if first_start > 0:
        preamble = text[:first_start].strip()
        if preamble:
            sections.append(("Preamble", "", "", preamble))

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
        section_text = text[end:next_start].strip()
        if section_text:
            sections.append((active_section, active_subsection, active_main_section, section_text))

    return sections if sections else [("Preamble", "", "", text)]


def _extract_tables(text: str) -> tuple[list[str], str]:
    """
    Extract table blocks from *text*.
    Returns (list_of_table_texts, remaining_text_with_tables_removed).
    """
    tables: list[str] = []
    remaining = text

    # Markdown tables first
    for m in _MD_TABLE.finditer(text):
        table_text = m.group(0).strip()
        if table_text:
            tables.append(table_text)
    remaining = _MD_TABLE.sub("\n", remaining)

    # Numeric dense tables
    for m in _NUMERIC_TABLE.finditer(remaining):
        table_text = m.group(0).strip()
        if table_text and len(table_text) > 40:
            tables.append(table_text)
    remaining = _NUMERIC_TABLE.sub("\n", remaining)

    return tables, remaining.strip()


def _character_chunk(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Legacy word-boundary character chunker (kept as the within-section split).
    """
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        prev_start = start
        end = start + chunk_size

        if end >= text_length:
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Snap to word boundary within ±50 chars of end
        m = re.search(r"\s+", text[end - 50 : end + 50])
        if m:
            boundary = (end - 50) + m.start()
            if boundary > start:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - chunk_overlap
        if start <= prev_start:
            start = end

    return chunks


def _token_estimate(text: str) -> int:
    """Rough token count estimate (1 token ≈ 4 chars)."""
    return max(1, len(text) // 4)


# ── Public API ─────────────────────────────────────────────────────────────────


def rich_chunk_document(
    text: str,
    doc_meta: DocumentMeta,
    chunk_size: int = 3000,
    chunk_overlap: int = 500,
    doc_extensions: list[str] | None = None,
) -> list[RichChunk]:
    """
    Hierarchical chunker: split by section → detect tables → character-chunk text.

    For 10-K / financial filings, uses larger chunks (3000 chars, 500 overlap)
    to preserve complete subsections.

    Returns a list of :class:`RichChunk` objects with full metadata attached.
    """
    chunks: list[RichChunk] = []
    chunk_index = 0

    # Use larger chunks for financial documents
    is_financial = doc_meta.doc_type in ("10-K", "10-Q", "annual_report")
    if is_financial:
        chunk_size = max(chunk_size, 3000)
        chunk_overlap = max(chunk_overlap, 500)

    section_tuples = _split_by_sections(text)

    for section_title, subsection, main_section, section_text in section_tuples:
        # Extract tables before character-chunking the prose
        table_texts, remaining_text = _extract_tables(section_text)

        # Table chunks — preserve intact
        for table_text in table_texts:
            if len(table_text.strip()) < 20:
                continue
            wc = len(table_text.split())
            chunks.append(
                RichChunk(
                    content=table_text,
                    chunk_type="table",
                    chunk_index=chunk_index,
                    section_title=section_title,
                    subsection=subsection,
                    main_section=main_section,
                    parent_section=main_section if main_section else section_title,
                    page_number=None,
                    doc_year=doc_meta.doc_year,
                    doc_type=doc_meta.doc_type,
                    entity_name=doc_meta.entity_name,
                    word_count=wc,
                    token_estimate=_token_estimate(table_text),
                    file_path=doc_meta.path,
                )
            )
            chunk_index += 1

        # Prose chunks within this section
        text_chunks = _character_chunk(remaining_text, chunk_size, chunk_overlap)
        for chunk_text in text_chunks:
            if not chunk_text.strip():
                continue
            wc = len(chunk_text.split())
            chunks.append(
                RichChunk(
                    content=chunk_text,
                    chunk_type="text",
                    chunk_index=chunk_index,
                    section_title=section_title,
                    subsection=subsection,
                    main_section=main_section,
                    parent_section=main_section if main_section else section_title,
                    page_number=None,
                    doc_year=doc_meta.doc_year,
                    doc_type=doc_meta.doc_type,
                    entity_name=doc_meta.entity_name,
                    word_count=wc,
                    token_estimate=_token_estimate(chunk_text),
                    file_path=doc_meta.path,
                )
            )
            chunk_index += 1

    return chunks


def rich_chunk_caption(caption: str, doc_meta: DocumentMeta, chunk_index: int = 0) -> RichChunk:
    """Wrap a single image caption in a RichChunk."""
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
    )


# ── Legacy compatibility wrapper ───────────────────────────────────────────────


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Legacy API — returns plain strings.
    Kept for backward compatibility with any code still calling this directly.
    """
    return _character_chunk(text, chunk_size, chunk_overlap)
