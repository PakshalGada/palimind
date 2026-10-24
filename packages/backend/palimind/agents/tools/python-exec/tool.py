from __future__ import annotations

from pathlib import Path

from palimind.security.sandbox import run_python_isolated


def run_python(code: str) -> str:
    """Execute a Python snippet inside an OS sandbox.

    Memory, CPU, file-size and process limits are applied by
    :mod:`palimind.security.sandbox`; the workspace is read-only unless the
    agent has ``write_access`` and networking is disabled.  There is no
    unsandboxed fallback unless the operator explicitly opts in.
    """
    if not code or not str(code).strip():
        return "Error: code is required"

    from palimind.llm.mixture_of_expert.tools import _get_context

    ctx = _get_context()
    root = ctx.get("root")
    if root is None:
        # Legacy callers (e.g. unit tests of the tool itself) get a temporary
        # scratch directory rather than the whole host filesystem.
        import tempfile

        root = Path(tempfile.mkdtemp(prefix="palimind-python-"))

    return run_python_isolated(
        str(code),
        root=Path(root),
        allow_network=bool(ctx.get("allow_network", False)),
        allow_write=bool(ctx.get("write_access", False)),
    )
