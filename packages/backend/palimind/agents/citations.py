"""Citation attachment for agent runs.

Agent tools already record web/document sources through the shared
``source_collector`` context. This module turns those raw records into ranked
``Source`` objects, attaches citations to the final answer, and returns the
payload the UI/SSE stream expects (``citation_map``).

It is deliberately best-effort: a citation failure must never lose an answer.
"""

from __future__ import annotations

from typing import Any


def finalize_agent_citations(
    answer: str,
    collected: list[dict[str, Any]] | None,
) -> tuple[str, dict[str, Any] | None]:
    """Attach citations to *answer* from *collected* source records.

    Returns ``(possibly_updated_answer, citation_payload_or_None)``.
    """
    if not answer or not answer.strip() or not collected:
        return answer, None
    try:
        from palimind.generative.citation import finalize_citations
        from palimind.research.sources import (
            dedupe_sources,
            score_sources,
            sources_from_collected,
        )

        sources = score_sources(dedupe_sources(sources_from_collected(collected)))
        if not sources:
            return answer, None
        result = finalize_citations(answer, sources)
        return result.text, result.to_dict()
    except Exception:
        return answer, None
