from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from core.settings import SHELL_EXEC_TIMEOUT


def run_shell(command: str) -> str:
    """Run a shell command in a jailed working directory (the field root).
    Timeout enforced from settings.SHELL_EXEC_TIMEOUT. Captures stdout and
    stderr. Only callable by agents with shell_access: true (enforced by
    the tool permission layer)."""
    from core.llm.mixture_of_expert.tools import _get_context

    ctx = _get_context()
    root: Path | None = ctx.get("root")
    if root is None:
        return "Error: no active workspace configured for shell execution."

    if not isinstance(command, str) or not command.strip():
        return "Error: command is required"

    cwd = str(root)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=SHELL_EXEC_TIMEOUT,
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        if proc.returncode != 0:
            parts = [f"Error (exit {proc.returncode})"]
            if err:
                parts.append(err[-2000:])
            if out:
                parts.append(out[-2000:])
            return "\n".join(parts)
        # Success: return stdout, and keep any stderr alongside it rather
        # than silently discarding it.
        parts = []
        if out:
            parts.append(out[-4000:])
        if err:
            parts.append(f"[stderr]\n{err[-2000:]}")
        return "\n".join(parts) if parts else "Command completed successfully (no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {SHELL_EXEC_TIMEOUT}s"
    except OSError as e:
        return f"Error running command: {e}"
    except Exception as e:
        return f"Error running command: {e}"


# registry metadata for the main TOOL_REGISTRY
TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Run a shell command in a jailed working directory (the field root). "
        "Requires shell_access on the agent. stdout/stderr are returned."
    ),
    "parameters": {
        "command": "The shell command to execute",
    },
    "tier": 2,
    "requires_approval": True,
}
