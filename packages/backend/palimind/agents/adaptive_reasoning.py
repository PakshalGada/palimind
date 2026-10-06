"""Adaptive reasoning: allocate reasoning effort to a task's complexity.

Modern agent platforms (Claude, Grok) do not spend the same amount of thinking
on "what is 2+2" and "design a migration plan". This module gives PaliMind the
same behaviour:

* Four effort levels — ``minimal``, ``standard``, ``high``, ``max`` — each with
  a tool-iteration ceiling, a live-context token budget and a token budget for
  the final answer.
* A cheap complexity classifier (one small LLM call, with a deterministic
  heuristic fallback) that scores a task and recommends a level.
* ``auto`` resolution: start low and auto-escalate a level when the agent gets
  stuck (repeated tool loops, tool errors, no answer).
* Token-budget management so simple tasks do not pay for deep reasoning.

The module is deliberately free of I/O at import time and degrades gracefully
when Ollama is unreachable (the heuristic is always available).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from palimind.settings import ADAPTIVE_ESCALATE_ON_STUCK, ADAPTIVE_REASONING

EFFORT_LEVELS: tuple[str, ...] = ("minimal", "standard", "high", "max")
AUTO_EFFORT = "auto"

# Ordered profiles. ``iterations`` is the tool-iteration ceiling, ``context``
# the live-exchange token budget, ``tokens`` the answer token budget and
# ``verify`` whether the post-run verification pass runs.
EFFORT_PROFILES: dict[str, dict[str, Any]] = {
    "minimal": {
        "level": "minimal",
        "label": "Minimal",
        "description": "Direct one-shot answer; tools only if strictly required.",
        "iterations": 3,
        "context": 2000,
        "tokens": 512,
        "verify": False,
        "indicator": "○",
    },
    "standard": {
        "level": "standard",
        "label": "Standard",
        "description": "Focused execution with a handful of tool steps.",
        "iterations": 8,
        "context": 6000,
        "tokens": 1500,
        "verify": False,
        "indicator": "●○",
    },
    "high": {
        "level": "high",
        "label": "High",
        "description": "Multi-step reasoning with verification of the result.",
        "iterations": 14,
        "context": 12000,
        "tokens": 3000,
        "verify": True,
        "indicator": "●●○",
    },
    "max": {
        "level": "max",
        "label": "Max",
        "description": "Deep, exhaustive reasoning and multiple verification passes.",
        "iterations": 24,
        "context": 20000,
        "tokens": 6000,
        "verify": True,
        "indicator": "●●●",
    },
}

_SIMPLE_RE = re.compile(
    r"^(hi|hello|hey|thanks|thank you|ok|okay|great|cool|what is \d+\s*[\+\-\*/]\s*\d+)[\s!.?]*$",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"\b(code|script|function|debug|refactor|implement|regex|algorithm|class|module|"
    r"compile|test|api|database|migration|bug)\b",
    re.IGNORECASE,
)
_RESEARCH_RE = re.compile(
    r"\b(research|compare|analyse|analyze|investigate|literature|survey|report|"
    r"trade-?offs?|pros and cons|evaluate|recommend)\b",
    re.IGNORECASE,
)
_MULTISTEP_RE = re.compile(
    r"\b(then|after that|step by step|first|second|finally|pipeline|workflow|plan|"
    r"design|architect|orchestrate|build .* that .* then)\b",
    re.IGNORECASE,
)
_CURRENT_RE = re.compile(
    r"\b(latest|current|today|news|price|stock|weather|2025|2026)\b", re.IGNORECASE
)


def effort_profile(level: str) -> dict[str, Any]:
    """Return the profile for *level* (unknown values fall back to standard)."""
    return dict(EFFORT_PROFILES.get(str(level).lower(), EFFORT_PROFILES["standard"]))


def list_effort_levels() -> list[dict[str, Any]]:
    """Serialize every effort level for the agent-config UI."""
    return [effort_profile(level) for level in EFFORT_LEVELS]


def next_level(level: str) -> str:
    """Return the next higher effort level (``max`` is a fixed point)."""
    try:
        idx = EFFORT_LEVELS.index(str(level).lower())
    except ValueError:
        return "standard"
    return EFFORT_LEVELS[min(idx + 1, len(EFFORT_LEVELS) - 1)]


def previous_level(level: str) -> str:
    try:
        idx = EFFORT_LEVELS.index(str(level).lower())
    except ValueError:
        return "standard"
    return EFFORT_LEVELS[max(idx - 1, 0)]


def token_budget(level: str) -> int:
    """Approximate answer-token budget for an effort level."""
    return int(effort_profile(level).get("tokens", 1500))


def heuristic_complexity(task: str) -> dict[str, Any]:
    """Deterministic complexity estimate used as prior and fallback.

    Returns ``{"score", "level", "signals", "source"}`` where ``score`` is a
    0..1 estimate of task difficulty.
    """
    text = (task or "").strip()
    signals: list[str] = []
    if not text:
        return {"score": 0.05, "level": "minimal", "signals": ["empty"], "source": "heuristic"}

    if _SIMPLE_RE.match(text):
        return {
            "score": 0.05,
            "level": "minimal",
            "signals": ["trivial"],
            "source": "heuristic",
        }

    score = 0.15
    length = len(text)
    if length > 120:
        score += 0.1
    if length > 400:
        score += 0.1
    if length > 1200:
        score += 0.1
    if length > 200:
        signals.append("long-input")

    if _CODE_RE.search(text):
        score += 0.25
        signals.append("code")
    if _RESEARCH_RE.search(text):
        score += 0.25
        signals.append("research")
    if _MULTISTEP_RE.search(text):
        score += 0.2
        signals.append("multi-step")
    if _CURRENT_RE.search(text):
        score += 0.1
        signals.append("live-info")
    if text.count("?") >= 3:
        score += 0.1
        signals.append("multi-question")
    if "\n" in text and len(text.splitlines()) > 6:
        score += 0.1
        signals.append("structured-brief")

    score = max(0.0, min(1.0, score))
    if score < 0.2:
        level = "minimal"
    elif score < 0.45:
        level = "standard"
    elif score < 0.72:
        level = "high"
    else:
        level = "max"
    return {"score": round(score, 3), "level": level, "signals": signals, "source": "heuristic"}


def _score_to_level(score: float) -> str:
    if score < 0.2:
        return "minimal"
    if score < 0.45:
        return "standard"
    if score < 0.72:
        return "high"
    return "max"


def classify_complexity(
    task: str,
    model: str = "",
    ollama_url: str = "",
    usage_cb: Callable[[dict], None] | None = None,
    read_timeout: float = 30.0,
) -> dict[str, Any]:
    """Classify a task's complexity.

    Uses one cheap LLM call when a model/URL is supplied; falls back to the
    deterministic heuristic on any failure. The result always carries a
    ``level`` in :data:`EFFORT_LEVELS`.
    """
    prior = heuristic_complexity(task)
    if not model or not ollama_url:
        return prior
    prompt = (
        "You are a routing classifier for an AI agent platform. Estimate how much "
        "reasoning effort a task needs. Consider required tool use, number of "
        "steps, ambiguity and whether live data is needed.\n\n"
        'Respond with ONLY a JSON object: {"complexity": <0.0-1.0>, '
        '"level": "minimal|standard|high|max", "reasoning": "<one short sentence>"}\n\n'
        f"Task: {task[:2000]}"
    )
    try:
        from palimind.llm.mixture_of_expert.llm import llm_chat_safe

        result = llm_chat_safe(
            [{"role": "user", "content": prompt}],
            model,
            ollama_url,
            format="json",
            temperature=0.0,
            num_predict=120,
            read_timeout=read_timeout,
            error_prefix="[effort classifier",
        )
    except Exception as e:  # noqa: BLE001 - classifier is best-effort
        print(f"[adaptive] complexity classifier failed: {e}")
        return prior

    if usage_cb is not None:
        try:
            usage_cb(result.get("usage") or {})
        except Exception:  # noqa: BLE001
            pass

    try:
        parsed = json.loads(result.get("content") or "{}")
    except (json.JSONDecodeError, TypeError):
        return prior
    if not isinstance(parsed, dict):
        return prior

    try:
        score = float(parsed.get("complexity", prior["score"]))
    except (TypeError, ValueError):
        score = float(prior["score"])
    score = max(0.0, min(1.0, score))
    level = str(parsed.get("level", "")).lower()
    if level not in EFFORT_LEVELS:
        level = _score_to_level(score)
    return {
        "score": round(score, 3),
        "level": level,
        "signals": prior.get("signals", []),
        "source": "llm",
        "reasoning": str(parsed.get("reasoning", ""))[:300],
    }


def resolve_effort(
    task: str,
    requested: str = AUTO_EFFORT,
    model: str = "",
    ollama_url: str = "",
    usage_cb: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """Resolve the effective effort for a run.

    * ``requested`` in :data:`EFFORT_LEVELS` → that level, no classifier call.
    * ``requested`` empty/``auto``/``adaptive`` → classify the task.
    * adaptive reasoning disabled globally → ``standard``.

    Returns ``{"level", "profile", "score", "source", "reasoning", "requested"}``.
    """
    req = (requested or AUTO_EFFORT).strip().lower()
    if not ADAPTIVE_REASONING:
        profile = effort_profile("standard")
        return {
            "level": "standard",
            "profile": profile,
            "score": None,
            "source": "disabled",
            "reasoning": "Adaptive reasoning is disabled.",
            "requested": requested,
        }
    if req in EFFORT_LEVELS:
        profile = effort_profile(req)
        return {
            "level": req,
            "profile": profile,
            "score": None,
            "source": "manual",
            "reasoning": f"Agent is pinned to '{req}' effort.",
            "requested": requested,
        }
    classification = classify_complexity(task, model, ollama_url, usage_cb)
    level = classification["level"]
    profile = effort_profile(level)
    return {
        "level": level,
        "profile": profile,
        "score": classification.get("score"),
        "source": classification.get("source", "heuristic"),
        "reasoning": classification.get("reasoning", ""),
        "signals": classification.get("signals", []),
        "requested": requested,
    }


def should_escalate(
    *,
    repeated_tool: bool = False,
    tool_error: bool = False,
    answered: bool = True,
    iteration: int = 0,
    max_iterations: int = 0,
) -> bool:
    """Return True when a stuck run should be retried at a higher effort."""
    if not (ADAPTIVE_REASONING and ADAPTIVE_ESCALATE_ON_STUCK):
        return False
    if repeated_tool or tool_error:
        return True
    if not answered:
        return True
    # Used more than 80% of the budget without finishing cleanly.
    return bool(max_iterations and iteration >= max_iterations * 0.8)


def escalate_effort(level: str, *, reason: str = "") -> dict[str, Any]:
    """Return the escalated level/profile for a run that got stuck."""
    nxt = next_level(level)
    return {
        "level": nxt,
        "profile": effort_profile(nxt),
        "escalated_from": level,
        "escalated": nxt != level,
        "reason": reason,
    }


def apply_effort(
    level: str,
    *,
    max_iterations: int = 0,
    context_budget: int = 0,
) -> dict[str, int]:
    """Combine an effort profile with an agent's configured ceilings.

    The effort level is the target; the agent's own values act as a hard
    ceiling when they are smaller, so a user cannot accidentally let a
    "minimal" agent loop for 24 steps.
    """
    profile = effort_profile(level)
    iterations = int(profile.get("iterations", 8))
    context = int(profile.get("context", 6000))
    if max_iterations and max_iterations > 0:
        iterations = min(iterations, max_iterations)
    if context_budget and context_budget > 0:
        context = min(context, context_budget)
    return {
        "iterations": max(1, iterations),
        "context_budget": max(1000, context),
        "tokens": int(profile.get("tokens", 1500)),
    }


def effort_indicator(level: str) -> str:
    """A compact visual indicator (e.g. ``●●○``) for the UI."""
    return str(effort_profile(level).get("indicator", "●○"))
