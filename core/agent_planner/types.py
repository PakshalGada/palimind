"""
Core data types for the Palimind agentic planner.

Defines TaskType, ClassificationResult, ExecutionPlan, ToolCall, AgentResult
and supporting dataclasses used throughout the planner pipeline.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ── Task classification ────────────────────────────────────────────────────────

class TaskType(Enum):
    """
    Semantic classification of a user query.

    Used by the AgentPlanner to select the appropriate retrieval strategy
    and system prompt template.
    """
    LOOKUP          = auto()   # "What is X?" — single-document point lookup
    SUMMARIZATION   = auto()   # "Summarize document Y" — file-targeted
    COMPARISON      = auto()   # "How did X change between 2023 and 2025?" — multi-doc
    TREND_ANALYSIS  = auto()   # "Show revenue trend over 3 years" — temporal
    TIMELINE        = auto()   # "When did X happen?" — chronological event list
    CONTRADICTION   = auto()   # "Does 2023 contradict 2025?" — diff/inconsistency
    FINANCIAL       = auto()   # "What was gross margin in Q3 2024?" — financial data
    RISK_ANALYSIS   = auto()   # "What are Apple's risk factors?" — risk section


@dataclass
class ClassificationResult:
    """Output of the query classifier."""
    task_type: TaskType
    target_docs: list[str] = field(default_factory=list)   # explicit doc mentions
    time_range: tuple[int, int] | None = None               # e.g. (2023, 2025)
    entities: list[str] = field(default_factory=list)       # named entities in query
    confidence: float = 1.0
    raw_intent: str = ""                                    # human-readable reasoning

    def years_in_range(self) -> list[int]:
        """Return a list of years spanning time_range, inclusive."""
        if self.time_range is None:
            return []
        start, end = self.time_range
        return list(range(start, end + 1))


# ── Execution plan types ───────────────────────────────────────────────────────

@dataclass
class ToolCall:
    """
    A single planned tool invocation.

    ``parallel_group``: all ToolCalls with the same group ID run concurrently.
    Group 0 runs first (sequentially), then group 1 (parallel), etc.
    ``depends_on``: list of call_ids whose results must be available before
    this call runs. The executor injects their results as ``prior_results``.
    """
    tool_name: str
    arguments: dict[str, Any]
    parallel_group: int = 0
    depends_on: list[str] = field(default_factory=list)
    call_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def __post_init__(self) -> None:
        # Ensure call_id is always a non-empty string
        if not self.call_id:
            self.call_id = str(uuid.uuid4())[:8]


@dataclass
class ExecutionPlan:
    """Ordered list of tool invocations produced by the AgentPlanner."""
    task_type: TaskType
    steps: list[ToolCall]
    reasoning: str = ""
    estimated_doc_coverage: list[str] = field(default_factory=list)


# ── Tool result ────────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Result of a single tool execution."""
    call_id: str
    tool_name: str
    success: bool
    data: Any = None                # tool-specific return value
    error: str = ""
    elapsed_ms: float = 0.0


# ── Agent result ───────────────────────────────────────────────────────────────

@dataclass
class AgentResult:
    """
    Final output of AgentPlanner.execute().

    ``assembled_context``: the assembled text context ready to send to the LLM.
    ``all_chunks``: flat list of all retrieved RichChunk-like dicts.
    ``tool_results``: raw results from every tool that ran.
    ``plan``: the ExecutionPlan that was followed.
    ``classification``: the original query classification.
    """
    assembled_context: str
    all_chunks: list[dict]
    tool_results: list[ToolResult]
    plan: ExecutionPlan
    classification: ClassificationResult
    image_paths: list[str] = field(default_factory=list)
    iterations: int = 1


# ── Reflection ─────────────────────────────────────────────────────────────────

@dataclass
class ReflectionResult:
    """Output of the ReAct reflection step."""
    sufficient: bool        # True → evidence is adequate; stop loop
    reason: str = ""        # why evidence is or isn't sufficient
    missing_docs: list[str] = field(default_factory=list)  # docs we expected but didn't get
    suggested_replan: str = ""  # hint for replanning (if not sufficient)
