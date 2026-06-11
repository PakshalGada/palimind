"""
Comparison and cross-document synthesis tools.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx


@dataclass
class ComparisonResult:
    """Result of compare_document_sets()."""
    per_doc_summary: dict[str, str]       # {doc_label: summary_text}
    comparative_analysis: str             # full comparative narrative
    doc_labels: list[str]
    contradictions_noted: list[str] = field(default_factory=list)


def _llm_call(
    prompt: str,
    system: str,
    ollama_url: str,
    model: str,
    temperature: float = 0.1,
    timeout: float = 120.0,
) -> str:
    """Make a single non-streaming LLM call. Returns the response text."""
    try:
        resp = httpx.post(
            f"{ollama_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"[LLM call failed: {e}]"


def compare_document_sets(
    query: str,
    doc_sets: dict[str, list[dict]],
    ollama_url: str,
    model: str,
    token_budget: int = 6000,
) -> ComparisonResult:
    """
    Compare retrieved chunk sets from multiple documents.

    Parameters
    ----------
    query:
        The original user question driving the comparison.
    doc_sets:
        ``{label: [chunk_dicts]}`` — e.g. ``{"2023": chunks_23, "2025": chunks_25}``
    ollama_url, model:
        Ollama endpoint and model name.
    token_budget:
        Approximate character budget for the combined context.

    Returns
    -------
    ComparisonResult
    """
    from core.context.assembler import assemble_context, AssembledContext
    from core.agent_planner.types import TaskType

    # Flatten all chunks with doc_label injected
    all_chunks: list[dict] = []
    for label, chunks in doc_sets.items():
        for chunk in chunks:
            c = dict(chunk)
            c["_doc_label"] = label
            all_chunks.append(c)

    # Build comparative context (per-doc sections)
    assembled = assemble_context(all_chunks, TaskType.COMPARISON, token_budget=token_budget)

    # System prompt for comparison
    system = (
        "You are an expert document analyst specializing in comparative analysis. "
        "You will be given sections from multiple documents, each clearly labeled. "
        "Your task is to produce a thorough, structured comparison that:\n"
        "1. Addresses the user's specific question directly\n"
        "2. Compares each document on every relevant dimension\n"
        "3. Highlights key differences, changes, and trends\n"
        "4. Notes any contradictions or inconsistencies\n"
        "5. Cites the document source for every claim\n"
        "Be specific. Use concrete data and quotes where available."
    )

    user_prompt = (
        f"Documents:\n{assembled.text}\n\n"
        f"Question: {query}\n\n"
        "Provide a detailed comparative analysis:"
    )

    comparative_analysis = _llm_call(user_prompt, system, ollama_url, model)

    # Per-doc mini-summaries
    per_doc_summary: dict[str, str] = {}
    for label, chunks in doc_sets.items():
        if not chunks:
            per_doc_summary[label] = "No relevant content found."
            continue
        doc_text = "\n\n".join(c.get("content", "") for c in chunks[:5])
        mini_system = "You are a concise summariser. Write 2-3 sentences summarising the key points from the provided text relevant to the question."
        mini_prompt = f"Text:\n{doc_text[:3000]}\n\nQuestion: {query}\n\nSummary:"
        per_doc_summary[label] = _llm_call(mini_prompt, mini_system, ollama_url, model)

    return ComparisonResult(
        per_doc_summary=per_doc_summary,
        comparative_analysis=comparative_analysis,
        doc_labels=list(doc_sets.keys()),
    )


def summarize_document(
    file_path: str,
    root: Path,
    ollama_url: str,
    model: str,
    focus_query: str | None = None,
    max_chars: int = 8000,
) -> str:
    """
    Generate a (optionally query-focused) summary of a document.

    Falls back to the stored summary if no focus_query is given.
    """
    from core.storage.db import get_connection, get_file_summary, get_chunks_for_file

    conn = get_connection(root)
    try:
        stored = get_file_summary(conn, file_path) or ""
        if stored and not focus_query:
            return stored
        chunks = get_chunks_for_file(conn, file_path)
    finally:
        conn.close()

    if not chunks:
        return stored or "No content available."

    full_text = "\n\n".join(chunks)[:max_chars]

    system = (
        "You are a precise document summariser. "
        + ("Summarise the document with a focus on the given question." if focus_query
           else "Write a comprehensive 3-5 sentence summary of the document.")
    )
    prompt = (
        (f"Question: {focus_query}\n\n" if focus_query else "")
        + f"Document:\n{full_text}\n\nSummary:"
    )

    from core.generative.summariser import summarise_file
    return summarise_file(full_text, ollama_url, model, max_chars=max_chars)
