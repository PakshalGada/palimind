"""
Timeline building tool.

Merges structured timeline events (from the timeline_events SQLite table)
with date-bearing chunks from semantic retrieval, then sorts everything
chronologically to produce a coherent timeline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TimelineEvent:
    event_date: str          # ISO date string or year string
    event_year: int | None
    event_text: str
    event_type: str
    source_file: str
    source_year: int | None = None  # doc_year of the filing that mentions this


@dataclass
class Timeline:
    events: list[TimelineEvent]
    query: str = ""
    time_range: tuple[int, int] | None = None

    def to_markdown(self) -> str:
        """Render the timeline as a markdown string."""
        if not self.events:
            return "No timeline events found."

        lines = ["## Timeline\n"]
        current_year: int | None = None

        for event in self.events:
            year = event.event_year
            if year != current_year:
                lines.append(f"\n### {year or 'Date Unknown'}\n")
                current_year = year

            date_prefix = f"**{event.event_date}**: " if event.event_date and event.event_date != str(year) else ""
            source = event.source_file.split("/")[-1]
            type_badge = f" `{event.event_type}`" if event.event_type != "general" else ""
            lines.append(f"- {date_prefix}{event.event_text}{type_badge} *(Source: {source})*")

        return "\n".join(lines)


# ── Date extraction helpers ────────────────────────────────────────────────────

_DATE_PATTERNS = [
    # Full ISO: 2024-09-15
    re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b"),
    # "September 15, 2024" / "15 September 2024"
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),?\s+(20\d{2})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(20\d{2})\b",
        re.IGNORECASE,
    ),
    # Q1 2024 / Q4 2023
    re.compile(r"\b(Q[1-4])\s+(20\d{2})\b", re.IGNORECASE),
    # Year only: 2024
    re.compile(r"\b(20\d{2})\b"),
]

_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _extract_date_from_text(text: str) -> tuple[str, int | None]:
    """
    Extract the first recognizable date from text.
    Returns (date_string, year_int).
    """
    # Full ISO
    m = _DATE_PATTERNS[0].search(text)
    if m:
        return m.group(0), int(m.group(1))

    # "Month DD, YYYY"
    m = _DATE_PATTERNS[1].search(text)
    if m:
        year = int(m.group(3))
        month = _MONTH_MAP.get(m.group(1).lower(), "01")
        day = m.group(2).zfill(2)
        return f"{year}-{month}-{day}", year

    # "DD Month YYYY"
    m = _DATE_PATTERNS[2].search(text)
    if m:
        year = int(m.group(3))
        month = _MONTH_MAP.get(m.group(2).lower(), "01")
        day = m.group(1).zfill(2)
        return f"{year}-{month}-{day}", year

    # Q1 2024
    m = _DATE_PATTERNS[3].search(text)
    if m:
        year = int(m.group(2))
        quarter = m.group(1).upper()
        month = {"Q1": "03", "Q2": "06", "Q3": "09", "Q4": "12"}.get(quarter, "01")
        return f"{year}-{month}", year

    # Year only
    m = _DATE_PATTERNS[4].search(text)
    if m:
        year = int(m.group(1))
        return str(year), year

    return "", None


def _sort_key(event: TimelineEvent) -> tuple:
    """Sort key: (year, date_string) — handles partial dates gracefully."""
    year = event.event_year or 9999
    # Pad date string for consistent lexicographic ordering
    date = event.event_date or ""
    return (year, date)


# ── Public API ─────────────────────────────────────────────────────────────────

def build_timeline(
    query: str,
    root: Path,
    time_range: tuple[int, int] | None = None,
    event_types: list[str] | None = None,
    semantic_limit: int = 12,
) -> Timeline:
    """
    Build a chronological timeline for the given query.

    Merges two sources:
    1. Structured events from the ``timeline_events`` SQLite table.
    2. Date-bearing chunks from semantic retrieval (fallback / enrichment).

    Parameters
    ----------
    query: The user's timeline question.
    root: Project root.
    time_range: Optional (start_year, end_year).
    event_types: Filter to specific event types.
    semantic_limit: Max semantic chunks to pull for date extraction.
    """
    from core.storage.db import get_connection, query_timeline_events
    from core.retrieval.searcher import retrieve_documents

    events: list[TimelineEvent] = []

    # 1. Pull from structured table
    conn = get_connection(root)
    try:
        sql_events = query_timeline_events(
            conn,
            year_min=time_range[0] if time_range else None,
            year_max=time_range[1] if time_range else None,
            event_types=event_types,
            limit=200,
        )
    finally:
        conn.close()

    for row in sql_events:
        events.append(TimelineEvent(
            event_date=row.get("event_date", ""),
            event_year=row.get("event_year"),
            event_text=row.get("event_text", ""),
            event_type=row.get("event_type", "general"),
            source_file=row.get("file_path", ""),
        ))

    # 2. Semantic retrieval for enrichment
    semantic_chunks = retrieve_documents(query, root, limit=semantic_limit)
    for chunk in semantic_chunks:
        content = chunk.get("content", "")
        date_str, year = _extract_date_from_text(content)
        if not year:
            continue
        if time_range and not (time_range[0] <= year <= time_range[1]):
            continue

        # Only add if not already captured by structured table (rough dedup)
        chunk_key = (year, content[:50])
        if not any(
            e.event_year == year and e.event_text[:50] == content[:50]
            for e in events
        ):
            events.append(TimelineEvent(
                event_date=date_str,
                event_year=year,
                event_text=content[:300],
                event_type="general",
                source_file=chunk.get("file_path", ""),
                source_year=chunk.get("doc_year"),
            ))

    # Sort chronologically
    events.sort(key=_sort_key)

    return Timeline(
        events=events,
        query=query,
        time_range=time_range,
    )
