"""Portable sandbox enforcement for agent tools.

Deliberately avoids OS-specific facilities (seccomp, App Sandbox) so limits
behave identically on Windows, macOS and Linux: wall-clock timeout, output
size cap, and audit logging.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from palimind.agents.tools.audit import (
    audit_log_tool,
    debug_log_call,
    debug_log_done,
    hash_args,
    sanitize_args,
)
from palimind.settings import TOOL_DEBUG_LOG

MAX_OUTPUT_CHARS = 20_000

T = TypeVar("T")


def clamp_output(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [output truncated at {limit} chars]"


async def run_sandboxed(
    fn: Callable[[], Any],
    timeout_s: int,
    tool_name: str,
    args_summary: dict[str, Any] | None = None,
) -> str:
    """Run ``fn`` with a hard timeout, output clamp and audit trail."""
    loop = asyncio.get_running_loop()
    started = time.perf_counter()
    safe_args = sanitize_args(args_summary or {})
    args_hash = hash_args(safe_args)

    if TOOL_DEBUG_LOG:
        debug_log_call(tool_name, safe_args)

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(fn)),
            timeout=timeout_s,
        )
    except TimeoutError:
        duration = (time.perf_counter() - started) * 1000
        if TOOL_DEBUG_LOG:
            debug_log_done(tool_name, "timeout", duration)
        audit_log_tool(tool_name, args_hash, "timeout", duration)
        raise
    except Exception:
        duration = (time.perf_counter() - started) * 1000
        if TOOL_DEBUG_LOG:
            debug_log_done(tool_name, "error", duration)
        audit_log_tool(tool_name, args_hash, "error", duration)
        raise

    duration = (time.perf_counter() - started) * 1000
    output = clamp_output(str(result))

    if TOOL_DEBUG_LOG:
        debug_log_done(tool_name, "ok", duration)
    audit_log_tool(tool_name, args_hash, "ok", duration)

    return output


def run_sandboxed_sync(
    fn: Callable[[], Any],
    timeout_s: int,
    tool_name: str,
    args_summary: dict[str, Any] | None = None,
    *,
    agent_id: str = "",
    session_id: str = "",
) -> str:
    """Synchronous counterpart of :func:`run_sandboxed`.

    The live agent loop executes tools from a worker thread, so it cannot
    await the async sandbox. This runs ``fn`` on a daemon thread and enforces
    the same wall-clock timeout, output clamp and audit trail. On timeout the
    worker thread is abandoned (Python cannot forcibly kill a thread) — the
    same trade-off the async version makes when it cancels the await.
    """
    started = time.perf_counter()
    safe_args = sanitize_args(args_summary or {})
    args_hash = hash_args(safe_args)

    if TOOL_DEBUG_LOG:
        debug_log_call(tool_name, safe_args)

    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller thread
            box["error"] = exc

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(timeout_s)

    if worker.is_alive():
        duration = (time.perf_counter() - started) * 1000
        if TOOL_DEBUG_LOG:
            debug_log_done(tool_name, "timeout", duration)
        audit_log_tool(tool_name, args_hash, "timeout", duration, agent_id, session_id)
        raise TimeoutError(f"tool '{tool_name}' timed out after {timeout_s}s")

    duration = (time.perf_counter() - started) * 1000
    if "error" in box:
        if TOOL_DEBUG_LOG:
            debug_log_done(tool_name, "error", duration)
        audit_log_tool(tool_name, args_hash, "error", duration, agent_id, session_id)
        raise box["error"]

    output = clamp_output(str(box.get("value")))
    if TOOL_DEBUG_LOG:
        debug_log_done(tool_name, "ok", duration)
    audit_log_tool(tool_name, args_hash, "ok", duration, agent_id, session_id)
    return output
