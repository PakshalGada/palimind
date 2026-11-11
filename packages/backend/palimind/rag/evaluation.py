"""Pure retrieval-quality metrics for the RAG evaluation harness.

Keeping the metric maths in the package (rather than in the CLI script) makes
it unit-testable without an index, embeddings, or a model. The CLI in
``scripts/rag_eval.py`` only orchestrates the fixture workspace and feeds
ranked results into these helpers.
"""

from __future__ import annotations

import math
from typing import Any


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("\\", "/").split())


def result_matches(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Return whether a retrieved result satisfies one expected source.

    ``expected`` supports ``file`` (required), ``section`` and ``page``. File
    matching accepts a full relative path or an unambiguous suffix, because the
    evaluator may name a file by basename while the index stores a relative
    path (and vice versa).
    """
    file_n = _norm(result.get("file_path"))
    expected_file = _norm(expected.get("file"))
    if not file_n or not expected_file:
        return False
    if not (
        file_n == expected_file
        or file_n.endswith(f"/{expected_file}")
        or expected_file.endswith(f"/{file_n}")
        or expected_file in file_n
    ):
        return False

    section = _norm(expected.get("section"))
    if section:
        fields = [
            _norm(result.get(key))
            for key in ("section_title", "main_section", "parent_section")
        ]
        if not any(section in field or field in section for field in fields if field):
            return False

    page = expected.get("page")
    if page is not None and result.get("page_number") is not None:
        try:
            return int(result["page_number"]) == int(page)
        except (TypeError, ValueError):
            return False
    return True


def first_match_rank(results: list[dict[str, Any]], expected: dict[str, Any]) -> int | None:
    """1-based rank of the first result matching *expected*, or ``None``."""
    for rank, result in enumerate(results, start=1):
        if result_matches(result, expected):
            return rank
    return None


def ndcg_at_k(relevances: list[int], k: int) -> float:
    """Binary-relevance nDCG@k."""
    if k <= 0:
        return 0.0
    dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevances[:k], start=1))
    ideal = sorted(relevances, reverse=True)[:k]
    idcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def evaluate_case(
    results: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    *,
    recall_ks: tuple[int, ...] = (5, 10),
    ndcg_k: int = 10,
) -> dict[str, Any]:
    """Score one query against its expected sources."""
    total = len(expected)
    ranks = [first_match_rank(results, item) for item in expected]

    metrics: dict[str, Any] = {
        "expected_total": total,
        "ranks": ranks,
        "matched": sum(1 for rank in ranks if rank is not None),
    }
    for k in recall_ks:
        hits = sum(1 for rank in ranks if rank is not None and rank <= k)
        metrics[f"recall@{k}"] = (hits / total) if total else 0.0

    mrr = 0.0
    found_ranks = [rank for rank in ranks if rank is not None]
    if found_ranks:
        mrr = 1.0 / min(found_ranks)
    metrics[f"mrr@{max(recall_ks, default=10)}"] = mrr
    metrics["mrr"] = mrr

    relevances = [
        1 if any(result_matches(result, item) for item in expected) else 0
        for result in results[:ndcg_k]
    ]
    metrics[f"ndcg@{ndcg_k}"] = ndcg_at_k(relevances, ndcg_k)
    return metrics


def phrase_hit(results: list[dict[str, Any]], phrases: list[str], *, k: int = 10) -> float:
    """Fraction of expected verbatim phrases present in the top-k passages."""
    wanted = [phrase for phrase in phrases if str(phrase).strip()]
    if not wanted:
        return 1.0
    joined = "\n".join(str(result.get("content") or "") for result in results[:k]).lower()
    found = sum(1 for phrase in wanted if str(phrase).lower() in joined)
    return found / len(wanted)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case metrics into a report summary."""
    total = len(cases)
    if not total:
        return {"cases": 0}

    def mean(key: str) -> float:
        values = []
        for case in cases:
            metrics = case.get("metrics")
            if isinstance(metrics, dict) and key in metrics:
                values.append(float(metrics.get(key) or 0.0))
            else:
                values.append(float(case.get(key) or 0.0))
        return sum(values) / len(values)

    latencies = [float(case.get("latency_ms") or 0.0) for case in cases]
    return {
        "cases": total,
        "recall@5": round(mean("recall@5"), 4),
        "recall@10": round(mean("recall@10"), 4),
        "mrr": round(mean("mrr"), 4),
        "ndcg@10": round(mean("ndcg@10"), 4),
        "phrase_hit": round(mean("phrase_hit"), 4),
        "latency_ms_mean": round(sum(latencies) / len(latencies), 1),
        "latency_ms_p50": round(_percentile(latencies, 0.50), 1),
        "latency_ms_p95": round(_percentile(latencies, 0.95), 1),
    }
