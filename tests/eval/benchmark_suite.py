"""
Palimind Agentic RAG Evaluation Benchmark Suite.

Tests cover 5 categories:
  SD  — single document (lookup, financial, risk)
  MD  — multi-document (comparison, trend)
  CD  — cross-document (comparison, timeline)
  AR  — agentic reasoning (multi-step)
  CON — contradiction detection

Usage:
    from tests.eval.benchmark_suite import BENCHMARK_SUITE, BenchmarkTest
    from tests.eval.runner import run_benchmark
    
    scores = run_benchmark(BENCHMARK_SUITE, root=Path("/path/to/docs"))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.agent_planner.types import TaskType


@dataclass
class BenchmarkTest:
    """A single benchmark test case."""
    test_id: str
    category: str           # "single_document" | "multi_document" | "cross_document" | "agentic_reasoning" | "contradiction"
    query: str
    expected_task_type: TaskType
    grading_criteria: list[str]
    expected_docs: list[str] = field(default_factory=list)   # file paths that should be cited
    expected_years: list[int] = field(default_factory=list)  # years that should appear
    reference_answer: str = ""
    min_score: float = 0.6   # Minimum acceptable composite score

    def __str__(self) -> str:
        return f"[{self.test_id}] {self.query[:60]}..."


# ── Benchmark test cases ───────────────────────────────────────────────────────

BENCHMARK_SUITE: list[BenchmarkTest] = [

    # ── Single Document ────────────────────────────────────────────────────────
    BenchmarkTest(
        test_id="SD-001",
        category="single_document",
        query="What was Apple's total revenue in fiscal year 2024?",
        expected_task_type=TaskType.FINANCIAL,
        grading_criteria=[
            "Provides a specific revenue figure",
            "Cites a 2024 source document",
            "Figure uses correct currency (USD) and scale (billions/millions)",
        ],
        expected_years=[2024],
        min_score=0.7,
    ),
    BenchmarkTest(
        test_id="SD-002",
        category="single_document",
        query="What are the main risk factors disclosed in Apple's most recent 10-K?",
        expected_task_type=TaskType.RISK_ANALYSIS,
        grading_criteria=[
            "Lists at least 3 distinct risk categories",
            "Mentions at least one of: AI regulation, supply chain, competition, legal",
            "Cites the source document",
            "Does not hallucinate risk factors not present in the document",
        ],
        min_score=0.65,
    ),
    BenchmarkTest(
        test_id="SD-003",
        category="single_document",
        query="What is Apple's business overview?",
        expected_task_type=TaskType.SUMMARIZATION,
        grading_criteria=[
            "Covers Apple's main product and service segments",
            "Mentions at least one financial scale metric",
            "Is coherent and structured",
        ],
        min_score=0.65,
    ),

    # ── Multi Document ─────────────────────────────────────────────────────────
    BenchmarkTest(
        test_id="MD-001",
        category="multi_document",
        query="How did Apple's gross margin change from 2023 to 2025?",
        expected_task_type=TaskType.COMPARISON,
        grading_criteria=[
            "Cites both 2023 and 2025 source documents",
            "Provides gross margin figures (or percentages) for both years",
            "States the direction of change (improved/declined/stable)",
            "Attributes the change to at least one factor",
        ],
        expected_years=[2023, 2025],
        min_score=0.70,
    ),
    BenchmarkTest(
        test_id="MD-002",
        category="multi_document",
        query="Did Apple's stated AI strategy evolve between 2023 and 2025?",
        expected_task_type=TaskType.COMPARISON,
        grading_criteria=[
            "Cites at least 2 different year filings",
            "Identifies specific language or strategic changes",
            "Draws a chronological conclusion about the evolution",
            "Does not make up AI initiatives not in the documents",
        ],
        expected_years=[2023, 2025],
        min_score=0.65,
    ),
    BenchmarkTest(
        test_id="MD-003",
        category="multi_document",
        query="What financial trends can be observed in Apple's annual reports from 2023 to 2025?",
        expected_task_type=TaskType.TREND_ANALYSIS,
        grading_criteria=[
            "Covers at least 2 years of data",
            "Identifies at least 2 distinct financial trends",
            "Uses quantitative data where available",
            "Presents trends in chronological order",
        ],
        expected_years=[2023, 2024, 2025],
        min_score=0.65,
    ),

    # ── Cross Document ─────────────────────────────────────────────────────────
    BenchmarkTest(
        test_id="CD-001",
        category="cross_document",
        query="How did Apple's risk profile change between 2023 and 2025?",
        expected_task_type=TaskType.COMPARISON,
        grading_criteria=[
            "Cites both 2023 and 2025 documents",
            "Compares specific named risk categories (not generic platitudes)",
            "Identifies at least one risk that emerged, intensified, or diminished",
            "Does not hallucinate a risk factor",
            "Discusses changes — not just describes risks from one year",
        ],
        expected_years=[2023, 2025],
        min_score=0.70,
    ),
    BenchmarkTest(
        test_id="CD-002",
        category="cross_document",
        query="Create a timeline of Apple's major risk disclosures from 2023 to 2025",
        expected_task_type=TaskType.TIMELINE,
        grading_criteria=[
            "Events are in chronological order",
            "Includes at least 3 distinct events or risk disclosures",
            "Each event is attributed to a specific year",
            "Cites at least 2 different year sources",
        ],
        expected_years=[2023, 2024, 2025],
        min_score=0.65,
    ),
    BenchmarkTest(
        test_id="CD-003",
        category="cross_document",
        query="Compare Apple's competitive positioning as described in the 2023 vs 2025 annual reports",
        expected_task_type=TaskType.COMPARISON,
        grading_criteria=[
            "References both years explicitly",
            "Discusses competitive dynamics from multiple angles",
            "Notes any shifts in competitive language or concerns",
            "Specific enough to be useful (not just 'Apple faces competition')",
        ],
        expected_years=[2023, 2025],
        min_score=0.65,
    ),

    # ── Agentic Reasoning ──────────────────────────────────────────────────────
    BenchmarkTest(
        test_id="AR-001",
        category="agentic_reasoning",
        query="Which of Apple's 2023 risk factors were no longer mentioned in 2025, and which new ones appeared?",
        expected_task_type=TaskType.CONTRADICTION,
        grading_criteria=[
            "Retrieves from both 2023 and 2025 documents (multi-step reasoning)",
            "Identifies at least one risk present in 2023 but absent in 2025",
            "Identifies at least one risk in 2025 not present in 2023",
            "Does not confabulate specific risk factors",
            "Provides a structured answer (not just comparison prose)",
        ],
        expected_years=[2023, 2025],
        min_score=0.60,
    ),
    BenchmarkTest(
        test_id="AR-002",
        category="agentic_reasoning",
        query="What is the trend in Apple's R&D spending and how does it relate to their AI strategy evolution?",
        expected_task_type=TaskType.TREND_ANALYSIS,
        grading_criteria=[
            "Provides R&D spending data from at least 2 years",
            "Connects R&D trend to AI strategy mentions",
            "Draws an evidence-based conclusion",
            "Cites source documents",
        ],
        min_score=0.60,
    ),

    # ── Contradiction ──────────────────────────────────────────────────────────
    BenchmarkTest(
        test_id="CON-001",
        category="contradiction",
        query="Does Apple's 2025 10-K contradict any forward-looking statements from the 2023 10-K?",
        expected_task_type=TaskType.CONTRADICTION,
        grading_criteria=[
            "Retrieves from both 2023 and 2025",
            "Identifies at least one specific inconsistency (or correctly states none found)",
            "Quotes or closely paraphrases actual document text",
            "Rates the significance of any contradictions found",
        ],
        expected_years=[2023, 2025],
        min_score=0.55,
    ),
    BenchmarkTest(
        test_id="CON-002",
        category="contradiction",
        query="Are there any inconsistencies in how Apple describes its supply chain risks across their annual reports?",
        expected_task_type=TaskType.CONTRADICTION,
        grading_criteria=[
            "Searches across multiple years",
            "Specifically addresses supply chain risk language",
            "Notes any evolution in language that could indicate policy shift",
            "Does not fabricate contradictions",
        ],
        min_score=0.55,
    ),
]
