"""
Benchmark runner for Palimind's agentic RAG evaluation suite.

Usage:
    python -m tests.eval.runner --root /path/to/your/docs
    python -m tests.eval.runner --root /path/to/your/docs --category multi_document
    python -m tests.eval.runner --root /path/to/your/docs --test-id CD-001
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class BenchmarkScore:
    test_id: str
    category: str
    query: str

    # Retrieval quality
    task_type_correct: bool
    doc_coverage: float          # expected docs found / expected docs total
    year_coverage: float         # expected years found / expected years total

    # Answer quality (heuristic: checked by simple criteria matching)
    criteria_pass_rate: float    # fraction of grading criteria passed
    has_sources: bool
    has_citations: bool

    # System timing
    retrieval_latency_ms: float
    total_latency_ms: float

    # Raw
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    task_type_got: str = ""
    error: str = ""

    @property
    def composite_score(self) -> float:
        if self.error:
            return 0.0
        return (
            0.30 * self.criteria_pass_rate +
            0.25 * self.year_coverage +
            0.20 * self.doc_coverage +
            0.15 * (1.0 if self.task_type_correct else 0.0) +
            0.10 * (1.0 if self.has_citations else 0.0)
        )

    @property
    def passed(self) -> bool:
        return self.composite_score >= 0.5


def _check_year_coverage(sources: list[str], expected_years: list[int]) -> float:
    if not expected_years:
        return 1.0
    found = 0
    for year in expected_years:
        if any(str(year) in s for s in sources):
            found += 1
    return found / len(expected_years)


def _check_doc_coverage(sources: list[str], expected_docs: list[str]) -> float:
    if not expected_docs:
        return 1.0 if sources else 0.0
    found = 0
    for doc in expected_docs:
        doc_name = doc.split("/")[-1].lower()
        if any(doc_name in s.lower() or s.lower() in doc_name for s in sources):
            found += 1
    return found / len(expected_docs)


def _check_criteria_heuristic(answer: str, criteria: list[str]) -> float:
    """
    Lightweight heuristic criteria checker.
    Checks for keyword presence; for full evaluation use an LLM judge.
    """
    if not criteria or not answer:
        return 0.0

    answer_lower = answer.lower()
    passed = 0

    for criterion in criteria:
        crit_lower = criterion.lower()

        # Keyword heuristics based on criterion text
        if "cites" in crit_lower or "source" in crit_lower:
            # Check for source citations in answer
            if any(kw in answer_lower for kw in ["source", "according to", "10-k", "annual report", "filing"]):
                passed += 1
        elif "at least" in crit_lower and "distinct" in crit_lower:
            # Check for enumeration (at least N things)
            import re
            bullets = len(re.findall(r"[•\-\*]\s", answer))
            numbered = len(re.findall(r"\d+\.", answer))
            if bullets + numbered >= 2:
                passed += 1
        elif "chronological" in crit_lower or "order" in crit_lower:
            # Check for year mentions in order
            import re
            years = [int(y) for y in re.findall(r"20\d{2}", answer)]
            if years == sorted(years) and len(years) >= 2:
                passed += 1
        elif "quantitative" in crit_lower or "figure" in crit_lower or "number" in crit_lower:
            # Check for numbers in answer
            import re
            if re.search(r"\$[\d,.]+|\d+\.?\d*%|\d+\s*(billion|million)", answer, re.IGNORECASE):
                passed += 1
        elif "hallucin" in crit_lower or "fabricat" in crit_lower or "not make up" in crit_lower:
            # Assume passing unless we have a way to detect hallucination
            passed += 1
        else:
            # Default: check if any word from the criterion appears in the answer
            key_words = [w for w in crit_lower.split() if len(w) > 4]
            if key_words and any(w in answer_lower for w in key_words[:3]):
                passed += 1

    return passed / len(criteria)


def run_single_test(
    test: "BenchmarkTest",
    root: Path,
) -> BenchmarkScore:
    """Run a single benchmark test and return its score."""
    import traceback
    from core.querying import query_stream_with_diagnostics
    from core.generative.responder import generate_response

    start = time.monotonic()
    error = ""
    answer = ""
    sources = []
    task_type_got = ""
    retrieval_ms = 0.0

    try:
        t0 = time.monotonic()
        context, stream, diagnostics = query_stream_with_diagnostics(
            root,
            test.query,
        )
        retrieval_ms = (time.monotonic() - t0) * 1000

        answer = generate_response(stream)
        sources = list(context.sources) if context.sources else []

        if diagnostics:
            task_type_got = diagnostics.task_type

    except Exception as exc:
        error = str(exc)
        traceback.print_exc()

    total_ms = (time.monotonic() - start) * 1000

    # Compute scores
    task_type_correct = task_type_got == test.expected_task_type.name
    year_coverage = _check_year_coverage(sources, test.expected_years)
    doc_coverage = _check_doc_coverage(sources, test.expected_docs)
    criteria_rate = _check_criteria_heuristic(answer, test.grading_criteria)
    has_sources = len(sources) > 0
    has_citations = any(
        kw in answer.lower()
        for kw in ["source", "according", "10-k", "filing", "report", "document"]
    )

    return BenchmarkScore(
        test_id=test.test_id,
        category=test.category,
        query=test.query,
        task_type_correct=task_type_correct,
        doc_coverage=doc_coverage,
        year_coverage=year_coverage,
        criteria_pass_rate=criteria_rate,
        has_sources=has_sources,
        has_citations=has_citations,
        retrieval_latency_ms=retrieval_ms,
        total_latency_ms=total_ms,
        answer=answer[:500],  # truncate for report
        sources=sources,
        task_type_got=task_type_got,
        error=error,
    )


def run_benchmark(
    tests: list["BenchmarkTest"],
    root: Path,
    *,
    category: str | None = None,
    test_id: str | None = None,
    verbose: bool = True,
) -> list[BenchmarkScore]:
    """
    Run the benchmark suite and return scores.

    Parameters
    ----------
    tests: List of BenchmarkTest objects.
    root: Project root with indexed documents.
    category: If set, only run tests from this category.
    test_id: If set, only run this single test.
    verbose: Print progress to stdout.
    """
    from tests.eval.benchmark_suite import BenchmarkTest

    # Filter tests
    filtered = tests
    if category:
        filtered = [t for t in filtered if t.category == category]
    if test_id:
        filtered = [t for t in filtered if t.test_id == test_id]

    if not filtered:
        print("No tests matched the filter criteria.")
        return []

    scores: list[BenchmarkScore] = []
    for i, test in enumerate(filtered, 1):
        if verbose:
            print(f"\n[{i}/{len(filtered)}] Running {test.test_id}: {test.query[:60]}...")

        score = run_single_test(test, root)
        scores.append(score)

        if verbose:
            status = "✅ PASS" if score.passed else "❌ FAIL"
            print(f"  {status} — composite: {score.composite_score:.0%} "
                  f"(task_type={'✓' if score.task_type_correct else f'✗ got {score.task_type_got}'}, "
                  f"year_cov={score.year_coverage:.0%}, "
                  f"criteria={score.criteria_pass_rate:.0%}, "
                  f"latency={score.total_latency_ms:.0f}ms)")
            if score.error:
                print(f"  ERROR: {score.error}")

    # Summary report
    if verbose and scores:
        print("\n" + "=" * 60)
        print("BENCHMARK RESULTS SUMMARY")
        print("=" * 60)

        categories: dict[str, list[BenchmarkScore]] = {}
        for s in scores:
            categories.setdefault(s.category, []).append(s)

        for cat, cat_scores in sorted(categories.items()):
            composite = statistics.mean(s.composite_score for s in cat_scores)
            pass_rate = sum(1 for s in cat_scores if s.passed) / len(cat_scores)
            print(f"\n{cat}:")
            print(f"  Composite score: {composite:.0%}")
            print(f"  Pass rate: {pass_rate:.0%} ({sum(1 for s in cat_scores if s.passed)}/{len(cat_scores)})")

        overall = statistics.mean(s.composite_score for s in scores)
        overall_pass = sum(1 for s in scores if s.passed) / len(scores)
        print(f"\nOVERALL: {overall:.0%} composite, {overall_pass:.0%} pass rate")
        print(f"Avg latency: {statistics.mean(s.total_latency_ms for s in scores):.0f}ms")

    return scores


def save_results(scores: list[BenchmarkScore], output_path: Path) -> None:
    """Save benchmark results to a JSON file."""
    results = []
    for s in scores:
        d = {
            "test_id": s.test_id,
            "category": s.category,
            "query": s.query,
            "composite_score": round(s.composite_score, 3),
            "passed": s.passed,
            "task_type_correct": s.task_type_correct,
            "task_type_got": s.task_type_got,
            "year_coverage": round(s.year_coverage, 3),
            "doc_coverage": round(s.doc_coverage, 3),
            "criteria_pass_rate": round(s.criteria_pass_rate, 3),
            "has_sources": s.has_sources,
            "has_citations": s.has_citations,
            "total_latency_ms": round(s.total_latency_ms, 1),
            "sources": s.sources,
            "answer_preview": s.answer[:200],
            "error": s.error,
        }
        results.append(d)

    output_path.write_text(json.dumps({"results": results}, indent=2))
    print(f"\nResults saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Run Palimind benchmark suite")
    parser.add_argument("--root", required=True, help="Path to the indexed document directory")
    parser.add_argument("--category", default=None, help="Filter by category")
    parser.add_argument("--test-id", default=None, help="Run a single test by ID")
    parser.add_argument("--output", default=None, help="Save results to JSON file")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"Error: root path does not exist: {root}")
        sys.exit(1)

    from tests.eval.benchmark_suite import BENCHMARK_SUITE

    scores = run_benchmark(
        BENCHMARK_SUITE,
        root,
        category=args.category,
        test_id=args.test_id,
    )

    if args.output and scores:
        save_results(scores, Path(args.output))


if __name__ == "__main__":
    main()
