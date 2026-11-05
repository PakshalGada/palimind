"""Git tools for code agents.

All commands run inside the active workspace with an argument list (never a
shell), a timeout, and bounded output. Read-only commands are tier 1; commit /
branch mutations are tier 2 and go through the approval gate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

MAX_OUTPUT = 20_000


def _root() -> Path | None:
    from palimind.llm.mixture_of_expert.tools import _get_context

    root = _get_context().get("root")
    return Path(root) if root else None


def _run_git(args: list[str], *, timeout: int = 30) -> str:
    root = _root()
    if root is None:
        return "Error: no active workspace configured for git."
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout)),
            check=False,
        )
    except FileNotFoundError:
        return "Error: git is not installed."
    except subprocess.TimeoutExpired:
        return f"Error: git {' '.join(args)} timed out."
    except Exception as exc:  # noqa: BLE001
        return f"Error: git failed: {exc}"
    out = (proc.stdout or "") + (proc.stderr or "")
    out = out.strip() or "(no output)"
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n...[truncated]"
    if proc.returncode != 0:
        return f"Error (git exit {proc.returncode}):\n{out}"
    return out


def git_status() -> str:
    """Show the working tree status (short form) and current branch."""
    return _run_git(["status", "--short", "--branch"])


def git_diff(path: str = "", staged: bool = False, max_chars: int = 12_000) -> str:
    """Show unstaged or staged changes, optionally limited to one path."""
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    if path:
        args.extend(["--", path])
    out = _run_git(args)
    try:
        cap = max(500, min(int(max_chars or 12_000), MAX_OUTPUT))
    except (TypeError, ValueError):
        cap = 12_000
    return out[:cap] + ("\n...[truncated]" if len(out) > cap else "")


def git_log(limit: int = 20) -> str:
    """Show recent commits, one line each."""
    try:
        n = max(1, min(int(limit or 20), 200))
    except (TypeError, ValueError):
        n = 20
    return _run_git(["log", "--oneline", "--decorate", f"-n{n}"])


def git_show(rev: str = "HEAD", max_chars: int = 12_000) -> str:
    """Show one commit (metadata + patch)."""
    out = _run_git(["show", "--no-color", "--stat", str(rev or "HEAD")])
    try:
        cap = max(500, min(int(max_chars or 12_000), MAX_OUTPUT))
    except (TypeError, ValueError):
        cap = 12_000
    return out[:cap] + ("\n...[truncated]" if len(out) > cap else "")


def git_commit(message: str, all: bool = False) -> str:
    """Commit staged changes (or stage everything first with ``all=True``)."""
    if not message or not str(message).strip():
        return "Error: commit message is required"
    if all:
        staged = _run_git(["add", "-A"])
        if staged.startswith("Error"):
            return staged
    return _run_git(["commit", "-m", str(message).strip()])


def git_branch(name: str = "", create: bool = False) -> str:
    """List branches, or create/switch to *name*."""
    if name:
        if create:
            return _run_git(["checkout", "-b", name])
        return _run_git(["checkout", name])
    return _run_git(["branch", "--all", "--verbose", "--no-abbrev"])


def _p(
    *,
    type: str = "string",
    description: str,
    required: bool = True,
    default: Any = None,
    enum: tuple[str, ...] = (),
) -> dict[str, Any]:
    spec: dict[str, Any] = {"type": type, "description": description, "required": required}
    if default is not None:
        spec["default"] = default
        spec["required"] = False
    if enum:
        spec["enum"] = list(enum)
    return spec


TOOLS: dict[str, dict[str, Any]] = {
    "git_status": {
        "fn": git_status,
        "description": "Show the workspace git status (short form) and current branch.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "git_diff": {
        "fn": git_diff,
        "description": "Show unstaged or staged git changes, optionally for one path.",
        "parameters": {
            "path": _p(description="Optional path to diff", required=False),
            "staged": _p(type="boolean", description="Show staged changes", default=False),
            "max_chars": _p(type="integer", description="Maximum characters", default=12000),
        },
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "git_log": {
        "fn": git_log,
        "description": "Show recent commits, one line each.",
        "parameters": {
            "limit": _p(type="integer", description="Number of commits", default=20),
        },
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "git_show": {
        "fn": git_show,
        "description": "Show one commit (metadata and patch).",
        "parameters": {
            "rev": _p(description="Revision (default HEAD)", default="HEAD"),
            "max_chars": _p(type="integer", description="Maximum characters", default=12000),
        },
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "git_commit": {
        "fn": git_commit,
        "description": "Commit changes. Requires approval; use all=true to stage everything.",
        "parameters": {
            "message": _p(description="Commit message"),
            "all": _p(type="boolean", description="Stage all changes first", default=False),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
    "git_branch": {
        "fn": git_branch,
        "description": "List branches, or create/switch to a branch by name.",
        "parameters": {
            "name": _p(description="Branch name", required=False),
            "create": _p(type="boolean", description="Create the branch", default=False),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
}
