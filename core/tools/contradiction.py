"""
Contradiction detection tool.

Detects contradictory or inconsistent statements across document sets
using n-gram similarity + LLM verification.

Algorithm:
1. For each pair of chunks from different documents, compute n-gram similarity.
   High similarity = same topic. Low similarity after filtering = potential contradiction.
2. Candidate pairs (high topic similarity but divergent content) are sent to the LLM.
3. The LLM confirms whether a genuine contradiction exists and rates severity.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Contradiction:
    """A single detected contradiction between two documents."""
    claim_a: str
    claim_b: str
    doc_a: str
    doc_b: str
    year_a: int | None
    year_b: int | None
    severity: str            # "high" | "medium" | "low"
    explanation: str = ""


@dataclass
class ContradictionReport:
    contradictions: list[Contradiction]
    query: str
    docs_compared: list[str]
    summary: str = ""


def _ngram_similarity(a: str, b: str, n: int = 4) -> float:
    """Character n-gram Jaccard similarity (same as context assembler)."""
    a_lower = a.lower()
    b_lower = b.lower()
    if a_lower == b_lower:
        return 1.0
    if not a_lower or not b_lower:
        return 0.0
    a_ngrams = {a_lower[i:i+n] for i in range(len(a_lower) - n + 1)}
    b_ngrams = {b_lower[i:i+n] for i in range(len(b_lower) - n + 1)}
    if not a_ngrams or not b_ngrams:
        return 0.0
    intersection = len(a_ngrams & b_ngrams)
    union = len(a_ngrams | b_ngrams)
    return intersection / union if union else 0.0


def _candidate_pairs(
    doc_sets: dict[str, list[dict]],
    topic_threshold: float = 0.25,
    max_pairs: int = 20,
) -> list[tuple[dict, dict]]:
    """
    Find chunk pairs from different documents that discuss the same topic.
    Filters for high n-gram overlap (same topic, different content).
    """
    doc_labels = list(doc_sets.keys())
    candidates: list[tuple[dict, dict, float]] = []

    for label_a, label_b in itertools.combinations(doc_labels, 2):
        chunks_a = doc_sets[label_a]
        chunks_b = doc_sets[label_b]

        for chunk_a in chunks_a:
            for chunk_b in chunks_b:
                content_a = chunk_a.get("content", "")[:500]
                content_b = chunk_b.get("content", "")[:500]
                sim = _ngram_similarity(content_a, content_b)
                # High similarity = same topic (possible contradiction territory)
                if sim >= topic_threshold:
                    candidates.append((chunk_a, chunk_b, sim))

    # Sort by similarity descending, take top N
    candidates.sort(key=lambda x: x[2], reverse=True)
    return [(a, b) for a, b, _ in candidates[:max_pairs]]


def detect_contradictions(
    query: str,
    doc_sets: dict[str, list[dict]],
    ollama_url: str,
    model: str,
    max_contradictions: int = 10,
) -> ContradictionReport:
    """
    Detect contradictions across document sets.

    Parameters
    ----------
    query:
        The user's question (used to focus the LLM verification).
    doc_sets:
        ``{label: [chunk_dicts]}`` — e.g. ``{"2023": [...], "2025": [...]}``
    ollama_url, model:
        Ollama endpoint and model.
    max_contradictions:
        Maximum number of contradictions to report.

    Returns
    -------
    ContradictionReport
    """
    import json
    import httpx

    if len(doc_sets) < 2:
        return ContradictionReport(
            contradictions=[],
            query=query,
            docs_compared=list(doc_sets.keys()),
            summary="Need at least 2 document sets to detect contradictions.",
        )

    # Get candidate pairs (same topic, potentially different claims)
    candidate_pairs = _candidate_pairs(doc_sets, topic_threshold=0.20)

    if not candidate_pairs:
        # If no close pairs, build a broader comparison for the LLM
        all_chunks_flat = [(k, c) for k, v in doc_sets.items() for c in v[:3]]
        confirmed = []
    else:
        # Ask LLM to verify each candidate pair
        confirmed: list[Contradiction] = []

        for chunk_a, chunk_b in candidate_pairs:
            if len(confirmed) >= max_contradictions:
                break

            label_a = chunk_a.get("_doc_label", chunk_a.get("file_path", "Doc A"))
            label_b = chunk_b.get("_doc_label", chunk_b.get("file_path", "Doc B"))
            year_a = chunk_a.get("doc_year")
            year_b = chunk_b.get("doc_year")

            prompt = f"""Compare these two statements from different documents and determine if they contradict each other.

Statement from {label_a} ({year_a or 'unknown year'}):
"{chunk_a.get('content', '')[:400]}"

Statement from {label_b} ({year_b or 'unknown year'}):
"{chunk_b.get('content', '')[:400]}"

Question context: {query}

Respond ONLY in JSON:
{{"is_contradiction": bool, "severity": "high|medium|low|none", "explanation": "brief explanation"}}"""

            try:
                resp = httpx.post(
                    f"{ollama_url.rstrip('/')}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "options": {"temperature": 0.0},
                    },
                    timeout=60.0,
                )
                resp.raise_for_status()
                content = resp.json().get("message", {}).get("content", "{}")

                # Extract JSON from response
                import re as _re
                m = _re.search(r"\{.*\}", content, _re.DOTALL)
                if not m:
                    continue

                result = json.loads(m.group(0))
                if result.get("is_contradiction") and result.get("severity", "none") != "none":
                    confirmed.append(Contradiction(
                        claim_a=chunk_a.get("content", "")[:300],
                        claim_b=chunk_b.get("content", "")[:300],
                        doc_a=str(label_a),
                        doc_b=str(label_b),
                        year_a=year_a,
                        year_b=year_b,
                        severity=result.get("severity", "low"),
                        explanation=result.get("explanation", ""),
                    ))
            except Exception:
                continue

    # Generate overall summary
    if confirmed:
        summary_prompt = (
            f"Summarize these {len(confirmed)} contradictions found between documents "
            f"in response to the question: '{query}'\n\n"
            + "\n".join(
                f"- {c.doc_a} vs {c.doc_b} ({c.severity}): {c.explanation}"
                for c in confirmed
            )
            + "\n\nProvide a 2-3 sentence summary:"
        )

        try:
            resp = httpx.post(
                f"{ollama_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": summary_prompt}],
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
                timeout=60.0,
            )
            summary = resp.json().get("message", {}).get("content", "").strip()
        except Exception:
            summary = f"Found {len(confirmed)} contradictions across {len(doc_sets)} documents."
    else:
        summary = "No significant contradictions were detected between the provided documents."

    return ContradictionReport(
        contradictions=confirmed,
        query=query,
        docs_compared=list(doc_sets.keys()),
        summary=summary,
    )
