"""Agentic RAG for document mode.

Single-shot retrieval answers "what does the document say about X" well. It is
weak for questions that need several searches (comparisons, multi-part asks,
"find the exact number in the table, then compute"). This module adds an
iterative loop on top of the same shared retrieval pipeline:

    plan 2–6 sub-queries → run them in parallel → exact-term lookup →
    merge/RRF → sufficiency check → optional second round → cited context.

It deliberately reuses :func:`palimind.rag.retrieve.hybrid_search` instead of
replacing it: the agentic layer only decides *what to search* and *when to
stop*.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from palimind.agents.adaptive_reasoning import heuristic_complexity
from palimind.rag.retrieve import (
    _assemble_context,
    expand_parent_sections,
    rrf_fuse,
    select_diverse,
)
from palimind.storage.db import get_connection, grep_chunks

logger = logging.getLogger(__name__)

_AGENTIC_MODES = ("auto", "off", "always")

_COMPLEX_RE = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference between|across|both|"
    r"respectively|trend|over time|summari[sz]e all|every|each|"
    r"breakdown|reconcile|why did|how did|impact of)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"(\$\s?[\d,]+(?:\.\d+)?\s?(?:billion|million|bn|m|k)?|"
    r"\d+(?:\.\d+)?\s?%|\b(?:19|20)\d{2}\b)"
)
_QUOTED_RE = re.compile(r'"([^"\n]{3,80})"|\'([^\'\n]{3,80})\'')
_ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,4})\b")
_SPLIT_RE = re.compile(
    r"(?:\?|;|\n|\s+and\s+also\s+|\s+and\s+(?=(?:what|how|why|when|where|who|which|"
    r"compare|find|list|summarize|summarise|explain|show)\b)|\s+then\s+)",
    re.IGNORECASE,
)

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "about",
    "what",
    "when",
    "where",
    "which",
    "who",
    "how",
    "why",
    "can",
    "will",
    "would",
    "should",
    "could",
    "please",
    "use",
    "using",
    "run",
    "make",
    "need",
    "want",
    "give",
    "find",
    "get",
    "all",
    "any",
    "some",
    "your",
    "our",
    "you",
    "they",
    "them",
    "their",
    "does",
    "did",
    "was",
    "were",
    "are",
    "is",
    "of",
    "in",
    "on",
    "to",
    "a",
    "an",
    "it",
    "its",
}


# ── routing ────────────────────────────────────────────────────────────────────


def resolve_mode(mode: str | None, config: dict[str, Any] | None = None) -> str:
    """Normalize a requested agentic mode (``auto``/``off``/``always``)."""
    requested = str(mode or "").strip().lower()
    if requested not in _AGENTIC_MODES:
        requested = str((config or {}).get("agentic_rag", "auto")).strip().lower()
    return requested if requested in _AGENTIC_MODES else "auto"


def should_use_agentic(query: str, mode: str = "auto") -> bool:
    """Route a question to the agentic loop when complexity justifies it.

    Reuses the deterministic complexity heuristics that already drive agent
    reasoning effort, plus document-specific signals (comparisons, multiple
    questions, aggregation over time).
    """
    mode = resolve_mode(mode)
    if mode == "off":
        return False
    if mode == "always":
        return True

    text = (query or "").strip()
    if not text:
        return False

    signals = set(heuristic_complexity(text).get("signals") or [])
    if {"multi-question", "multi-step", "research", "structured-brief"} & signals:
        return True
    if _COMPLEX_RE.search(text):
        return True
    # Two or more explicit asks is a reliable multi-hop signal.
    if text.count("?") >= 2:
        return True
    # A long analytical prompt with several clauses is rarely one lookup.
    if len(text.split()) >= 26 and len(re.findall(r"[,;]", text)) >= 2:
        return True
    return False


# ── planning ───────────────────────────────────────────────────────────────────


def _clean_query(text: str) -> str:
    return " ".join(str(text or "").strip().strip("?.!;").split())


def heuristic_subqueries(query: str, max_subqueries: int = 6) -> list[str]:
    """Deterministic fallback plan when the local model is unavailable."""
    text = (query or "").strip()
    if not text:
        return []

    candidates: list[str] = [text]
    for piece in _SPLIT_RE.split(text):
        piece = _clean_query(piece)
        if len(piece.split()) >= 3:
            candidates.append(piece)

    # "compare X and Y" style questions: search each side separately.
    compare = re.search(
        r"\b(?:compare|difference between|versus|vs\.?)\s+(.+?)\s+(?:and|with|to|vs\.?)\s+(.+)",
        text,
        re.IGNORECASE,
    )
    if compare:
        left, right = _clean_query(compare.group(1)), _clean_query(compare.group(2))
        if left:
            candidates.append(left)
        if right:
            candidates.append(right)

    seen: set[str] = set()
    out: list[str] = []
    for candidate in candidates:
        key = candidate.lower()
        if key in seen or not candidate:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= max_subqueries:
            break
    return out


def plan_subqueries(
    query: str,
    *,
    model: str = "",
    ollama_url: str = "",
    max_subqueries: int = 6,
    usage_cb: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """Ask a small model for 2–6 self-contained searches; never fail hard."""
    fallback = heuristic_subqueries(query, max_subqueries)
    if not model or not ollama_url:
        return {"subqueries": fallback, "source": "heuristic", "reasoning": ""}

    prompt = (
        "Plan document retrieval for the user's question. Split it into 2-6 "
        "self-contained search queries that together cover every part of the "
        "question. Use different keywords/synonyms and include the original "
        "question as one query. Do not answer the question.\n\n"
        'Respond with ONLY JSON: {"queries": ["...", "..."], '
        '"reasoning": "<one short sentence>"}\n\n'
        f"Question: {query[:2000]}"
    )
    try:
        from palimind.llm.mixture_of_expert.llm import llm_chat_safe

        result = llm_chat_safe(
            [{"role": "user", "content": prompt}],
            model,
            ollama_url,
            format="json",
            temperature=0.1,
            num_predict=220,
            read_timeout=45.0,
            error_prefix="[agentic planner",
        )
    except Exception as e:  # noqa: BLE001 - planning is best-effort
        logger.debug(f"Agentic planning failed: {e}")
        return {"subqueries": fallback, "source": "heuristic", "reasoning": ""}

    if usage_cb is not None:
        try:
            usage_cb(result.get("usage") or {})
        except Exception:  # noqa: BLE001
            pass

    try:
        parsed = json.loads(result.get("content") or "{}")
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    raw = parsed.get("queries") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        raw = parsed.get("subqueries") if isinstance(parsed, dict) else None

    subqueries: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            text = _clean_query(str(item))
            if text and text.lower() not in {q.lower() for q in subqueries}:
                subqueries.append(text)
    if not subqueries:
        subqueries = fallback
    # Always keep the original ask in the plan.
    if text := _clean_query(query):
        if text.lower() not in {q.lower() for q in subqueries}:
            subqueries.insert(0, text)

    return {
        "subqueries": subqueries[:max_subqueries],
        "source": "llm",
        "reasoning": str(parsed.get("reasoning", ""))[:300] if isinstance(parsed, dict) else "",
    }


# ── exact lookup ───────────────────────────────────────────────────────────────


def extract_lookup_terms(query: str, limit: int = 6) -> list[str]:
    """Pull verbatim terms worth an exact substring lookup (figures, quotes)."""
    terms: list[str] = []
    for match in _QUOTED_RE.finditer(query or ""):
        value = (match.group(1) or match.group(2) or "").strip()
        if value:
            terms.append(value)
    for match in _NUMBER_RE.finditer(query or ""):
        terms.append(match.group(0).strip())
    for match in _ENTITY_RE.finditer(query or ""):
        value = match.group(1).strip()
        if value.lower() not in _STOPWORDS:
            terms.append(value)

    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.lower()
        if key in seen or term.lower() in _STOPWORDS:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= limit:
            break
    return out


def _exact_lookup(root: Path, query: str, file_paths: list[str] | None) -> list[dict]:
    terms = extract_lookup_terms(query)
    if not terms:
        return []
    try:
        conn = get_connection(root)
        try:
            return grep_chunks(conn, terms, limit=6, file_paths=file_paths)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Exact lookup failed: {e}")
        return []


# ── sufficiency ────────────────────────────────────────────────────────────────


def _context_ok(results: list[dict]) -> bool:
    return any((r.get("content") or "").strip() for r in results)


def sufficiency_check(
    query: str,
    results: list[dict],
    *,
    model: str = "",
    ollama_url: str = "",
    usage_cb: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """Decide whether the gathered evidence can answer the question.

    Deterministic when no model is supplied; otherwise one small JSON call with
    a safe "sufficient if we found anything" fallback.
    """
    if not _context_ok(results):
        return {"sufficient": False, "followups": [], "missing": "no evidence retrieved"}

    if not model or not ollama_url:
        return {"sufficient": True, "followups": [], "missing": "", "source": "heuristic"}

    snippets = "\n\n".join(
        f"[{i + 1}] {(r.get('file_path') or '')}: {(r.get('content') or '')[:600]}"
        for i, r in enumerate(results[:6])
    )
    prompt = (
        "You are checking whether retrieved document evidence is enough to answer "
        "the user's question. If a specific fact (number, date, name, comparison) "
        "is missing, propose 1-2 new search queries that would find it. Do not "
        "answer the question.\n\n"
        'Respond with ONLY JSON: {"sufficient": true|false, '
        '"missing": "<short>", "followups": ["..."]}\n\n'
        f"Question: {query[:1200]}\n\nEvidence:\n{snippets[:5000]}"
    )
    try:
        from palimind.llm.mixture_of_expert.llm import llm_chat_safe

        result = llm_chat_safe(
            [{"role": "user", "content": prompt}],
            model,
            ollama_url,
            format="json",
            temperature=0.1,
            num_predict=180,
            read_timeout=35.0,
            error_prefix="[agentic sufficiency",
        )
    except Exception as e:  # noqa: BLE001 - never block the answer
        logger.debug(f"Sufficiency check failed: {e}")
        return {"sufficient": True, "followups": [], "missing": "", "source": "fallback"}

    if usage_cb is not None:
        try:
            usage_cb(result.get("usage") or {})
        except Exception:  # noqa: BLE001
            pass

    try:
        parsed = json.loads(result.get("content") or "{}")
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    followups = [
        _clean_query(str(item))
        for item in (parsed.get("followups") or [])
        if _clean_query(str(item))
    ][:2]
    return {
        "sufficient": bool(parsed.get("sufficient", True)),
        "followups": followups,
        "missing": str(parsed.get("missing", ""))[:300],
        "source": "llm",
    }


# ── merge ──────────────────────────────────────────────────────────────────────


def merge_contexts(
    root: Path,
    query: str,
    contexts: list[dict],
    *,
    limit: int = 10,
    token_budget: int | None = None,
    parent_retrieval: bool = True,
    parent_max_tokens: int = 1500,
    exact: list[dict] | None = None,
) -> dict[str, Any]:
    """Fuse several retrieval results into one cited context block."""
    ranked_lists: list[list[dict]] = []
    sources: list[str] = []
    errors: list[str] = []
    for ctx in contexts:
        results = list(ctx.get("results") or [])
        if results:
            ranked_lists.append(results)
        for src in ctx.get("sources") or []:
            if src not in sources:
                sources.append(src)
        for err in ctx.get("errors") or []:
            errors.append(err)

    merged: list[dict] = []
    if ranked_lists:
        for entry in rrf_fuse(ranked_lists):
            merged.append(entry["result"])

    # Exact-term hits are high precision: put them first so the selector keeps
    # them, then let MMR/lexical diversity fill the remaining budget.
    if exact:
        seen_ids = {r.get("chunk_db_id") for r in merged if r.get("chunk_db_id")}
        merged = [r for r in exact if r.get("chunk_db_id") not in seen_ids] + merged

    selected = select_diverse(merged, max(limit, 1), per_file_cap=4)
    try:
        conn = get_connection(root)
        try:
            selected = expand_parent_sections(
                conn,
                selected,
                max_tokens=parent_max_tokens,
                enabled=parent_retrieval,
            )
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        errors.append(f"Parent expansion error: {e}")

    parts, kept = _assemble_context(selected, token_budget)
    for result in kept:
        path = result.get("file_path", "unknown")
        if path not in sources:
            sources.append(path)

    has_media = any(r.get("media_start_ts") is not None for r in kept)
    return {
        "content": "\n\n".join(parts),
        "sources": sources,
        "results": kept,
        "total_results": len(kept),
        "has_media": has_media,
        "errors": list(dict.fromkeys(errors)),
    }


def _run_queries(
    engine: Any,
    queries: list[str],
    *,
    limit: int,
    files_filter: list[str] | None,
) -> list[dict]:
    results: list[dict] = []
    if not queries:
        return results
    with ThreadPoolExecutor(max_workers=min(4, len(queries))) as pool:
        future_map = {
            pool.submit(
                engine.retrieve_context,
                subquery,
                limit=limit,
                history=None,
                mid_term_summary=None,
                long_term_episodes=None,
                files_filter=files_filter,
            ): subquery
            for subquery in queries
        }
        for future in as_completed(future_map):
            try:
                results.append(future.result())
            except Exception as e:  # noqa: BLE001 - one lane must not sink the run
                logger.debug(f"Agentic sub-query failed: {e}")
    return results


def agentic_retrieve(
    engine: Any,
    query: str,
    *,
    limit: int = 10,
    files_filter: list[str] | None = None,
    max_subqueries: int = 6,
    max_rounds: int = 2,
    token_budget: int | None = None,
    parent_retrieval: bool = True,
    parent_max_tokens: int = 1500,
    planner_model: str = "",
    usage_cb: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """Plan → parallel retrieve → exact lookup → verify (→ repeat) → context."""
    plan = plan_subqueries(
        query,
        model=planner_model,
        ollama_url=getattr(engine, "ollama_url", ""),
        max_subqueries=max_subqueries,
        usage_cb=usage_cb,
    )
    subqueries: list[str] = list(plan.get("subqueries") or [query])
    seen_queries = {q.lower() for q in subqueries}

    contexts = _run_queries(engine, subqueries, limit=limit, files_filter=files_filter)
    exact = _exact_lookup(engine.root, query, files_filter)
    merged = merge_contexts(
        engine.root,
        query,
        contexts,
        limit=limit,
        token_budget=token_budget,
        parent_retrieval=parent_retrieval,
        parent_max_tokens=parent_max_tokens,
        exact=exact,
    )

    rounds = 1
    sufficiency: dict[str, Any] = {"sufficient": True, "followups": []}
    for _ in range(max(0, max_rounds - 1)):
        sufficiency = sufficiency_check(
            query,
            merged.get("results") or [],
            model=planner_model,
            ollama_url=getattr(engine, "ollama_url", ""),
            usage_cb=usage_cb,
        )
        followups = [q for q in sufficiency.get("followups") or [] if q.lower() not in seen_queries]
        if sufficiency.get("sufficient") or not followups:
            break
        seen_queries.update(q.lower() for q in followups)
        subqueries.extend(followups)
        more = _run_queries(engine, followups, limit=limit, files_filter=files_filter)
        contexts.extend(more)
        exact = _exact_lookup(engine.root, query, files_filter)
        merged = merge_contexts(
            engine.root,
            query,
            contexts,
            limit=limit,
            token_budget=token_budget,
            parent_retrieval=parent_retrieval,
            parent_max_tokens=parent_max_tokens,
            exact=exact,
        )
        rounds += 1

    merged["subqueries"] = subqueries
    merged["rounds"] = rounds
    merged["sufficiency"] = sufficiency
    merged["plan_source"] = plan.get("source", "heuristic")
    merged["plan_reasoning"] = plan.get("reasoning", "")
    merged["lookup_terms"] = extract_lookup_terms(query)
    return merged
