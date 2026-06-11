"""
Heuristic execution plan templates for each TaskType.

Each template returns a pre-built ExecutionPlan without any LLM round-trip.
For novel or complex queries the AgentPlanner may fall through to LLM-based
planning, but these templates handle the vast majority of production queries.
"""
from __future__ import annotations

from core.agent_planner.types import (
    ClassificationResult,
    ExecutionPlan,
    TaskType,
    ToolCall,
)


def _lookup_template(
    query: str, cls: ClassificationResult, config: dict
) -> ExecutionPlan:
    return ExecutionPlan(
        task_type=TaskType.LOOKUP,
        steps=[
            ToolCall(
                tool_name="retrieve_documents",
                arguments={
                    "query": query,
                    "limit": config.get("retrieval_limit", 5),
                },
                parallel_group=0,
                call_id="retrieve_main",
            )
        ],
        reasoning="Single lookup — one hybrid BM25+vector query suffices.",
        estimated_doc_coverage=[],
    )


def _summarization_template(
    query: str, cls: ClassificationResult, config: dict
) -> ExecutionPlan:
    return ExecutionPlan(
        task_type=TaskType.SUMMARIZATION,
        steps=[
            ToolCall(
                tool_name="retrieve_documents",
                arguments={
                    "query": query,
                    "limit": 8,
                },
                parallel_group=0,
                call_id="retrieve_summary",
            )
        ],
        reasoning="Summarization — retrieve broad set of chunks, LLM will summarize.",
        estimated_doc_coverage=cls.target_docs,
    )


def _comparison_template(
    query: str, cls: ClassificationResult, config: dict
) -> ExecutionPlan:
    years = cls.years_in_range()
    chunks_per_doc = config.get("comparison_chunks_per_doc", 4)

    if not years:
        # No specific years — compare all available docs
        return ExecutionPlan(
            task_type=TaskType.COMPARISON,
            steps=[
                ToolCall(
                    tool_name="retrieve_documents",
                    arguments={"query": query, "limit": 10},
                    parallel_group=0,
                    call_id="retrieve_all",
                )
            ],
            reasoning="Comparison without specific years — broad retrieval for LLM to compare.",
            estimated_doc_coverage=[],
        )

    # Per-year parallel retrieval + comparison synthesis
    retrieve_steps = [
        ToolCall(
            tool_name="retrieve_by_metadata",
            arguments={
                "query": query,
                "doc_year": year,
                "limit": chunks_per_doc,
            },
            parallel_group=1,
            call_id=f"retrieve_{year}",
        )
        for year in years
    ]

    compare_step = ToolCall(
        tool_name="compare_document_sets",
        arguments={"query": query},
        parallel_group=2,
        depends_on=[f"retrieve_{year}" for year in years],
        call_id="compare",
    )

    return ExecutionPlan(
        task_type=TaskType.COMPARISON,
        steps=retrieve_steps + [compare_step],
        reasoning=(
            f"Comparison across {len(years)} years {years}. "
            "Parallel per-year retrieval then comparative synthesis."
        ),
        estimated_doc_coverage=[str(y) for y in years],
    )


def _trend_template(
    query: str, cls: ClassificationResult, config: dict
) -> ExecutionPlan:
    years = cls.years_in_range()
    chunks_per_doc = config.get("comparison_chunks_per_doc", 4)

    retrieve_steps = [
        ToolCall(
            tool_name="retrieve_by_metadata",
            arguments={
                "query": query,
                "doc_year": year,
                "limit": chunks_per_doc,
            },
            parallel_group=1,
            call_id=f"retrieve_{year}",
        )
        for year in years
    ] if years else [
        ToolCall(
            tool_name="retrieve_documents",
            arguments={"query": query, "limit": 10},
            parallel_group=0,
            call_id="retrieve_trend",
        )
    ]

    return ExecutionPlan(
        task_type=TaskType.TREND_ANALYSIS,
        steps=retrieve_steps,
        reasoning="Trend analysis — per-year retrieval sorted chronologically.",
        estimated_doc_coverage=[str(y) for y in years],
    )


def _timeline_template(
    query: str, cls: ClassificationResult, config: dict
) -> ExecutionPlan:
    return ExecutionPlan(
        task_type=TaskType.TIMELINE,
        steps=[
            ToolCall(
                tool_name="build_timeline",
                arguments={
                    "query": query,
                    "time_range": list(cls.time_range) if cls.time_range else None,
                    "semantic_limit": 12,
                },
                parallel_group=0,
                call_id="build_timeline",
            )
        ],
        reasoning="Timeline — merge SQL events + semantic chunks, sort chronologically.",
        estimated_doc_coverage=[],
    )


def _contradiction_template(
    query: str, cls: ClassificationResult, config: dict
) -> ExecutionPlan:
    years = cls.years_in_range()
    chunks_per_doc = config.get("comparison_chunks_per_doc", 5)

    retrieve_steps = [
        ToolCall(
            tool_name="retrieve_by_metadata",
            arguments={
                "query": query,
                "doc_year": year,
                "limit": chunks_per_doc,
            },
            parallel_group=1,
            call_id=f"retrieve_{year}",
        )
        for year in years
    ] if years else [
        ToolCall(
            tool_name="retrieve_documents",
            arguments={"query": query, "limit": 10},
            parallel_group=1,
            call_id="retrieve_all",
        )
    ]

    depend_ids = [f"retrieve_{year}" for year in years] if years else ["retrieve_all"]
    contradiction_step = ToolCall(
        tool_name="detect_contradictions",
        arguments={"query": query},
        parallel_group=2,
        depends_on=depend_ids,
        call_id="contradictions",
    )

    return ExecutionPlan(
        task_type=TaskType.CONTRADICTION,
        steps=retrieve_steps + [contradiction_step],
        reasoning="Contradiction detection — per-doc retrieval then pairwise verification.",
        estimated_doc_coverage=[str(y) for y in years],
    )


def _financial_template(
    query: str, cls: ClassificationResult, config: dict
) -> ExecutionPlan:
    return ExecutionPlan(
        task_type=TaskType.FINANCIAL,
        steps=[
            ToolCall(
                tool_name="retrieve_financials",
                arguments={
                    "query": query,
                    "time_range": list(cls.time_range) if cls.time_range else None,
                },
                parallel_group=0,
                call_id="financials",
            ),
            ToolCall(
                tool_name="retrieve_documents",
                arguments={
                    "query": query,
                    "limit": 3,
                    "section_filter": "financial",
                },
                parallel_group=0,
                call_id="financial_context",
            ),
        ],
        reasoning="Financial query — structured SQL lookup + semantic financial section context.",
        estimated_doc_coverage=[],
    )


def _risk_template(
    query: str, cls: ClassificationResult, config: dict
) -> ExecutionPlan:
    years = cls.years_in_range()
    chunks_per_doc = config.get("comparison_chunks_per_doc", 6)

    if years:
        steps = [
            ToolCall(
                tool_name="retrieve_risk_factors",
                arguments={
                    "query": query,
                    "doc_year": year,
                    "limit": chunks_per_doc,
                },
                parallel_group=1,
                call_id=f"risk_{year}",
            )
            for year in years
        ]
    else:
        steps = [
            ToolCall(
                tool_name="retrieve_risk_factors",
                arguments={
                    "query": query,
                    "doc_year": None,
                    "limit": 6,
                },
                parallel_group=0,
                call_id="risk_all",
            )
        ]

    return ExecutionPlan(
        task_type=TaskType.RISK_ANALYSIS,
        steps=steps,
        reasoning="Risk analysis — section-targeted retrieval for 'Risk Factors'.",
        estimated_doc_coverage=[str(y) for y in years],
    )


# ── Template registry ──────────────────────────────────────────────────────────

TASK_TEMPLATES: dict[TaskType, callable] = {
    TaskType.LOOKUP:         _lookup_template,
    TaskType.SUMMARIZATION:  _summarization_template,
    TaskType.COMPARISON:     _comparison_template,
    TaskType.TREND_ANALYSIS: _trend_template,
    TaskType.TIMELINE:       _timeline_template,
    TaskType.CONTRADICTION:  _contradiction_template,
    TaskType.FINANCIAL:      _financial_template,
    TaskType.RISK_ANALYSIS:  _risk_template,
}


def get_plan(
    query: str,
    classification: ClassificationResult,
    config: dict,
) -> ExecutionPlan:
    """
    Return an ExecutionPlan for the given classification.
    Always returns a plan — unknown task types fall through to LOOKUP.
    """
    template = TASK_TEMPLATES.get(classification.task_type, _lookup_template)
    return template(query, classification, config)
