"""
Structured context assembler for the Palimind agentic planner.

Replaces the raw ``"\\n\\n".join(context.text_contexts)`` in ``querying.py``
with a document-aware, token-budgeted context assembler.

Key features:
* Groups chunks by source document with clear separator labels.
* Allocates token budget equally across documents for COMPARISON tasks.
* Deduplicates near-identical chunks (avoids sending the same sentence twice).
* Sorts timeline chunks chronologically.
* Returns ``AssembledContext`` with full provenance for diagnostics.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.agent_planner.types import TaskType


@dataclass
class AssembledContext:
    """Result of context assembly, ready to be sent to the LLM."""
    text: str                                    # final concatenated string for LLM
    doc_groups: dict[str, list[str]]             # {file_path: [chunk_texts]}
    token_count: int                             # estimated token count
    truncated: bool = False                      # True if budget was hit
    dedup_removed: int = 0                       # chunks removed by deduplication
    chunks_used: list[dict] = field(default_factory=list)  # chunk dicts that made it in


# ── Deduplication ──────────────────────────────────────────────────────────────

def _ngram_similarity(a: str, b: str, n: int = 4) -> float:
    """
    Character n-gram Jaccard similarity.
    Fast approximation of semantic similarity for deduplication.
    Returns 0.0 (totally different) to 1.0 (identical).
    """
    if not a or not b:
        return 0.0
    a_lower = a.lower()
    b_lower = b.lower()
    if a_lower == b_lower:
        return 1.0
    a_ngrams = {a_lower[i:i+n] for i in range(len(a_lower) - n + 1)}
    b_ngrams = {b_lower[i:i+n] for i in range(len(b_lower) - n + 1)}
    if not a_ngrams or not b_ngrams:
        return 0.0
    intersection = len(a_ngrams & b_ngrams)
    union = len(a_ngrams | b_ngrams)
    return intersection / union if union else 0.0


def _deduplicate(
    chunks: list[dict],
    threshold: float = 0.85,
) -> tuple[list[dict], int]:
    """
    Remove near-duplicate chunks using n-gram Jaccard similarity.

    When two chunks are above the similarity threshold, keep whichever
    has the higher rerank_score (or the first one if no scores).

    Returns (deduplicated_list, num_removed).
    """
    if not chunks:
        return [], 0

    kept: list[dict] = []
    removed = 0

    for chunk in chunks:
        content = chunk.get("content", "")
        is_duplicate = False
        for kept_chunk in kept:
            sim = _ngram_similarity(content, kept_chunk.get("content", ""))
            if sim >= threshold:
                # Keep whichever has a better rerank score
                chunk_score = chunk.get("rerank_score", 0.0) or 0.0
                kept_score = kept_chunk.get("rerank_score", 0.0) or 0.0
                if chunk_score > kept_score:
                    kept.remove(kept_chunk)
                    kept.append(chunk)
                is_duplicate = True
                removed += 1
                break
        if not is_duplicate:
            kept.append(chunk)

    return kept, removed


# ── Assembly strategies ────────────────────────────────────────────────────────

def _token_count(text: str) -> int:
    return max(1, len(text) // 4)


def _doc_label(file_path: str, doc_year: int | None, doc_type: str) -> str:
    """Build a human-readable document label for context separators."""
    name = file_path.split("/")[-1]
    parts = [name]
    if doc_year:
        parts.append(str(doc_year))
    if doc_type and doc_type != "other":
        parts.append(doc_type.upper())
    return " | ".join(parts)


def _assemble_flat(
    chunks: list[dict],
    token_budget: int,
) -> AssembledContext:
    """Simple flat assembly, ordered by rerank_score descending."""
    chunks_sorted = sorted(
        chunks, key=lambda c: c.get("rerank_score", 0.0) or 0.0, reverse=True
    )
    parts: list[str] = []
    used_chunks: list[dict] = []
    used_tokens = 0
    truncated = False

    for chunk in chunks_sorted:
        text = chunk.get("content", "")
        fp = chunk.get("file_path", "unknown")
        section = chunk.get("section_title", "")
        label = f"Source ({fp}" + (f" — {section}" if section else "") + f"):\n{text}"
        tk = _token_count(label)
        if used_tokens + tk > token_budget:
            truncated = True
            break
        parts.append(label)
        used_chunks.append(chunk)
        used_tokens += tk

    text = "\n\n".join(parts)
    doc_groups: dict[str, list[str]] = {}
    for chunk in used_chunks:
        fp = chunk.get("file_path", "unknown")
        doc_groups.setdefault(fp, []).append(chunk.get("content", ""))

    return AssembledContext(
        text=text,
        doc_groups=doc_groups,
        token_count=used_tokens,
        truncated=truncated,
        chunks_used=used_chunks,
    )


def _assemble_comparative(
    doc_groups: dict[str, list[dict]],
    token_budget: int,
) -> AssembledContext:
    """
    Comparative assembly: strict per-document sections with equal token budgets.

    Each document gets its own labeled section so the LLM can clearly
    compare 2023 vs 2024 vs 2025 without mixing chunks.
    """
    n_docs = max(len(doc_groups), 1)
    budget_per_doc = token_budget // n_docs

    parts: list[str] = []
    all_used_chunks: list[dict] = []
    total_tokens = 0
    truncated = False
    global_doc_groups: dict[str, list[str]] = {}

    # Sort documents by year (ascending) so the LLM reads chronologically
    def _sort_key(kv: tuple[str, list[dict]]) -> int:
        chunks = kv[1]
        if chunks and chunks[0].get("doc_year"):
            return chunks[0]["doc_year"]
        return 9999

    for file_path, chunks in sorted(doc_groups.items(), key=_sort_key):
        # Sort chunks within each doc by rerank_score
        chunks_sorted = sorted(
            chunks, key=lambda c: c.get("rerank_score", 0.0) or 0.0, reverse=True
        )

        doc_year = chunks[0].get("doc_year") if chunks else None
        doc_type = chunks[0].get("doc_type", "other") if chunks else "other"
        label = _doc_label(file_path, doc_year, doc_type)

        section_parts: list[str] = []
        used_tokens = 0
        used_chunks: list[dict] = []

        for chunk in chunks_sorted:
            text = chunk.get("content", "")
            section = chunk.get("section_title", "")
            entry = (f"[{section}] " if section else "") + text
            tk = _token_count(entry)
            if used_tokens + tk > budget_per_doc:
                truncated = True
                break
            section_parts.append(entry)
            used_chunks.append(chunk)
            used_tokens += tk

        if section_parts:
            doc_block = f"━━━ {label} ━━━\n" + "\n\n".join(section_parts)
            parts.append(doc_block)
            all_used_chunks.extend(used_chunks)
            total_tokens += used_tokens
            global_doc_groups[file_path] = [c.get("content", "") for c in used_chunks]

    return AssembledContext(
        text="\n\n".join(parts),
        doc_groups=global_doc_groups,
        token_count=total_tokens,
        truncated=truncated,
        chunks_used=all_used_chunks,
    )


def _assemble_timeline(
    chunks: list[dict],
    token_budget: int,
) -> AssembledContext:
    """
    Timeline assembly: sort chunks by doc_year, then by chunk_index.
    Adds year separators between document years.
    """
    # Sort by year → chunk_index
    chunks_sorted = sorted(
        chunks,
        key=lambda c: (c.get("doc_year") or 9999, c.get("chunk_index", 0)),
    )

    parts: list[str] = []
    used_chunks: list[dict] = []
    used_tokens = 0
    truncated = False
    current_year: int | None = None

    for chunk in chunks_sorted:
        year = chunk.get("doc_year")
        text = chunk.get("content", "")
        fp = chunk.get("file_path", "")

        if year and year != current_year:
            year_header = f"\n── {year} ({fp.split('/')[-1]}) ──"
            parts.append(year_header)
            current_year = year

        tk = _token_count(text)
        if used_tokens + tk > token_budget:
            truncated = True
            break
        parts.append(text)
        used_chunks.append(chunk)
        used_tokens += tk

    doc_groups: dict[str, list[str]] = {}
    for chunk in used_chunks:
        fp = chunk.get("file_path", "unknown")
        doc_groups.setdefault(fp, []).append(chunk.get("content", ""))

    return AssembledContext(
        text="\n\n".join(parts),
        doc_groups=doc_groups,
        token_count=used_tokens,
        truncated=truncated,
        chunks_used=used_chunks,
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def assemble_context(
    chunks: list[dict],
    task_type: TaskType,
    token_budget: int = 6000,
    dedup_threshold: float = 0.85,
) -> AssembledContext:
    """
    Assemble retrieved chunks into a structured context string.

    Parameters
    ----------
    chunks:
        List of chunk dicts (from vector store / SQL). Each dict is expected
        to have at minimum: ``content``, ``file_path``. Optionally:
        ``rerank_score``, ``doc_year``, ``doc_type``, ``section_title``,
        ``chunk_index``.
    task_type:
        Determines the assembly strategy.
    token_budget:
        Approximate maximum number of tokens in the output context.
    dedup_threshold:
        Jaccard n-gram similarity threshold for deduplication (0–1).

    Returns
    -------
    AssembledContext
    """
    if not chunks:
        return AssembledContext(
            text="",
            doc_groups={},
            token_count=0,
        )

    # Deduplication pass
    chunks, removed = _deduplicate(chunks, threshold=dedup_threshold)

    # Group by document for strategies that need per-doc buckets
    doc_groups: dict[str, list[dict]] = {}
    for chunk in chunks:
        fp = chunk.get("file_path", "unknown")
        doc_groups.setdefault(fp, []).append(chunk)

    # Strategy selection
    if task_type in (TaskType.COMPARISON, TaskType.CONTRADICTION, TaskType.TREND_ANALYSIS):
        result = _assemble_comparative(doc_groups, token_budget)
    elif task_type == TaskType.TIMELINE:
        result = _assemble_timeline(chunks, token_budget)
    else:
        result = _assemble_flat(chunks, token_budget)

    result.dedup_removed = removed
    return result
