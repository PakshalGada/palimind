from __future__ import annotations

"""Tool telemetry: per-call debug trace and the global tool audit log.

Two artifacts are written under the field's ``.palimind/`` directory (or
``~/.palimind`` when no field root is configured):

  - ``tool_debug.log``   — one "call" line before a tool runs and one "done"
                           line after, with the tool name, sanitized args and
                           the result status. Args never carry file contents.
  - ``tool_audit.jsonl`` — one line per tool call: {timestamp, agent_id,
                           session_id, tool_name, args_hash, result_status,
                           duration_ms}. Args are hashed (SHA-256), never
                           stored, so traceability is retained without
                           persisting potentially sensitive content.

Both files are appended under a process-wide lock because parallel agent
threads may call tools concurrently.
"""

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from palimind.settings import TOOL_AUDIT_LOG, TOOL_DEBUG_LOG

_write_lock = threading.Lock()

# Arg keys whose values are content (file contents, code, payloads) and must
# never be written to the debug log.
_REDACTED_KEYS = frozenset({"content", "code", "text", "message", "payload"})

_MAX_ARG_LEN = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def tool_base_dir() -> Path:
    """Return the field's ``.palimind`` directory (home fallback)."""
    try:
        from palimind.llm.mixture_of_expert.tools import _get_context

        root = _get_context().get("root")
        if root is not None:
            return Path(root) / ".palimind"
    except Exception:
        pass
    return Path.home() / ".palimind"


def sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *args* safe for the debug log.

    Content-bearing keys (file contents, code, payloads) are redacted to a
    marker; every string value is truncated so the log stays small.
    """
    clean: dict[str, Any] = {}
    for key, value in args.items():
        if key in _REDACTED_KEYS:
            clean[key] = "<redacted>"
            continue
        if isinstance(value, str):
            clean[key] = value if len(value) <= _MAX_ARG_LEN else value[:_MAX_ARG_LEN] + "…"
        elif isinstance(value, (list, tuple)):
            clean[key] = [sanitize_args(v) if isinstance(v, dict) else v for v in value][:20]
        elif isinstance(value, dict):
            clean[key] = sanitize_args(value)
        else:
            clean[key] = value
    return clean


def hash_args(args: dict[str, Any]) -> str:
    """Deterministic SHA-256 of the canonical JSON form of *args*."""
    blob = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def debug_log_call(tool_name: str, args: dict[str, Any]) -> None:
    """Log that a tool is about to execute (before line)."""
    if not TOOL_DEBUG_LOG:
        return
    _append(
        "tool_debug.log",
        {
            "ts": _now_iso(),
            "event": "call",
            "tool": tool_name,
            "args": sanitize_args(args),
        },
    )


def debug_log_done(tool_name: str, status: str, duration_ms: float) -> None:
    """Log a tool's result status (after line)."""
    if not TOOL_DEBUG_LOG:
        return
    _append(
        "tool_debug.log",
        {
            "ts": _now_iso(),
            "event": "done",
            "tool": tool_name,
            "status": status,
            "duration_ms": round(duration_ms, 2),
        },
    )


def audit_log_tool(
    tool_name: str,
    args_hash: str,
    result_status: str,
    duration_ms: float,
    agent_id: str = "",
    session_id: str = "",
) -> None:
    """Append one line to the global tool audit log."""
    if not TOOL_AUDIT_LOG:
        return
    _append(
        "tool_audit.jsonl",
        {
            "timestamp": _now_iso(),
            "agent_id": agent_id,
            "session_id": session_id,
            "tool_name": tool_name,
            "args_hash": args_hash,
            "result_status": result_status,
            "duration_ms": round(duration_ms, 2),
        },
    )


def _append(filename: str, record: dict[str, Any]) -> None:
    try:
        path = tool_base_dir() / filename
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # telemetry must never break a tool call


def read_audit_log(
    limit: int = 200, offset: int = 0, base_dir: Path | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Read back the audit log (newest first) for the host UI.

    *base_dir* overrides the resolved tool base (used by the API endpoint
    which runs outside any tool execution context).
    """
    base = base_dir or tool_base_dir()
    path = base / "tool_audit.jsonl"
    entries: list[dict[str, Any]] = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            return [], str(e)
    total = len(entries)
    start = max(0, offset)
    return list(reversed(entries))[start : start + limit], total
