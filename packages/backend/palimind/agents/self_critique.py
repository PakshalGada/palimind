"""Structured post-task verification (self-critique).

PaliMind already has a lightweight reflection pass (see
``mixture_of_expert.agents._reflect_answer``). This module adds the structured
layer described in Phase 4.6:

* A per-task-type verification **checklist** generated automatically.
* **Output validation** against the task requirements.
* A **confidence score** and a machine-readable **verification report**.
* **Automatic retry** when confidence is below a threshold.
* **Human-in-the-loop** flagging for low-confidence results.

All LLM interaction is best-effort: on failure a heuristic report is produced
so a run is never blocked by the verifier.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from palimind.settings import (
    SELF_CRITIQUE_CONFIDENCE_THRESHOLD,
)

TASK_TYPES: tuple[str, ...] = ("code", "research", "data", "writing", "general")

_TASK_CHECKLISTS: dict[str, list[str]] = {
    "code": [
        "Does the answer address every part of the request?",
        "Is the code syntactically valid and free of obvious bugs?",
        "Are edge cases and error paths handled?",
        "Does it follow the surrounding conventions?",
        "Are imports/dependencies and assumptions stated?",
    ],
    "research": [
        "Is every factual claim supported by a cited source?",
        "Are sources authoritative and, where needed, independent?",
        "Is the distinction between verified and uncertain stated?",
        "Are contradictions between sources acknowledged?",
        "Does the answer directly address the original question?",
    ],
    "data": [
        "Are the calculations correct and reproducible?",
        "Are units, ranges and assumptions stated?",
        "Are missing data points handled explicitly?",
        "Are the conclusions supported by the numbers?",
        "Are tables/figures labelled clearly?",
    ],
    "writing": [
        "Does it answer the request in the requested tone and format?",
        "Is it free of filler, repetition and hedging?",
        "Is the structure clear and the opening strong?",
        "Are factual claims (if any) accurate?",
        "Does it respect length/format constraints?",
    ],
    "general": [
        "Does the answer directly address the question?",
        "Is it complete and free of contradictions?",
        "Are assumptions and uncertainty stated?",
        "Is it concise and well-structured?",
        "Would the user need to ask a follow-up to get the core answer?",
    ],
}

_CODE_RE = re.compile(
    r"\b(code|script|function|debug|refactor|implement|regex|algorithm|class|"
    r"module|compile|api|database|migration|bug|test)\b",
    re.IGNORECASE,
)
_RESEARCH_RE = re.compile(
    r"\b(research|compare|analyse|analyze|investigate|literature|survey|report|"
    r"source|citation|evidence)\b",
    re.IGNORECASE,
)
_DATA_RE = re.compile(
    r"\b(data|csv|dataset|statistics|calculate|compute|chart|table|metric|sum|average)\b",
    re.IGNORECASE,
)
_WRITING_RE = re.compile(
    r"\b(write|draft|essay|email|article|blog|copy|edit|rewrite|summarize|summary)\b",
    re.IGNORECASE,
)


def detect_task_type(task: str, definition: Any | None = None) -> str:
    """Infer the verification checklist family for a task."""
    text = task or ""
    if _CODE_RE.search(text):
        return "code"
    if _RESEARCH_RE.search(text):
        return "research"
    if _DATA_RE.search(text):
        return "data"
    if _WRITING_RE.search(text):
        return "writing"
    # Fall back to the agent's attached skills when present.
    skills = list(getattr(definition, "skills", []) or [])
    if any("code" in s for s in skills):
        return "code"
    if any(s in ("web-research", "fact-check", "deep-analysis") for s in skills):
        return "research"
    if any(s in ("concise-writer",) for s in skills):
        return "writing"
    return "general"


def build_checklist(task_type: str) -> list[str]:
    """Return the verification checklist for a task type."""
    return list(_TASK_CHECKLISTS.get(task_type, _TASK_CHECKLISTS["general"]))


def build_verification_prompt(
    task: str,
    output: str,
    checklist: list[str],
    success_criteria: str = "",
) -> str:
    checks = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(checklist))
    criteria = ""
    if success_criteria and success_criteria.strip():
        criteria = f"\nSuccess criteria supplied by the user:\n{success_criteria.strip()}\n"
    return f"""You are a strict verification agent. A worker produced the output below for a task.

TASK:
{task[:4000]}
{criteria}
OUTPUT TO VERIFY:
{output[:8000]}

Evaluate the output against each checklist item:
{checks}

Respond with ONLY a JSON object:
{{
  "passed": true,
  "confidence": 0.0,
  "checks": {{"<item number>": "pass|fail|partial"}},
  "issues": ["..."],
  "suggestions": ["..."],
  "reasoning": "<one or two sentences>"
}}
Set "passed" to false when any essential requirement is unmet. Confidence is
your 0..1 estimate that the output is correct and complete."""


def parse_verification(text: str) -> dict[str, Any] | None:
    """Parse the verifier's JSON response, tolerating code fences/prose."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    parsed: Any = None
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except (json.JSONDecodeError, TypeError):
                parsed = None
    if not isinstance(parsed, dict):
        return None
    try:
        confidence = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    checks = parsed.get("checks")
    if not isinstance(checks, dict):
        checks = {}
    issues = parsed.get("issues")
    suggestions = parsed.get("suggestions")
    return {
        "passed": bool(parsed.get("passed", confidence >= SELF_CRITIQUE_CONFIDENCE_THRESHOLD)),
        "confidence": max(0.0, min(1.0, confidence)),
        "checks": {str(k): str(v) for k, v in checks.items()},
        "issues": [str(i) for i in issues] if isinstance(issues, list) else [],
        "suggestions": [str(s) for s in suggestions] if isinstance(suggestions, list) else [],
        "reasoning": str(parsed.get("reasoning", ""))[:600],
    }


def heuristic_report(output: str, checklist: list[str]) -> dict[str, Any]:
    """Fallback report when the verifier LLM is unavailable."""
    text = (output or "").strip()
    issues: list[str] = []
    if not text:
        issues.append("The output is empty.")
    if text.startswith("[Agent ") and "error" in text.lower():
        issues.append("The run ended with an error message instead of an answer.")
    if len(text) < 40 and text:
        issues.append("The output is suspiciously short for the task.")
    confidence = 0.5
    if not issues:
        confidence = 0.75
    if not text:
        confidence = 0.0
    return {
        "passed": confidence >= SELF_CRITIQUE_CONFIDENCE_THRESHOLD,
        "confidence": confidence,
        "checks": {},
        "issues": issues,
        "suggestions": [],
        "reasoning": "Heuristic verification (verifier model unavailable).",
        "source": "heuristic",
    }


def verify_output(
    task: str,
    output: str,
    model: str = "",
    ollama_url: str = "",
    *,
    task_type: str | None = None,
    definition: Any | None = None,
    checklist: list[str] | None = None,
    success_criteria: str = "",
    usage_cb: Callable[[dict], None] | None = None,
    read_timeout: float = 120.0,
) -> dict[str, Any]:
    """Verify an output and return a structured report.

    The report always contains ``task_type``, ``checklist``, ``passed``,
    ``confidence``, ``issues``, ``suggestions`` and ``reasoning``.
    """
    resolved_type = task_type or detect_task_type(task, definition)
    resolved_checklist = checklist or build_checklist(resolved_type)
    base: dict[str, Any] = {
        "task_type": resolved_type,
        "checklist": resolved_checklist,
        "passed": True,
        "confidence": 0.5,
        "checks": {},
        "issues": [],
        "suggestions": [],
        "reasoning": "",
        "source": "heuristic",
    }
    if not model or not ollama_url or not (output or "").strip():
        base.update(heuristic_report(output, resolved_checklist))
        base["task_type"] = resolved_type
        base["checklist"] = resolved_checklist
        return base

    prompt = build_verification_prompt(task, output, resolved_checklist, success_criteria)
    try:
        from palimind.llm.mixture_of_expert.llm import llm_chat_safe

        result = llm_chat_safe(
            [{"role": "user", "content": prompt}],
            model,
            ollama_url,
            format="json",
            temperature=0.0,
            num_predict=600,
            read_timeout=read_timeout,
            error_prefix="[verification",
        )
    except Exception as e:  # noqa: BLE001 - verifier is best-effort
        print(f"[verification] model call failed: {e}")
        base.update(heuristic_report(output, resolved_checklist))
        base["task_type"] = resolved_type
        base["checklist"] = resolved_checklist
        return base

    if usage_cb is not None:
        try:
            usage_cb(result.get("usage") or {})
        except Exception:  # noqa: BLE001
            pass

    parsed = parse_verification(result.get("content") or "")
    if parsed is None:
        base.update(heuristic_report(output, resolved_checklist))
        base["task_type"] = resolved_type
        base["checklist"] = resolved_checklist
        return base
    parsed["task_type"] = resolved_type
    parsed["checklist"] = resolved_checklist
    parsed["source"] = "llm"
    return parsed


def needs_retry(report: dict[str, Any], threshold: float | None = None) -> bool:
    """True when verification failed or confidence is below threshold."""
    if not report:
        return False
    limit = SELF_CRITIQUE_CONFIDENCE_THRESHOLD if threshold is None else threshold
    if report.get("passed") is False:
        return True
    try:
        return float(report.get("confidence", 1.0)) < limit
    except (TypeError, ValueError):
        return False


def needs_human_review(report: dict[str, Any], threshold: float | None = None) -> bool:
    """True when a low-confidence result should be escalated to a human."""
    if not report:
        return False
    limit = SELF_CRITIQUE_CONFIDENCE_THRESHOLD if threshold is None else threshold
    try:
        return float(report.get("confidence", 1.0)) < limit
    except (TypeError, ValueError):
        return False


def build_retry_prompt(task: str, output: str, report: dict[str, Any]) -> str:
    """Prompt asking the worker to fix the verifier's findings."""
    issues = "\n".join(f"- {i}" for i in report.get("issues", [])) or "- (no specific issues)"
    suggestions = "\n".join(f"- {s}" for s in report.get("suggestions", []))
    suggestion_block = f"\nSuggestions:\n{suggestions}\n" if suggestions else ""
    return (
        "A verifier reviewed your previous answer and found problems. Produce an "
        "improved FINAL_ANSWER that fixes them. Do not mention the review.\n\n"
        f"TASK:\n{task[:3000]}\n\nPREVIOUS ANSWER:\n{output[:6000]}\n\n"
        f"Issues:\n{issues}\n{suggestion_block}"
    )


def format_report(report: dict[str, Any]) -> str:
    """Human-readable one-block verification summary (for logs/UI)."""
    if not report:
        return ""
    pct = int(round(float(report.get("confidence", 0.0)) * 100))
    status = "passed" if report.get("passed") else "needs attention"
    lines = [f"Verification: {status} ({pct}% confidence)"]
    if report.get("reasoning"):
        lines.append(str(report["reasoning"]))
    for issue in report.get("issues", [])[:5]:
        lines.append(f"- {issue}")
    return "\n".join(lines)


__all__ = [
    "TASK_TYPES",
    "build_checklist",
    "build_retry_prompt",
    "build_verification_prompt",
    "detect_task_type",
    "format_report",
    "heuristic_report",
    "needs_human_review",
    "needs_retry",
    "parse_verification",
    "verify_output",
]
