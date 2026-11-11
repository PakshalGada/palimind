"""Unit tests for the RAG evaluation metrics (no index or model needed)."""

from __future__ import annotations

from palimind.rag.evaluation import (
    aggregate,
    evaluate_case,
    first_match_rank,
    ndcg_at_k,
    phrase_hit,
    result_matches,
)


def _r(file_path: str, section: str = "", page: int | None = None, content: str = "") -> dict:
    return {
        "file_path": file_path,
        "section_title": section,
        "page_number": page,
        "content": content,
    }


def test_result_matches_file_section_and_page() -> None:
    result = _r("reports/annual_2023.pdf", "Risk Factors", 12)
    assert result_matches(result, {"file": "annual_2023.pdf"})
    assert result_matches(result, {"file": "reports/annual_2023.pdf", "section": "risk factors"})
    assert result_matches(result, {"file": "annual_2023.pdf", "page": 12})
    assert not result_matches(result, {"file": "annual_2023.pdf", "section": "Revenue"})
    assert not result_matches(result, {"file": "other.pdf"})


def test_first_match_rank_and_ndcg() -> None:
    results = [_r("b.md"), _r("a.md"), _r("c.md")]
    assert first_match_rank(results, {"file": "a.md"}) == 2
    assert first_match_rank(results, {"file": "z.md"}) is None

    # A single relevant result at rank 1 is a perfect score.
    assert ndcg_at_k([1, 0, 0], 3) == 1.0
    # Rank 2 is discounted by log2(3).
    expected = (1 / 1.584962500721156) / (1 / 1.0)
    assert abs(ndcg_at_k([0, 1, 0], 3) - expected) < 1e-9


def test_evaluate_case_recall_mrr_and_multi_source() -> None:
    results = [_r("a.md", "Revenue"), _r("b.md", "Method"), _r("c.md", "Risks")]
    metrics = evaluate_case(
        results,
        [{"file": "c.md", "section": "Risks"}, {"file": "a.md", "section": "Revenue"}],
        recall_ks=(1, 5),
        ndcg_k=3,
    )
    assert metrics["recall@1"] == 0.5  # only a.md is inside the top-1
    assert metrics["recall@5"] == 1.0
    assert metrics["mrr"] == 1.0  # a.md is rank 1
    assert 0.0 < metrics["ndcg@3"] < 1.0


def test_phrase_hit_uses_top_k_passages() -> None:
    results = [_r("a.md", content="Revenue was $4.2 billion.")]
    assert phrase_hit(results, ["4.2 billion"]) == 1.0
    assert phrase_hit(results, ["4.2 billion", "not present"]) == 0.5
    assert phrase_hit(results, []) == 1.0


def test_aggregate_reports_means_and_latency_percentiles() -> None:
    cases = [
        {"recall@5": 1.0, "recall@10": 1.0, "mrr": 1.0, "ndcg@10": 1.0, "phrase_hit": 1.0, "latency_ms": 10},
        {"recall@5": 0.0, "recall@10": 0.5, "mrr": 0.5, "ndcg@10": 0.5, "phrase_hit": 0.5, "latency_ms": 30},
    ]
    summary = aggregate(cases)
    assert summary["cases"] == 2
    assert summary["recall@5"] == 0.5
    assert summary["mrr"] == 0.75
    assert summary["latency_ms_mean"] == 20.0
    assert summary["latency_ms_p95"] == 30.0
