from __future__ import annotations

import subprocess
import sys

from palimind.settings import PYTHON_EXEC_MEMORY_MB, PYTHON_EXEC_TIMEOUT


def _limit_memory() -> None:
    """Best-effort address-space cap; skipped on platforms without resource."""
    try:
        import resource

        limit = PYTHON_EXEC_MEMORY_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, OSError, ValueError):
        pass  # Windows / hardened environments: rely on timeout only


def run_python(code: str) -> str:
    """Execute a short Python snippet in a subprocess with timeout and,
    where supported by the OS, an address-space memory cap."""
    if not code or not str(code).strip():
        return "Error: code is required"

    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", str(code)],
            capture_output=True,
            text=True,
            timeout=PYTHON_EXEC_TIMEOUT,
            preexec_fn=_limit_memory if sys.platform != "win32" else None,
        )
    except subprocess.TimeoutExpired:
        return f"Error: execution exceeded {PYTHON_EXEC_TIMEOUT}s timeout"
    except OSError as exc:
        return f"Error: failed to start interpreter ({exc})"

    parts: list[str] = []
    if proc.stdout.strip():
        parts.append(proc.stdout.strip())
    if proc.returncode != 0:
        err = proc.stderr.strip()
        parts.append(f"Error (exit {proc.returncode})" + (f": {err[-2000:]}" if err else ""))
    elif proc.stderr.strip():
        parts.append(f"[stderr]\n{proc.stderr.strip()[-2000:]}")
    return "\n".join(parts) if parts else "(no output)"
