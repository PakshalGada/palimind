"""Small helpers for per-run token usage and cost estimates.

Local Ollama inference is free, so the default rates are 0 and the UI can show
"local · $0". Cloud/OpenCode-proxy users can set
``PALIMIND_COST_INPUT_PER_MTOK`` / ``PALIMIND_COST_OUTPUT_PER_MTOK`` to get a
useful estimate without introducing a remote price lookup.
"""

from __future__ import annotations

from palimind.settings import COST_INPUT_PER_MTOK, COST_OUTPUT_PER_MTOK


def normalize_usage(usage: dict | None) -> dict[str, int]:
    """Return integer prompt/completion token counts from any usage payload."""
    data = usage or {}
    try:
        prompt = max(0, int(data.get("prompt_tokens", 0) or 0))
    except (TypeError, ValueError):
        prompt = 0
    try:
        completion = max(0, int(data.get("completion_tokens", 0) or 0))
    except (TypeError, ValueError):
        completion = 0
    return {"prompt_tokens": prompt, "completion_tokens": completion}


def estimate_cost_usd(usage: dict | None) -> float:
    """Estimate cost for *usage* using the configured per-million-token rates."""
    tokens = normalize_usage(usage)
    cost = tokens["prompt_tokens"] / 1_000_000 * float(COST_INPUT_PER_MTOK) + tokens[
        "completion_tokens"
    ] / 1_000_000 * float(COST_OUTPUT_PER_MTOK)
    return round(max(0.0, cost), 6)


def usage_payload(usage: dict | None) -> dict[str, int | float]:
    """Token counts plus the cost estimate, ready for an SSE payload."""
    tokens = normalize_usage(usage)
    return {**tokens, "estimated_cost_usd": estimate_cost_usd(tokens)}
