"""
Retrieval Diagnostics System for Palimind.

Computes and exposes rich diagnostics alongside every answer:
- Documents searched and evidence coverage
- Chunks retrieved vs chunks used
- Per-chunk confidence scores
- Missing evidence warnings
- Plan execution trace

DiagnosticsReport is JSON-serializable and emitted as an SSE event
after the 'done' event in /api/chat.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from core.agent_planner.types import AgentResult, ExecutionPlan, TaskType


class EvidenceQuality(str, Enum):
    HIGH    = "high"     # rerank_score > 2.0
    MEDIUM  = "medium"   # -1.0 to 2.0
    LOW     = "low"      # -5.0 to -1.0
    MISSING = "missing"  # no relevant chunks


def _score_to_quality(score: float | None) -> EvidenceQuality:
    if score is None:
        return EvidenceQuality.MEDIUM
    if score > 2.0:
        return EvidenceQuality.HIGH
    if score > -1.0:
        return EvidenceQuality.MEDIUM
    if score > -5.0:
        return EvidenceQuality.LOW
    return EvidenceQuality.MISSING


def _normalize_confidence(scores: list[float]) -> float:
    """Map mean rerank scores (range ~-10 to +10) to 0.0–1.0."""
    if not scores:
        return 0.0
    mean = statistics.mean(scores)
    # Sigmoid-like normalization: score of 5 → ~0.9, score of 0 → ~0.5, score of -5 → ~0.1
    import math
    return round(1.0 / (1.0 + math.exp(-mean / 3.0)), 3)


@dataclass
class ChunkDiagnostic:
    chunk_db_id: int
    file_path: str
    section_title: str
    doc_year: int | None
    rerank_score: float | None
    evidence_quality: str      # EvidenceQuality value
    used_in_context: bool


@dataclass
class DocumentCoverage:
    file_path: str
    doc_year: int | None
    chunks_retrieved: int
    chunks_used: int
    avg_rerank_score: float | None
    top_section: str


@dataclass
class DiagnosticsReport:
    query: str
    task_type: str
    plan_steps: list[str]
    plan_iterations: int

    # Retrieval stats
    docs_searched: list[str]
    total_chunks_retrieved: int
    total_chunks_used: int
    doc_coverage: list[dict]      # List of DocumentCoverage as dicts
    chunk_diagnostics: list[dict] # List of ChunkDiagnostic as dicts (top 20)

    # Quality
    overall_confidence: float
    evidence_quality: str

    # Warnings
    missing_evidence_warnings: list[str]
    low_confidence_warnings: list[str]

    # Context stats
    context_token_count: int
    context_truncated: bool
    dedup_chunks_removed: int

    # Timing
    elapsed_ms: float

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "task_type": self.task_type,
            "plan_steps": self.plan_steps,
            "plan_iterations": self.plan_iterations,
            "docs_searched": self.docs_searched,
            "total_chunks_retrieved": self.total_chunks_retrieved,
            "total_chunks_used": self.total_chunks_used,
            "doc_coverage": self.doc_coverage,
            "chunk_diagnostics": self.chunk_diagnostics[:20],  # Cap for SSE size
            "overall_confidence": self.overall_confidence,
            "evidence_quality": self.evidence_quality,
            "missing_evidence_warnings": self.missing_evidence_warnings,
            "low_confidence_warnings": self.low_confidence_warnings,
            "context_token_count": self.context_token_count,
            "context_truncated": self.context_truncated,
            "dedup_chunks_removed": self.dedup_chunks_removed,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


def compute_diagnostics(
    query: str,
    agent_result: AgentResult,
    context_token_count: int = 0,
    context_truncated: bool = False,
    dedup_removed: int = 0,
    elapsed_ms: float = 0.0,
) -> DiagnosticsReport:
    """
    Compute a DiagnosticsReport from an AgentResult.

    Parameters
    ----------
    query: Original user query.
    agent_result: The AgentResult from AgentPlanner.execute().
    context_token_count: Estimated tokens in the assembled context.
    context_truncated: Whether the context was truncated due to token budget.
    dedup_removed: Number of duplicate chunks removed during assembly.
    elapsed_ms: Total elapsed time in milliseconds for the full pipeline.
    """
    classification = agent_result.classification
    plan = agent_result.plan
    all_chunks = agent_result.all_chunks

    # Plan steps summary
    plan_steps = [step.tool_name for step in (plan.steps if plan else [])]

    # Collect all retrieved chunks (including ones not used)
    all_retrieved = all_chunks  # already flattened by planner

    # Used chunks are those in assembled context — approximate by non-empty all_chunks
    # (in practice assembled_context.chunks_used would be better — but we work with what we have)
    used_chunks = [c for c in all_retrieved if c.get("content")]

    # Docs searched
    docs_searched = sorted({c.get("file_path", "") for c in all_retrieved if c.get("file_path")})

    # Per-document coverage
    doc_groups: dict[str, list[dict]] = {}
    for chunk in all_retrieved:
        fp = chunk.get("file_path", "unknown")
        doc_groups.setdefault(fp, []).append(chunk)

    doc_coverage_list: list[dict] = []
    for fp, chunks in sorted(doc_groups.items()):
        scores = [c.get("rerank_score") for c in chunks if c.get("rerank_score") is not None]
        avg_score = round(statistics.mean(scores), 3) if scores else None
        sections = [c.get("section_title", "") for c in chunks if c.get("section_title")]
        top_section = sections[0] if sections else ""
        doc_year = chunks[0].get("doc_year") if chunks else None

        doc_coverage_list.append({
            "file_path": fp,
            "doc_year": doc_year,
            "chunks_retrieved": len(chunks),
            "chunks_used": len(chunks),  # simplified
            "avg_rerank_score": avg_score,
            "top_section": top_section,
        })

    # Chunk diagnostics (top 20 by rerank score)
    sorted_chunks = sorted(
        all_retrieved,
        key=lambda c: c.get("rerank_score", 0.0) or 0.0,
        reverse=True,
    )
    chunk_diag_list = [
        {
            "chunk_db_id": c.get("chunk_db_id"),
            "file_path": c.get("file_path", ""),
            "section_title": c.get("section_title", ""),
            "doc_year": c.get("doc_year"),
            "rerank_score": c.get("rerank_score"),
            "evidence_quality": _score_to_quality(c.get("rerank_score")).value,
            "used_in_context": True,
        }
        for c in sorted_chunks[:20]
    ]

    # Confidence calculation
    scores = [c.get("rerank_score") for c in all_retrieved if c.get("rerank_score") is not None]
    confidence = _normalize_confidence([s for s in scores if s is not None])
    evidence_quality = _score_to_quality(statistics.mean(scores) if scores else None)

    # Warnings
    missing_warnings: list[str] = []
    low_conf_warnings: list[str] = []

    # Check for expected years missing
    if classification.time_range:
        expected_years = set(range(classification.time_range[0], classification.time_range[1] + 1))
        covered_years = {c.get("doc_year") for c in all_retrieved if c.get("doc_year")}
        for year in expected_years:
            if year not in covered_years:
                missing_warnings.append(f"⚠ No evidence retrieved for year {year}")

    if not all_retrieved:
        missing_warnings.append("⚠ No chunks were retrieved from the knowledge base")

    if confidence < 0.4 and all_retrieved:
        low_conf_warnings.append(
            f"⚠ Low average confidence ({confidence:.0%}) — results may be weakly relevant"
        )

    for result in agent_result.tool_results:
        if not result.success:
            missing_warnings.append(f"⚠ Tool '{result.tool_name}' failed: {result.error}")

    return DiagnosticsReport(
        query=query,
        task_type=classification.task_type.name,
        plan_steps=plan_steps,
        plan_iterations=agent_result.iterations,
        docs_searched=docs_searched,
        total_chunks_retrieved=len(all_retrieved),
        total_chunks_used=len(used_chunks),
        doc_coverage=doc_coverage_list,
        chunk_diagnostics=chunk_diag_list,
        overall_confidence=confidence,
        evidence_quality=evidence_quality.value,
        missing_evidence_warnings=missing_warnings,
        low_confidence_warnings=low_conf_warnings,
        context_token_count=context_token_count,
        context_truncated=context_truncated,
        dedup_chunks_removed=dedup_removed,
        elapsed_ms=elapsed_ms,
    )
