from __future__ import annotations

from typing import Any


def run(**kwargs: Any) -> str:
    """Legacy-style entrypoint; wrapped by FunctionTool automatically.

    Return a plain string. Start the string with "Error:" on failure —
    ToolResult.ok is derived from that convention.
    """
    return "Error: my-tool is not implemented yet"
