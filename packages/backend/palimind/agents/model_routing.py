"""Capability-aware model routing with an optional hosted/frontier fallback.

The router answers one question: *which installed model should run this task?*
It considers the task's needs (tools, vision, code, reasoning depth), the
available local models and — when explicitly configured — hosted/frontier
models exposed through the OpenCode proxy.

The policy is deliberately conservative:

* an explicit per-agent model is kept unless it cannot satisfy a hard need;
* hard needs (tools/vision/code) are matched from ``model_capabilities``;
* hard/complex tasks may move to a reasoning-capable local model first;
* a hosted/frontier model is used only when ``PALIMIND_FRONTIER_MODELS`` (or
  an explicit route) makes one available and the task is at/above
  ``PALIMIND_FRONTIER_MIN_COMPLEXITY``;
* with routing disabled, the caller's model is returned unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from palimind.model_capabilities import get_capabilities, infer_from_name
from palimind.settings import (
    AGENT_FRONTIER_MIN_COMPLEXITY,
    AGENT_FRONTIER_MODELS,
    AGENT_MODEL_ROUTING,
)

_LEVEL_ORDER = {"minimal": 0, "standard": 1, "high": 2, "max": 3}
_CODE_HINTS = re.compile(
    r"\b(code|script|python|typescript|rust|java|debug|refactor|test|api|sql|"
    r"patch|repo|function|class|module)\b",
    re.IGNORECASE,
)
_RESEARCH_HINTS = re.compile(
    r"\b(research|compare|investigate|survey|literature|cite|sources|report|"
    r"analyse|analyze|evaluate)\b",
    re.IGNORECASE,
)
_PARAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)


@dataclass
class TaskNeeds:
    tools: bool = False
    vision: bool = False
    code: bool = False
    reasoning: bool = False
    complexity: str = "standard"
    context_tokens: int = 0

    @property
    def capabilities(self) -> set[str]:
        needed: set[str] = set()
        if self.tools:
            needed.add("tools")
        if self.vision:
            needed.add("vision")
        if self.code:
            needed.add("code")
        if self.reasoning:
            needed.add("reasoning")
        return needed


@dataclass
class ModelRoute:
    model: str
    provider: str  # local | hosted
    reason: str
    unchanged: bool = True
    required: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "reason": self.reason,
            "unchanged": self.unchanged,
            "required": list(self.required),
            "alternatives": list(self.alternatives),
        }


def infer_needs(
    task: str,
    *,
    tools: Iterable[str] = (),
    attachments: Iterable[str] = (),
    complexity: str = "standard",
) -> TaskNeeds:
    text = str(task or "")
    tool_list = [str(tool) for tool in tools if tool]
    attachment_list = [str(item).lower() for item in attachments if item]
    has_vision_attachment = any(
        item.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"))
        or item.startswith("image/")
        for item in attachment_list
    )
    level = str(complexity or "standard").lower()
    context_tokens = 0
    context_match = re.search(r"(\d{1,3})\s*(?:k|000)\s*(?:tokens|context)", text, re.I)
    if context_match:
        context_tokens = int(context_match.group(1)) * 1000
    return TaskNeeds(
        tools=bool(tool_list),
        vision=has_vision_attachment,
        code=bool(_CODE_HINTS.search(text)),
        reasoning=level in ("high", "max") or bool(_RESEARCH_HINTS.search(text)),
        complexity=level if level in _LEVEL_ORDER else "standard",
        context_tokens=context_tokens,
    )


def _model_size_b(model_id: str) -> float:
    match = _PARAM_RE.search(str(model_id or ""))
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _provider(model_id: str, hosted: set[str]) -> str:
    return "hosted" if model_id in hosted else "local"


def _eligible(model_id: str, needs: TaskNeeds, ollama_url: str) -> bool:
    if not model_id:
        return False
    caps = get_capabilities(model_id, ollama_url)
    if needs.capabilities and not needs.capabilities.issubset(set(caps.capabilities)):
        return False
    if needs.context_tokens and caps.context_window < needs.context_tokens:
        return False
    return True


def route_model(
    task: str,
    requested: str,
    *,
    candidates: Iterable[str] = (),
    ollama_url: str = "",
    tools: Iterable[str] = (),
    attachments: Iterable[str] = (),
    complexity: str = "standard",
    hosted_models: Iterable[str] | None = None,
    routing_mode: str = AGENT_MODEL_ROUTING,
    frontier_models: Iterable[str] | None = None,
) -> ModelRoute:
    """Pick the best model for *task*; return the requested model on any doubt.

    ``routing_mode`` is ``off``, ``local``, ``auto`` or ``frontier``.
    """
    mode = str(routing_mode or "auto").strip().lower()
    requested = str(requested or "").strip()
    if mode in ("off", "0", "false", "disabled"):
        return ModelRoute(
            model=requested,
            provider="local",
            reason="routing disabled",
            unchanged=True,
        )

    hosted = {str(m) for m in (hosted_models or ()) if m}
    frontier = [
        str(m)
        for m in (frontier_models if frontier_models is not None else AGENT_FRONTIER_MODELS)
        if m
    ]
    local_candidates: list[str] = []
    for model_id in [requested, *candidates]:
        model_id = str(model_id or "").strip()
        if model_id and model_id not in local_candidates:
            local_candidates.append(model_id)
    # Hosted/frontier candidates are considered after local ones unless the
    # task is hard enough to jump straight to a frontier model.
    all_candidates = [
        *local_candidates,
        *[m for m in [*frontier, *sorted(hosted)] if m not in local_candidates],
    ]

    needs = infer_needs(task, tools=tools, attachments=attachments, complexity=complexity)
    if mode == "local":
        hosted.clear()
        frontier = []
        all_candidates = local_candidates

    # Hard/complex task: prefer a reasoning/frontier model when the requested
    # local model is small. A capable local reasoning model still wins before a
    # hosted one.
    min_level = _LEVEL_ORDER.get(str(AGENT_FRONTIER_MIN_COMPLEXITY).lower(), 2)
    task_level = _LEVEL_ORDER.get(needs.complexity, 1)
    small_local = requested and _model_size_b(requested) and _model_size_b(requested) < 8
    if mode in ("auto", "frontier") and (task_level >= min_level or mode == "frontier"):
        explicit_frontier = [model_id for model_id in frontier if model_id]
        reasoning_local = next(
            (
                model_id
                for model_id in local_candidates
                if "reasoning" in get_capabilities(model_id, ollama_url).capabilities
                and _eligible(model_id, needs, ollama_url)
            ),
            "",
        )
        # An explicitly configured frontier list wins for a small local model;
        # otherwise prefer a reasoning-capable local model (local-first).
        if explicit_frontier and (small_local or mode == "frontier"):
            chosen = explicit_frontier[0]
            return ModelRoute(
                model=chosen,
                provider="hosted",
                reason=(
                    f"complex task ({needs.complexity}) and requested model is small "
                    f"({requested or 'unset'}) → configured frontier fallback"
                ),
                unchanged=False,
                required=sorted(needs.capabilities),
                alternatives=all_candidates,
            )
        if reasoning_local:
            return ModelRoute(
                model=reasoning_local,
                provider="local",
                reason=f"complex task → reasoning-capable local model ({needs.complexity})",
                unchanged=reasoning_local == requested,
                required=sorted(needs.capabilities),
                alternatives=all_candidates,
            )
        # "frontier" mode may use any hosted model exposed by the proxy.
        if mode == "frontier" and hosted:
            chosen = sorted(hosted)[0]
            return ModelRoute(
                model=chosen,
                provider="hosted",
                reason="frontier mode → hosted fallback",
                unchanged=False,
                required=sorted(needs.capabilities),
                alternatives=all_candidates,
            )

    for model_id in all_candidates:
        if _eligible(model_id, needs, ollama_url):
            return ModelRoute(
                model=model_id,
                provider=_provider(model_id, hosted),
                reason=(
                    "requested model satisfies task requirements"
                    if model_id == requested
                    else f"routed for capability {sorted(needs.capabilities) or 'chat'}"
                ),
                unchanged=model_id == requested,
                required=sorted(needs.capabilities),
                alternatives=all_candidates,
            )

    return ModelRoute(
        model=requested,
        provider=_provider(requested, hosted),
        reason="no candidate satisfied all requirements; keeping requested model",
        unchanged=True,
        required=sorted(needs.capabilities),
        alternatives=all_candidates,
    )


def describe_route(route: ModelRoute) -> dict[str, Any]:
    """Small JSON-safe summary for logs/UI."""
    data = route.to_dict()
    data["parameter_size"] = infer_from_name(route.model).parameter_size
    return data
