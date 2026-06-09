"""
Query intent router.

Classifies an incoming query into one of three intents before touching
the vector index, enabling targeted retrieval strategies:

  FILE_TARGETED  — the query explicitly mentions a specific indexed file
                   (e.g. "summarise main.py", "what does config.py do?")

  CORPUS_WIDE    — the query asks about the index as a whole
                   (e.g. "what files are indexed?", "list all documents")

  SEMANTIC       — default; falls through to turbovec similarity search
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto


class IntentKind(Enum):
    FILE_TARGETED = auto()
    CORPUS_WIDE = auto()
    SEMANTIC = auto()


@dataclass
class QueryIntent:
    kind: IntentKind
    # Populated for FILE_TARGETED — the matched indexed path(s)
    matched_paths: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Corpus-wide trigger phrases
# ---------------------------------------------------------------------------
_CORPUS_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\blist\b.{0,30}\b(files?|documents?|index)\b",
        r"\bwhat\b.{0,30}\b(files?|documents?)\b.{0,30}\b(indexed|know|have|contain)\b",
        r"\bwhich\b.{0,30}\b(files?|documents?)\b",
        r"\ball\b.{0,30}\b(files?|documents?)\b",
        r"\bshow\b.{0,30}\b(files?|documents?|index)\b",
        r"\bwhat.{0,10}indexed\b",
        r"\bwhat.{0,10}in\s+(the\s+)?index\b",
        r"\bfile\s+manifest\b",
    ]
]

# Summarisation / file-targeted trigger verbs
_FILE_TRIGGER_VERBS = re.compile(
    r"\b(summaris[e|ed]?|summarize[d]?|describe|explain|what.{0,10}(is|does|contain)|"
    r"show\s+me|tell\s+me\s+about|overview\s+of|contents?\s+of|give\s+me)\b",
    re.IGNORECASE,
)


def _is_corpus_wide(query: str) -> bool:
    return any(p.search(query) for p in _CORPUS_PATTERNS)


def _find_file_mentions(query: str, indexed_paths: list[str]) -> list[str]:
    """
    Return any indexed paths whose filename appears literally in *query*.
    Matches are case-insensitive and checked against both the full relative
    path and the bare filename.
    """
    query_lower = query.lower()
    matched: list[str] = []
    for path in indexed_paths:
        # Check full relative path and just the filename
        candidates = [path.lower(), path.lower().split("/")[-1]]
        if any(c in query_lower for c in candidates):
            matched.append(path)
    return matched


def classify_query(query: str, indexed_paths: list[str]) -> QueryIntent:
    """
    Classify *query* given the list of currently indexed file paths.

    Returns a :class:`QueryIntent` describing how retrieval should proceed.
    """
    # 1. Corpus-wide check first (takes priority over file mentions)
    if _is_corpus_wide(query):
        return QueryIntent(kind=IntentKind.CORPUS_WIDE)

    # 2. File-targeted: explicit filename in query
    matched = _find_file_mentions(query, indexed_paths)
    if matched:
        return QueryIntent(kind=IntentKind.FILE_TARGETED, matched_paths=matched)

    # 3. Default: semantic vector search
    return QueryIntent(kind=IntentKind.SEMANTIC)
