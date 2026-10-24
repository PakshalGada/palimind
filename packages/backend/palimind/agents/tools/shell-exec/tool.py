from __future__ import annotations

from pathlib import Path
from typing import Any

from palimind.security.sandbox import run_shell_isolated


def run_shell(command: str) -> str:
    """Run a shell command inside an OS sandbox (bubblewrap on Linux).

    The workspace is mounted read-only unless the agent has ``write_access``;
    networking is disabled.  If no real sandbox is available the call fails
    closed instead of running on the host.
    """
    from palimind.llm.mixture_of_expert.tools import _get_context

    ctx = _get_context()
    root: Path | None = ctx.get("root")
    if root is None:
        return "Error: no active workspace configured for shell execution."

    return run_shell_isolated(
        command,
        root=root,
        allow_network=bool(ctx.get("allow_network", False)),
        allow_write=bool(ctx.get("write_access", False)),
    )


# registry metadata for the main TOOL_REGISTRY
TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Run a shell command inside an OS sandbox (no network; workspace is "
        "read-only unless the agent has write access). Requires shell_access."
    ),
    "parameters": {
        "command": "The shell command to execute",
    },
    "tier": 2,
    "requires_approval": True,
}
