"""
Tool executor for the Palimind agentic planner.

Dispatches ToolCall objects to their registered handler functions,
respecting parallel_group ordering and depends_on dependencies.

Execution model:
  * Calls are grouped by their parallel_group integer.
  * Group 0 runs first (serially within the group or all in parallel —
    group 0 items are dispatched concurrently by default).
  * Groups are executed in ascending order; a higher group only starts
    when all lower groups have completed.
  * depends_on is checked at dispatch time: the results of named call_ids
    are injected into the arguments of dependent calls under key "prior_results".
"""
from __future__ import annotations

import concurrent.futures
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.agent_planner.types import ExecutionPlan, ToolCall, ToolResult


class ToolExecutor:
    """
    Executes an ExecutionPlan by dispatching tool calls to registered handlers.

    Usage:
        executor = ToolExecutor(root, config, ollama_url, model)
        results = executor.run(plan)
    """

    def __init__(
        self,
        root: Path,
        config: dict,
        ollama_url: str,
        model: str,
        max_workers: int = 4,
    ) -> None:
        self.root = root
        self.config = config
        self.ollama_url = ollama_url
        self.model = model
        self.max_workers = max_workers
        self._handlers = self._build_handlers()

    def _build_handlers(self) -> dict[str, callable]:
        """Register all tool handler functions."""
        return {
            "retrieve_documents":    self._handle_retrieve_documents,
            "retrieve_by_metadata":  self._handle_retrieve_by_metadata,
            "retrieve_risk_factors": self._handle_retrieve_risk_factors,
            "retrieve_financials":   self._handle_retrieve_financials,
            "compare_document_sets": self._handle_compare,
            "detect_contradictions": self._handle_contradictions,
            "build_timeline":        self._handle_timeline,
            "summarize_document":    self._handle_summarize,
        }

    # ── Tool handlers ──────────────────────────────────────────────────────────

    def _handle_retrieve_documents(self, args: dict, **_) -> list[dict]:
        from core.retrieval.searcher import retrieve_documents
        return retrieve_documents(
            args["query"],
            self.root,
            limit=args.get("limit", 5),
            files_filter=args.get("files_filter"),
            section_filter=args.get("section_filter"),
        )

    def _handle_retrieve_by_metadata(self, args: dict, **_) -> list[dict]:
        from core.retrieval.searcher import retrieve_by_metadata
        return retrieve_by_metadata(
            args["query"],
            self.root,
            limit=args.get("limit", 4),
            doc_year=args.get("doc_year"),
            doc_type=args.get("doc_type"),
            entity_name=args.get("entity_name"),
            section_title=args.get("section_title"),
            files_filter=args.get("files_filter"),
        )

    def _handle_retrieve_risk_factors(self, args: dict, **_) -> list[dict]:
        from core.retrieval.searcher import retrieve_risk_factors
        return retrieve_risk_factors(
            args["query"],
            self.root,
            limit=args.get("limit", 6),
            doc_year=args.get("doc_year"),
            entity_name=args.get("entity_name"),
        )

    def _handle_retrieve_financials(self, args: dict, **_) -> "FinancialsResult":
        from core.tools.financials import retrieve_financials
        time_range = args.get("time_range")
        if time_range and isinstance(time_range, list):
            time_range = tuple(time_range)
        return retrieve_financials(
            args["query"],
            self.root,
            time_range=time_range,
            metric_names=args.get("metric_names"),
            limit=args.get("limit", 5),
        )

    def _handle_compare(self, args: dict, prior_results: dict[str, Any] = {}, **_) -> "ComparisonResult":
        from core.tools.comparison import compare_document_sets

        # Build doc_sets from prior retrieve_by_metadata results
        doc_sets: dict[str, list[dict]] = {}
        for call_id, result in prior_results.items():
            if isinstance(result, list):
                # Label by year if available, else by call_id
                year = result[0].get("doc_year") if result else None
                label = str(year) if year else call_id
                doc_sets[label] = result

        if not doc_sets:
            # Fallback: retrieve broadly
            from core.retrieval.searcher import retrieve_documents
            chunks = retrieve_documents(args["query"], self.root, limit=8)
            doc_sets = {"all": chunks}

        return compare_document_sets(
            args["query"],
            doc_sets,
            self.ollama_url,
            self.model,
        )

    def _handle_contradictions(self, args: dict, prior_results: dict[str, Any] = {}, **_) -> "ContradictionReport":
        from core.tools.contradiction import detect_contradictions

        doc_sets: dict[str, list[dict]] = {}
        for call_id, result in prior_results.items():
            if isinstance(result, list):
                year = result[0].get("doc_year") if result else None
                label = str(year) if year else call_id
                doc_sets[label] = result

        if not doc_sets:
            from core.retrieval.searcher import retrieve_documents
            chunks = retrieve_documents(args["query"], self.root, limit=10)
            doc_sets = {"all": chunks}

        return detect_contradictions(
            args["query"],
            doc_sets,
            self.ollama_url,
            self.model,
        )

    def _handle_timeline(self, args: dict, **_) -> "Timeline":
        from core.tools.timeline import build_timeline
        time_range = args.get("time_range")
        if time_range and isinstance(time_range, list):
            time_range = tuple(time_range)
        return build_timeline(
            args["query"],
            self.root,
            time_range=time_range,
            event_types=args.get("event_types"),
            semantic_limit=args.get("semantic_limit", 12),
        )

    def _handle_summarize(self, args: dict, **_) -> str:
        from core.tools.comparison import summarize_document
        return summarize_document(
            args["file_path"],
            self.root,
            self.ollama_url,
            self.model,
            focus_query=args.get("focus_query"),
        )

    # ── Execution engine ───────────────────────────────────────────────────────

    def _dispatch(
        self,
        tool_call: ToolCall,
        completed_results: dict[str, Any],
    ) -> ToolResult:
        """Dispatch a single tool call and return its ToolResult."""
        handler = self._handlers.get(tool_call.tool_name)
        if handler is None:
            return ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                success=False,
                error=f"Unknown tool: {tool_call.tool_name}",
            )

        # Build prior_results for this call from depends_on
        prior = {dep_id: completed_results[dep_id] for dep_id in tool_call.depends_on
                 if dep_id in completed_results}

        start = time.monotonic()
        try:
            data = handler(tool_call.arguments, prior_results=prior)
            return ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                success=True,
                data=data,
                elapsed_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                success=False,
                error=str(exc),
                elapsed_ms=(time.monotonic() - start) * 1000,
            )

    def run(self, plan: ExecutionPlan, files_filter: list[str] | None = None) -> list[ToolResult]:
        """
        Execute the plan's steps in parallel-group order.

        Returns a list of ToolResult objects in completion order.
        """
        if files_filter:
            for step in plan.steps:
                if "files_filter" not in step.arguments:
                    step.arguments["files_filter"] = files_filter

        # Group steps by parallel_group
        groups: dict[int, list[ToolCall]] = defaultdict(list)
        for step in plan.steps:
            groups[step.parallel_group].append(step)

        completed_results: dict[str, Any] = {}
        all_results: list[ToolResult] = []

        for group_id in sorted(groups.keys()):
            calls = groups[group_id]

            if len(calls) == 1:
                # Single call — dispatch directly (no thread overhead)
                result = self._dispatch(calls[0], completed_results)
                all_results.append(result)
                if result.success:
                    completed_results[result.call_id] = result.data
            else:
                # Multiple calls in same group — run in parallel
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(len(calls), self.max_workers)
                ) as ex:
                    futures = {
                        ex.submit(self._dispatch, call, completed_results): call
                        for call in calls
                    }
                    for fut in concurrent.futures.as_completed(futures):
                        result = fut.result()
                        all_results.append(result)
                        if result.success:
                            completed_results[result.call_id] = result.data

        return all_results
