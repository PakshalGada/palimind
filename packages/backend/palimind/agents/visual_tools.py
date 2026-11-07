"""Agent tools for sandboxed HTML visual replies."""

from __future__ import annotations

import json
from typing import Any

from palimind.agents import visuals


def _ctx() -> dict[str, Any]:
    from palimind.llm.mixture_of_expert.tools import _get_context

    return _get_context()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def html_render(html: str, title: str = "Visual reply", height: int = 600) -> str:
    record = visuals.create_visual(
        html,
        title=title,
        height=height,
        agent_id=str(_ctx().get("agent_id") or ""),
    )
    return _json({"visual": record})


def html_preview(html: str) -> str:
    record = visuals.create_visual(
        html,
        title="Preview",
        agent_id=str(_ctx().get("agent_id") or ""),
    )
    return _json(
        {
            "preview_url": record["url"],
            "height": record["height"],
            "console": [],
            "note": "Preview is sandboxed; open it in the visual panel.",
        }
    )


TOOLS: dict[str, dict[str, Any]] = {
    "html_render": {
        "fn": html_render,
        "description": "Publish a sandboxed HTML page above the answer.",
        "parameters": {
            "html": {"type": "string"},
            "title": {"type": "string", "required": False},
            "height": {"type": "integer", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "html_preview": {
        "fn": html_preview,
        "description": "Render an HTML preview without publishing a message.",
        "parameters": {"html": {"type": "string"}},
        "tier": 1,
        "requires_approval": False,
    },
}
