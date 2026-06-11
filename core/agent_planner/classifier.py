"""
Query classifier for Palimind's agentic planner.

Classifies an incoming (already reformulated) query into one of eight TaskTypes
using fast regex heuristics — zero LLM round-trip required for common cases.

Priority order (highest to lowest):
  1. CONTRADICTION
  2. COMPARISON (explicit year-over-year or "vs" language)
  3. TREND_ANALYSIS
  4. TIMELINE
  5. FINANCIAL
  6. RISK_ANALYSIS
  7. SUMMARIZATION (file-targeted)
  8. LOOKUP (default)
"""
from __future__ import annotations

import re
from pathlib import Path

from core.agent_planner.types import ClassificationResult, TaskType


# ── Regex patterns ─────────────────────────────────────────────────────────────

_CONTRADICTION_RE = re.compile(
    r"\b(contradict|conflict|inconsist|disagree|mismatch|reversal|"
    r"flip|walk(?:ed)?\s+back|changed\s+stance|walk\s+back)\b",
    re.IGNORECASE,
)

_COMPARISON_RE = re.compile(
    r"\b(compar[ei]|differ(?:enc[e])?|change[d]?|evolv[e]?|shift[ed]?|"
    r"between|vs\.?|versus|contrast|how\s+did.{0,30}change|"
    r"from\s+20\d{2}\s+to\s+20\d{2})\b",
    re.IGNORECASE,
)

_TREND_RE = re.compile(
    r"\b(trend|over\s+(time|years?|quarters?|period)|growth\s+rate|"
    r"trajectory|year.over.year|yoy|quarter.over.quarter|qoq|"
    r"historically|across\s+years?|progression|pattern\s+over)\b",
    re.IGNORECASE,
)

_TIMELINE_RE = re.compile(
    r"\b(timeline|chronolog|sequence|order\s+of|when\s+did|"
    r"first\s+time|last\s+time|since\s+when|until\s+when|"
    r"history\s+of|events?\s+in|create\s+a\s+timeline|list\s+events?)\b",
    re.IGNORECASE,
)

_FINANCIAL_RE = re.compile(
    r"\b(revenue|profit|loss|gross\s+margin|operating\s+margin|net\s+margin|"
    r"eps|ebitda|ebit|cash\s+flow|balance\s+sheet|income\s+statement|"
    r"operating\s+income|net\s+income|total\s+assets|total\s+debt|"
    r"capex|capital\s+expenditure|dividend|earnings|quarterly\s+results|"
    r"financial\s+results|fiscal\s+year|fy\d{2,4}|q[1-4]\s*20\d{2})\b",
    re.IGNORECASE,
)

_RISK_RE = re.compile(
    r"\b(risk(?:\s+factor)?s?|threat|vulnerability|exposure|liability|"
    r"regulatory\s+risk|litigation|legal\s+risk|competition\s+risk|"
    r"operational\s+risk|market\s+risk|item\s+1a)\b",
    re.IGNORECASE,
)

_SUMMARIZE_RE = re.compile(
    r"\b(summariz[e]?|summar(?:is[e]?|y)|overview|brief|digest|"
    r"key\s+points?|main\s+points?|give\s+me\s+a\s+summary|"
    r"what\s+(?:is|does).{0,20}about|describe\s+the)\b",
    re.IGNORECASE,
)

# Year pattern: matches 2000-2099
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Known doc-type keywords
_DOCTYPE_KEYWORDS = re.compile(
    r"\b(10-?k|10-?q|8-?k|annual\s+report|earnings\s+call|proxy)\b",
    re.IGNORECASE,
)


def _extract_years(query: str) -> list[int]:
    return [int(y) for y in _YEAR_RE.findall(query)]


def _time_range(years: list[int]) -> tuple[int, int] | None:
    if len(years) >= 2:
        return (min(years), max(years))
    return None


def classify_query(
    query: str,
    indexed_docs: list[dict] | None = None,
) -> ClassificationResult:
    """
    Classify *query* into a :class:`TaskType`.

    Parameters
    ----------
    query:
        The (already reformulated) user query string.
    indexed_docs:
        Optional list of dicts with keys ``path``, ``doc_year``, ``doc_type``.
        Used to cross-reference explicit year mentions against available documents.

    Returns
    -------
    ClassificationResult
    """
    years = _extract_years(query)
    time_range = _time_range(years)

    # 1. CONTRADICTION — highest priority
    if _CONTRADICTION_RE.search(query):
        return ClassificationResult(
            task_type=TaskType.CONTRADICTION,
            time_range=time_range,
            confidence=0.90,
            raw_intent="Contradiction pattern detected in query",
        )

    # 2. TIMELINE — check before COMPARISON so "timeline from 2023 to 2025" wins
    if _TIMELINE_RE.search(query):
        return ClassificationResult(
            task_type=TaskType.TIMELINE,
            time_range=time_range,
            confidence=0.85,
            raw_intent="Timeline/chronology language detected (checked before comparison)",
        )

    # 3. COMPARISON — multi-year or explicit comparison language
    has_comparison_language = bool(_COMPARISON_RE.search(query))
    has_multi_year = len(years) >= 2
    if has_comparison_language or has_multi_year:
        return ClassificationResult(
            task_type=TaskType.COMPARISON,
            time_range=time_range,
            confidence=0.85 if has_comparison_language else 0.75,
            raw_intent="Comparison language or multiple years detected",
        )

    # 4. TREND ANALYSIS
    if _TREND_RE.search(query):
        return ClassificationResult(
            task_type=TaskType.TREND_ANALYSIS,
            time_range=time_range,
            confidence=0.85,
            raw_intent="Trend/trajectory language detected",
        )

    # (TIMELINE was already checked above — this line unreachable, kept for structure)
    if False and _TIMELINE_RE.search(query):
        return ClassificationResult(
            task_type=TaskType.TIMELINE,
            time_range=time_range,
            confidence=0.82,
            raw_intent="Timeline/chronology language detected",
        )

    # 5. FINANCIAL
    if _FINANCIAL_RE.search(query):
        return ClassificationResult(
            task_type=TaskType.FINANCIAL,
            time_range=time_range,
            confidence=0.82,
            raw_intent="Financial metric detected in query",
        )

    # 6. RISK ANALYSIS
    if _RISK_RE.search(query):
        return ClassificationResult(
            task_type=TaskType.RISK_ANALYSIS,
            time_range=time_range,
            confidence=0.80,
            raw_intent="Risk/threat language detected",
        )

    # 7. SUMMARIZATION
    if _SUMMARIZE_RE.search(query):
        return ClassificationResult(
            task_type=TaskType.SUMMARIZATION,
            time_range=time_range,
            confidence=0.80,
            raw_intent="Summarization language detected",
        )

    # 8. Default: LOOKUP
    return ClassificationResult(
        task_type=TaskType.LOOKUP,
        time_range=time_range,
        confidence=0.70,
        raw_intent="No specialized pattern matched; defaulting to lookup",
    )
