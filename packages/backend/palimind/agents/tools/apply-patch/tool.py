"""Apply unified-diff patches inside the workspace.

Code agents need an atomic edit primitive that is safer than rewriting whole
files. This tool validates every file path in the diff, applies it with
``git apply`` (falling back to ``patch -p1``), and refuses paths outside the
workspace or containing traversal segments.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

MAX_PATCH_CHARS = 500_000


def _root() -> Path | None:
    from palimind.llm.mixture_of_expert.tools import _get_context

    root = _get_context().get("root")
    return Path(root) if root else None


def _patch_paths(patch: str) -> tuple[list[str], str | None]:
    paths: list[str] = []
    for line in patch.splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        raw = line[4:].strip()
        # Strip timestamps and quotes if present.
        raw = raw.split("\t", 1)[0].strip().strip('"')
        if raw == "/dev/null":
            continue
        if raw.startswith(("a/", "b/")):
            raw = raw[2:]
        candidate = Path(raw)
        if candidate.is_absolute() or ".." in candidate.parts:
            return [], f"unsafe path in patch: {raw}"
        paths.append(raw)
    if not paths:
        return [], "patch contains no file paths (expected unified diff headers)"
    return paths, None


def apply_patch(patch: str) -> str:
    """Apply a unified diff to files in the active workspace."""
    root = _root()
    if root is None:
        return "Error: no active workspace configured for patching."
    text = str(patch or "")
    if not text.strip():
        return "Error: patch is required"
    if len(text) > MAX_PATCH_CHARS:
        return f"Error: patch is too large (max {MAX_PATCH_CHARS} chars)"
    paths, error = _patch_paths(text)
    if error:
        return f"Error: {error}"

    def _run(cmd: list[str]) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                input=text,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except FileNotFoundError:
            return False, f"{cmd[0]} is not installed"
        except subprocess.TimeoutExpired:
            return False, f"{cmd[0]} timed out"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, output.strip()

    ok, output = _run(["git", "apply", "--whitespace=nowarn", "-"])
    if not ok:
        # Some workspaces are not git repos; patch(1) is a portable fallback.
        ok, fallback_output = _run(["patch", "-p1", "--batch", "--forward"])
        if not ok:
            detail = output or fallback_output or "unknown error"
            return f"Error: patch failed to apply:\n{detail[:4000]}"
        output = fallback_output

    try:
        from palimind.llm.mixture_of_expert.tools import _schedule_reindex

        _schedule_reindex()
    except Exception:
        pass
    return (
        f"Applied patch to {len(paths)} file(s): {', '.join(paths[:10])}\n{output[:2000]}".strip()
    )


def _p(
    *,
    type: str = "string",
    description: str,
    required: bool = True,
    default: Any = None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {"type": type, "description": description, "required": required}
    if default is not None:
        spec["default"] = default
        spec["required"] = False
    return spec


TOOLS: dict[str, dict[str, Any]] = {
    "apply_patch": {
        "fn": apply_patch,
        "description": (
            "Apply a unified diff to workspace files atomically. Paths are "
            "validated to stay inside the workspace; requires approval."
        ),
        "parameters": {
            "patch": _p(description="Unified diff text (---/+++ headers and @@ hunks)"),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
}
