"""
Agent Planner — the central orchestrator for Palimind's agentic pipeline.

The planner implements a lightweight ReAct (Reason + Act) loop:

  1. Classify the query → TaskType
  2. Generate an ExecutionPlan (from heuristic templates)
  3. Execute the plan via ToolExecutor
  4. Reflect: is the retrieved evidence sufficient?
     • If yes → assemble context and return AgentResult
     • If no and iterations remain → re-plan with expanded scope
  5. Assemble context using task-appropriate strategy
  6. Return AgentResult for the LLM responder

The planner is intentionally model-agnostic: it does not call an LLM for
planning (only for tool actions like compare/contradiction). This keeps
first-query latency low and makes behavior predictable and debuggable.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.agent_planner.classifier import classify_query
from core.agent_planner.executor import ToolExecutor
from core.agent_planner.templates import get_plan
from core.agent_planner.types import (
    AgentResult,
    ClassificationResult,
    ExecutionPlan,
    ReflectionResult,
    TaskType,
    ToolResult,
)
from core.context.assembler import assemble_context


# ── Reflection helper ──────────────────────────────────────────────────────────

def _reflect(
    classification: ClassificationResult,
    tool_results: list[ToolResult],
) -> ReflectionResult:
    """
    Check whether the tool execution produced enough evidence.

    Heuristic rules (no LLM needed):
    • All tool calls succeeded AND at least one returned non-empty data → sufficient.
    • Comparison task: check that we got chunks from at least 2 different doc_years.
    • Contradiction task: same as comparison.
    """
    successful = [r for r in tool_results if r.success]

    if not successful:
        return ReflectionResult(
            sufficient=False,
            reason="All tool calls failed or returned no results.",
        )

    # Collect all flat chunks from successful retrieval results
    all_chunks: list[dict] = []
    for result in successful:
        data = result.data
        if isinstance(data, list):
            all_chunks.extend(data)
        # FinancialsResult
        elif hasattr(data, "context_chunks"):
            all_chunks.extend(data.context_chunks or [])

    if not all_chunks and classification.task_type not in (
        TaskType.TIMELINE, TaskType.COMPARISON, TaskType.CONTRADICTION
    ):
        return ReflectionResult(
            sufficient=False,
            reason="No chunks were retrieved.",
        )

    # For comparison/contradiction: verify multi-doc coverage
    if classification.task_type in (TaskType.COMPARISON, TaskType.CONTRADICTION, TaskType.TREND_ANALYSIS):
        years_covered = {c.get("doc_year") for c in all_chunks if c.get("doc_year")}
        files_covered = {c.get("file_path") for c in all_chunks}

        expected_years = set(classification.years_in_range())
        if expected_years and len(years_covered & expected_years) < max(1, len(expected_years) - 1):
            missing = expected_years - years_covered
            return ReflectionResult(
                sufficient=False,
                reason=f"Missing evidence from years: {missing}",
                missing_docs=[str(y) for y in missing],
                suggested_replan="Broaden search — remove section filter and retry.",
            )

    return ReflectionResult(sufficient=True, reason="Sufficient evidence gathered.")


# ── Context assembly from tool results ────────────────────────────────────────

def _collect_chunks_from_results(tool_results: list[ToolResult]) -> list[dict]:
    """Flatten all chunks from successful tool results into a single list."""
    chunks: list[dict] = []
    for result in tool_results:
        if not result.success:
            continue
        data = result.data
        if isinstance(data, list):
            chunks.extend(data)
        elif hasattr(data, "context_chunks") and data.context_chunks:
            chunks.extend(data.context_chunks)
    return chunks


def _collect_image_paths(chunks: list[dict]) -> list[str]:
    return list({
        c["file_path"]
        for c in chunks
        if c.get("chunk_type") in ("caption", "image") and c.get("file_path")
    })


def _build_context_from_results(
    tool_results: list[ToolResult],
    classification: ClassificationResult,
    token_budget: int = 6000,
) -> tuple[str, list[dict], list[str]]:
    """
    Build the assembled context string from all tool results.

    For special result types (ComparisonResult, ContradictionReport, Timeline)
    we use their formatted output directly. For plain chunk lists we use the
    standard context assembler.

    Returns (context_text, all_chunks, image_paths).
    """
    extra_sections: list[str] = []
    plain_chunks: list[dict] = []

    for result in tool_results:
        if not result.success:
            continue
        data = result.data

        # ComparisonResult
        if hasattr(data, "comparative_analysis"):
            extra_sections.append(
                f"**Comparative Analysis:**\n{data.comparative_analysis}"
            )
            for label, summary in (data.per_doc_summary or {}).items():
                extra_sections.append(f"**{label} Summary:** {summary}")

        # ContradictionReport
        elif hasattr(data, "contradictions"):
            extra_sections.append(f"**Contradiction Analysis:**\n{data.summary}")
            for c in (data.contradictions or [])[:5]:
                extra_sections.append(
                    f"• [{c.severity.upper()}] {c.doc_a} vs {c.doc_b}:\n"
                    f"  A: {c.claim_a[:200]}\n  B: {c.claim_b[:200]}\n"
                    f"  {c.explanation}"
                )

        # Timeline
        elif hasattr(data, "events") and hasattr(data, "to_markdown"):
            extra_sections.append(data.to_markdown())

        # FinancialsResult
        elif hasattr(data, "structured_facts"):
            from core.tools.financials import format_financial_facts
            facts_text = format_financial_facts(data.structured_facts or [])
            if facts_text:
                extra_sections.append(facts_text)
            plain_chunks.extend(data.context_chunks or [])

        # Plain chunk list
        elif isinstance(data, list):
            plain_chunks.extend(data)

    # Assemble plain chunks
    assembled = assemble_context(plain_chunks, classification.task_type, token_budget)

    # Combine: assembled chunks context + special result sections
    parts: list[str] = []
    if assembled.text:
        parts.append(assembled.text)
    parts.extend(extra_sections)

    final_text = "\n\n".join(parts)
    image_paths = _collect_image_paths(plain_chunks)

    return final_text, plain_chunks + assembled.chunks_used, image_paths


# ── System prompt selection ────────────────────────────────────────────────────

_TASK_SYSTEM_PROMPTS: dict[TaskType, str] = {
    TaskType.LOOKUP: (
        "You are a helpful document analyst. Use the provided context to answer "
        "the question accurately. Cite the source document for each fact."
    ),
    TaskType.SUMMARIZATION: (
        "You are an expert summariser. Provide a comprehensive, well-structured "
        "summary of the document(s) based on the provided context."
    ),
    TaskType.COMPARISON: (
        "You are a comparative document analyst. You have been given sections from "
        "multiple documents, each clearly labeled. Produce a thorough structured "
        "comparison that: (1) addresses the question directly, (2) compares each "
        "document on every relevant dimension, (3) highlights key differences and "
        "changes, (4) notes any inconsistencies, (5) cites the source for every "
        "claim. Be specific — use concrete data and quotes where available."
    ),
    TaskType.TREND_ANALYSIS: (
        "You are a trend analyst. Using the chronologically arranged context, "
        "identify and explain the key trends, patterns, and trajectories relevant "
        "to the question. Quantify trends where possible. Note any inflection "
        "points or acceleration/deceleration in trends."
    ),
    TaskType.TIMELINE: (
        "You are a timeline analyst. Based on the context provided, produce a "
        "clear chronological timeline of events. List events in date order. "
        "Cite the source document for each event. Use a markdown format with "
        "year headers and bullet points."
    ),
    TaskType.CONTRADICTION: (
        "You are a document consistency analyst. Using the contradiction analysis "
        "and context provided, explain any inconsistencies or contradictions found "
        "between the documents. For each contradiction: describe what each document "
        "says, explain why they conflict, and assess the significance."
    ),
    TaskType.FINANCIAL: (
        "You are a financial analyst. Using the structured financial data and "
        "narrative context provided, answer the question precisely. Include specific "
        "numbers, percentages, and time periods. Cite the source document and period "
        "for every figure."
    ),
    TaskType.RISK_ANALYSIS: (
        "You are a risk analyst specializing in regulatory filings. Using the "
        "provided risk factor sections, identify and explain the key risks. "
        "Where multiple years are provided, note how the risk profile has evolved. "
        "Categorize risks (operational, regulatory, financial, competitive, etc.) "
        "and assess relative severity based on the language used."
    ),
}


def get_task_system_prompt(task_type: TaskType, base_prompt: str = "") -> str:
    """Return the task-specific system prompt, optionally prepended with a base prompt."""
    task_prompt = _TASK_SYSTEM_PROMPTS.get(task_type, _TASK_SYSTEM_PROMPTS[TaskType.LOOKUP])
    if base_prompt:
        return f"{base_prompt}\n\n{task_prompt}"
    return task_prompt


# ── Main AgentPlanner ──────────────────────────────────────────────────────────

class AgentPlanner:
    """
    Orchestrates the full agentic query pipeline.

    Usage:
        planner = AgentPlanner(root, config, ollama_url, model)
        result = planner.execute(query)

        # Then use result.assembled_context + get_task_system_prompt()
        # to call the LLM responder.
    """

    def __init__(
        self,
        root: Path,
        config: dict,
        ollama_url: str,
        model: str,
        max_iterations: int = 3,
        token_budget: int = 8000,
    ) -> None:
        self.root = root
        self.config = config
        self.ollama_url = ollama_url
        self.model = model
        self.max_iterations = max_iterations
        self.token_budget = token_budget
        self.executor = ToolExecutor(root, config, ollama_url, model)

    def classify(self, query: str) -> ClassificationResult:
        """Classify a query into a TaskType."""
        from core.storage.db import get_connection, get_all_files
        conn = get_connection(self.root)
        try:
            indexed_docs = get_all_files(conn)
        except Exception:
            indexed_docs = []
        finally:
            conn.close()
        return classify_query(query, indexed_docs)

    def execute(
        self,
        query: str,
        classification: ClassificationResult | None = None,
        files_filter: list[str] | None = None
    ) -> AgentResult:
        """
        Execute the full agentic pipeline for *query*.

        Parameters
        ----------
        query: The user's query (already reformulated to standalone).
        classification: Optional pre-computed classification (skips classifier call).
        files_filter: Optional list of specific files to restrict search to.

        Returns
        -------
        AgentResult containing assembled_context, all_chunks, tool_results, etc.
        """
        start_time = time.monotonic()

        if classification is None:
            classification = self.classify(query)

        # ── Query rewriting ────────────────────────────────────────────────────
        # Rewrite the raw user query into a clean primary search query.
        # This improves embedding quality significantly compared to embedding the
        # full verbose question as-is.
        retrieval_query = query
        try:
            from core.retrieval.query_rewriter import rewrite_query
            rewritten = rewrite_query(query, self.ollama_url, self.model, self.root)
            if rewritten.search_queries:
                # Use the first (cleaned) sub-query for primary retrieval
                retrieval_query = rewritten.search_queries[0]
        except Exception:
            pass  # Fallback to original query silently

        all_tool_results: list[ToolResult] = []
        plan: ExecutionPlan | None = None
        iteration = 0

        for iteration in range(1, self.max_iterations + 1):
            # 1. Plan (using the cleaned retrieval query)
            plan = get_plan(retrieval_query, classification, self.config)

            # 2. Execute
            tool_results = self.executor.run(plan, files_filter=files_filter)
            all_tool_results.extend(tool_results)

            # 3. Reflect
            reflection = _reflect(classification, tool_results)
            if reflection.sufficient:
                break

            # 4. Replan (broaden scope — remove section filters)
            if iteration < self.max_iterations:
                classification = _broaden_classification(classification)
            else:
                # Final iteration — accept what we have
                break

        # 5. Assemble context
        context_text, all_chunks, image_paths = _build_context_from_results(
            all_tool_results, classification, self.token_budget
        )

        return AgentResult(
            assembled_context=context_text,
            all_chunks=all_chunks,
            tool_results=all_tool_results,
            plan=plan or ExecutionPlan(task_type=classification.task_type, steps=[]),
            classification=classification,
            image_paths=image_paths,
            iterations=iteration,
        )


def _broaden_classification(cls: ClassificationResult) -> ClassificationResult:
    """
    Produce a broader classification for replanning.
    Falls back to LOOKUP if original task was specialized.
    """
    from dataclasses import replace
    # For specialized tasks that found no results, fall back to LOOKUP
    if cls.task_type not in (TaskType.LOOKUP, TaskType.SUMMARIZATION):
        return ClassificationResult(
            task_type=TaskType.LOOKUP,
            time_range=cls.time_range,
            entities=cls.entities,
            confidence=0.5,
            raw_intent="Replanning: broadened to LOOKUP after insufficient results",
        )
    return cls
