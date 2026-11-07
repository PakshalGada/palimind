"""Follow-up suggestions after a settled agent answer.

Hosted agent products end an answer with a few relevant next steps. This module
keeps that affordance local and cheap: one small light-model call with a
deterministic fallback, so a slow or unavailable model can never block the
answer from being delivered.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

_MAX_SUGGESTIONS = 4
_MAX_LENGTH = 140


def _clean(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip(" -•\t")
    if not text:
        return ""
    return text[:_MAX_LENGTH]


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:_MAX_SUGGESTIONS]


def parse_suggestions(raw: str) -> list[str]:
    """Parse the model's JSON (object or array) into clean strings."""
    if not raw:
        return []
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    try:
        parsed = json.loads(cleaned)
    except (TypeError, ValueError):
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except (TypeError, ValueError):
            return []
    if isinstance(parsed, dict):
        parsed = parsed.get("suggestions") or parsed.get("follow_ups") or []
    if not isinstance(parsed, list):
        return []
    items = []
    for entry in parsed:
        if isinstance(entry, str):
            items.append(_clean(entry))
        elif isinstance(entry, dict):
            items.append(_clean(entry.get("text") or entry.get("label") or entry.get("question")))
    return _dedupe(items)


def heuristic_suggestions(
    task: str,
    answer: str,
    tool_names: Iterable[str] = (),
) -> list[str]:
    """Deterministic fallback that still feels relevant to the work done."""
    tools = {str(name) for name in tool_names}
    if tools & {
        "web_search",
        "fetch_url",
        "browse_url",
        "x_search",
        "arxiv_search",
        "research_search",
        "document_search",
    }:
        candidates = [
            "What are the three most important takeaways?",
            "Compare the strongest sources you found.",
            "What is still uncertain or unverified?",
            "Turn this into a one-page brief.",
        ]
    elif tools & {"write_file", "apply_patch", "search_replace", "run_shell", "run_python"}:
        candidates = [
            "Show me exactly what changed.",
            "Add a test or check for this.",
            "What could break, and how do we roll it back?",
            "Summarise the implementation in five bullets.",
        ]
    elif tools & {"csv_query", "sqlite_query", "duckdb_query", "xlsx_read", "chart_generate"}:
        candidates = [
            "Turn this into a chart.",
            "Show the rows behind the main number.",
            "What are the outliers or anomalies?",
            "Write a short executive summary.",
        ]
    else:
        candidates = [
            "Go deeper on this.",
            "Summarise this in five bullets.",
            "What should I do next?",
            "What are the strongest counterarguments?",
        ]
    if len(answer.strip()) > 2000:
        candidates.append("Give me a shorter version.")
    return _dedupe(candidates)


def build_suggestions_prompt(task: str, answer: str, tool_names: Iterable[str]) -> str:
    tools = ", ".join(sorted({str(name) for name in tool_names})) or "none"
    return f"""You are finishing an assistant turn. Suggest the three most useful
next actions or questions the user is likely to ask after this answer.

Rules:
- Short, specific, and grounded in the answer (not generic greetings).
- No numbering, no markdown, no quotes around each item.
- Tools already used: {tools}

USER TASK:
{task[:1500]}

ASSISTANT ANSWER:
{answer[:3500]}

Return ONLY a JSON object: {{"suggestions": ["...", "...", "..."]}}"""


def generate_suggestions(
    task: str,
    answer: str,
    model: str,
    ollama_url: str,
    *,
    tool_names: Iterable[str] = (),
    usage_cb: Callable[[dict], None] | None = None,
) -> list[str]:
    """Return 3–4 follow-ups; never raises and always has a fallback."""
    fallback = heuristic_suggestions(task, answer, tool_names)
    if not model or not ollama_url or not (answer or "").strip():
        return fallback
    try:
        from palimind.llm.mixture_of_expert.llm import llm_chat_safe

        result = llm_chat_safe(
            [{"role": "user", "content": build_suggestions_prompt(task, answer, tool_names)}],
            model,
            ollama_url,
            format="json",
            temperature=0.4,
            num_predict=200,
            # Keep the answer snappy: a slow local model falls back to the
            # deterministic suggestions instead of delaying the turn.
            read_timeout=5.0,
            error_prefix="[suggestions",
        )
        if usage_cb is not None and result.get("usage"):
            usage_cb(result["usage"])
        suggestions = parse_suggestions(str(result.get("content") or ""))
        if suggestions:
            return suggestions
    except Exception:  # noqa: BLE001 - suggestions are best-effort
        pass
    return fallback
