"""Lightweight graph signals: entity aliases and possible contradictions.

These are deterministic heuristics, not an LLM judgement. They surface pairs a
reader should inspect; every result keeps the two source files and quotes so the
UI can show provenance rather than a verdict.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_NEGATIONS = {
    "not",
    "no",
    "never",
    "none",
    "without",
    "cannot",
    "can't",
    "didn't",
    "doesn't",
    "isn't",
    "wasn't",
    "won't",
    "failed",
    "declined",
}
_OPPOSITES = (
    ("increase", "decrease"),
    ("increased", "decreased"),
    ("rise", "fall"),
    ("rose", "fell"),
    ("higher", "lower"),
    ("growth", "decline"),
    ("grew", "shrank"),
    ("approved", "rejected"),
    ("profit", "loss"),
    ("up", "down"),
    ("always", "never"),
    ("better", "worse"),
)
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "were",
    "was",
    "are",
    "has",
    "have",
    "had",
    "its",
    "their",
    "they",
    "which",
    "will",
    "would",
    "could",
    "should",
    "about",
    "into",
    "over",
    "than",
    "then",
    "when",
    "where",
    "while",
    "also",
    "more",
    "most",
    "such",
    "been",
    "being",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
_NUM_RE = re.compile(r"\b\d[\d,.]*\b")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _tokens(text: str) -> set[str]:
    return {
        word.lower()
        for word in _WORD_RE.findall(text or "")
        if word.lower() not in _STOPWORDS
    }


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.split(text or "") if part.strip()]


def _polarity(text: str) -> tuple[bool, set[str], set[str]]:
    words = _tokens(text)
    negated = any(word in _NEGATIONS for word in words)
    sides: set[str] = set()
    for left, right in _OPPOSITES:
        if left in words:
            sides.add(left)
        if right in words:
            sides.add(right)
    numbers = set(_NUM_RE.findall(text or ""))
    return negated, sides, numbers


def _reason(a: str, b: str) -> str:
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    neg_a, side_a, num_a = _polarity(a)
    neg_b, side_b, num_b = _polarity(b)
    reasons = []
    if neg_a != neg_b:
        reasons.append("one statement is negated")
    if side_a and side_b:
        for left, right in _OPPOSITES:
            if (left in side_a and right in side_b) or (
                right in side_a and left in side_b
            ):
                reasons.append(f"opposing terms: {left}/{right}")
                break
    if num_a and num_b and num_a != num_b:
        reasons.append("different figures")
    if not reasons and tokens_a != tokens_b:
        return ""
    return "; ".join(reasons)


def contradiction_candidates(root: Path, *, limit: int = 10) -> list[dict[str, Any]]:
    from palimind.storage.db import get_connection

    root = Path(root)
    conn = get_connection(root)
    try:
        rows = conn.execute(
            """
            SELECT em.entity_text, c.content, f.path, f.source_title, f.source_url,
                   c.section_title
            FROM entity_mentions em
            JOIN chunks c ON c.id = em.chunk_id
            JOIN files f ON f.id = c.file_id
            ORDER BY em.entity_text
            LIMIT 5000
            """
        ).fetchall()
    except Exception:  # noqa: BLE001 - signal is optional
        rows = []
    finally:
        conn.close()

    by_entity: dict[str, list[dict]] = {}
    try:
        from palimind.document.graph import normalize_entity_name
    except Exception:  # noqa: BLE001
        normalize_entity_name = lambda value: str(value).casefold()  # type: ignore[assignment]
    for entity, content, path, title, url, section in rows:
        name = str(entity or "").strip()
        if not name:
            continue
        by_entity.setdefault(normalize_entity_name(name), []).append(
            {
                "entity": name,
                "content": str(content or ""),
                "file_path": str(path or ""),
                "title": str(title or ""),
                "url": str(url or ""),
                "section": str(section or ""),
            }
        )

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mentions in by_entity.values():
        if len(mentions) < 2:
            continue
        checked = 0
        for i, first in enumerate(mentions):
            for second in mentions[i + 1 :]:
                if first["file_path"] == second["file_path"]:
                    continue
                key = tuple(sorted((first["file_path"], second["file_path"]))) + (
                    mentions[0]["entity"].casefold(),
                )
                key_str = "|".join(key)
                if key_str in seen:
                    continue
                checked += 1
                if checked > 60:
                    break
                for sentence_a in _sentences(first["content"])[:12]:
                    for sentence_b in _sentences(second["content"])[:12]:
                        tokens_a, tokens_b = _tokens(sentence_a), _tokens(sentence_b)
                        if len(tokens_a) < 3 or len(tokens_b) < 3:
                            continue
                        overlap = len(tokens_a & tokens_b) / max(
                            1, min(len(tokens_a), len(tokens_b))
                        )
                        if overlap < 0.55:
                            continue
                        reason = _reason(sentence_a, sentence_b)
                        if not reason:
                            continue
                        seen.add(key_str)
                        found.append(
                            {
                                "entity": mentions[0]["entity"],
                                "reason": reason,
                                "a": {
                                    "file_path": first["file_path"],
                                    "title": first["title"],
                                    "url": first["url"],
                                    "section": first["section"],
                                    "quote": sentence_a[:280],
                                },
                                "b": {
                                    "file_path": second["file_path"],
                                    "title": second["title"],
                                    "url": second["url"],
                                    "section": second["section"],
                                    "quote": sentence_b[:280],
                                },
                            }
                        )
                        break
                    if key_str in seen:
                        break
                if len(found) >= limit:
                    return found
    return found


def agreement_candidates(root: Path, *, limit: int = 10) -> list[dict[str, Any]]:
    """Pairs of sentences from different files that make similar, aligned claims."""
    from palimind.document.graph import normalize_entity_name
    from palimind.storage.db import get_connection

    root = Path(root)
    conn = get_connection(root)
    try:
        rows = conn.execute(
            """
            SELECT em.entity_text, c.content, f.path, f.source_title, f.source_url,
                   c.section_title
            FROM entity_mentions em
            JOIN chunks c ON c.id = em.chunk_id
            JOIN files f ON f.id = c.file_id
            ORDER BY em.entity_text
            LIMIT 5000
            """
        ).fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    finally:
        conn.close()

    by_entity: dict[str, list[dict]] = {}
    for entity, content, path, title, url, section in rows:
        name = str(entity or "").strip()
        if not name:
            continue
        by_entity.setdefault(normalize_entity_name(name), []).append(
            {
                "entity": name,
                "content": str(content or ""),
                "file_path": str(path or ""),
                "title": str(title or ""),
                "url": str(url or ""),
                "section": str(section or ""),
            }
        )

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mentions in by_entity.values():
        for i, first in enumerate(mentions):
            for second in mentions[i + 1 :]:
                if first["file_path"] == second["file_path"]:
                    continue
                key = "|".join(
                    sorted((first["file_path"], second["file_path"]))
                ) + "|" + mentions[0]["entity"].casefold()
                if key in seen:
                    continue
                for sentence_a in _sentences(first["content"])[:8]:
                    for sentence_b in _sentences(second["content"])[:8]:
                        tokens_a, tokens_b = _tokens(sentence_a), _tokens(sentence_b)
                        if len(tokens_a) < 3 or len(tokens_b) < 3:
                            continue
                        overlap = len(tokens_a & tokens_b) / max(
                            1, min(len(tokens_a), len(tokens_b))
                        )
                        if overlap < 0.75:
                            continue
                        if _reason(sentence_a, sentence_b):
                            continue
                        seen.add(key)
                        found.append(
                            {
                                "entity": mentions[0]["entity"],
                                "a": {
                                    "file_path": first["file_path"],
                                    "title": first["title"],
                                    "url": first["url"],
                                    "quote": sentence_a[:240],
                                },
                                "b": {
                                    "file_path": second["file_path"],
                                    "title": second["title"],
                                    "url": second["url"],
                                    "quote": sentence_b[:240],
                                },
                            }
                        )
                        break
                    if key in seen:
                        break
                if len(found) >= limit:
                    return found
    return found


def entity_aliases(root: Path, *, limit: int = 40) -> list[dict[str, Any]]:
    """Group entity surface forms that normalise to the same canonical name."""
    from palimind.document.graph import normalize_entity_name
    from palimind.storage.db import get_connection

    root = Path(root)
    conn = get_connection(root)
    try:
        rows = conn.execute(
            """
            SELECT em.entity_text, COUNT(*) FROM entity_mentions em
            GROUP BY em.entity_text ORDER BY COUNT(*) DESC LIMIT 2000
            """
        ).fetchall()
        if not rows:
            rows = conn.execute(
                """
                SELECT entity_name, COUNT(*) FROM files
                WHERE COALESCE(entity_name, '') <> ''
                GROUP BY entity_name ORDER BY COUNT(*) DESC LIMIT 2000
                """
            ).fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    finally:
        conn.close()

    groups: dict[str, dict[str, Any]] = {}
    for name, count in rows:
        label = str(name or "").strip()
        if not label:
            continue
        canonical = normalize_entity_name(label)
        entry = groups.setdefault(
            canonical, {"canonical": canonical, "labels": [], "mentions": 0}
        )
        if label not in entry["labels"]:
            entry["labels"].append(label)
        entry["mentions"] += int(count or 0)
    aliases = [
        item
        for item in groups.values()
        if len(item["labels"]) > 1
    ]
    aliases.sort(key=lambda item: (-item["mentions"], item["canonical"]))
    return aliases[: max(1, min(int(limit or 40), 200))]


def signals(root: Path, *, limit: int = 10) -> dict[str, Any]:
    return {
        "aliases": entity_aliases(Path(root)),
        "contradictions": contradiction_candidates(Path(root), limit=limit),
        "agreements": agreement_candidates(Path(root), limit=limit),
    }
