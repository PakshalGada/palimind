"""
Financial data retrieval and extraction tools.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FinancialsResult:
    """Combined structured + semantic financial retrieval result."""
    structured_facts: list[dict]    # rows from financial_facts table
    context_chunks: list[dict]      # semantic chunks from financial sections
    query: str = ""


def retrieve_financials(
    query: str,
    root: Path,
    time_range: tuple[int, int] | None = None,
    metric_names: list[str] | None = None,
    limit: int = 5,
) -> FinancialsResult:
    """
    Retrieve financial data: structured facts (SQL) + semantic context.

    Parameters
    ----------
    query: User's financial question.
    root: Project root.
    time_range: Optional (start_year, end_year) inclusive.
    metric_names: Specific metrics to look up (e.g. ['revenue', 'gross_margin']).
    limit: Max semantic chunks to return.
    """
    from core.storage.db import get_connection, query_financial_facts
    from core.retrieval.searcher import retrieve_by_metadata

    # 1. Structured SQL lookup
    conn = get_connection(root)
    try:
        sql_facts = query_financial_facts(
            conn,
            metric_names=metric_names,
            doc_year_min=time_range[0] if time_range else None,
            doc_year_max=time_range[1] if time_range else None,
            limit=50,
        )
    finally:
        conn.close()

    # 2. Semantic retrieval from financial sections
    semantic_chunks = retrieve_by_metadata(
        query,
        root,
        limit,
        section_title="financial",
        doc_year=None,
    )

    # If section filter returned nothing, try a broader search
    if not semantic_chunks:
        from core.retrieval.searcher import retrieve_documents
        semantic_chunks = retrieve_documents(query, root, limit)

    return FinancialsResult(
        structured_facts=sql_facts,
        context_chunks=semantic_chunks,
        query=query,
    )


def format_financial_facts(facts: list[dict]) -> str:
    """Format structured financial facts as a readable table string."""
    if not facts:
        return ""

    # Group by year
    by_year: dict[int | None, list[dict]] = {}
    for fact in facts:
        year = fact.get("doc_year")
        by_year.setdefault(year, []).append(fact)

    lines = ["**Structured Financial Data:**\n"]
    for year, year_facts in sorted(by_year.items(), key=lambda x: x[0] or 0):
        lines.append(f"Year: {year or 'Unknown'}")
        for fact in year_facts:
            name = fact.get("metric_name", "").replace("_", " ").title()
            value = fact.get("value")
            unit = fact.get("unit", "")
            period = fact.get("period", "")
            source = fact.get("file_path", "").split("/")[-1]

            val_str = f"{value:,.2f}" if isinstance(value, float) else str(value)
            lines.append(f"  • {name}: {val_str} {unit} ({period}) — {source}")
        lines.append("")

    return "\n".join(lines)
