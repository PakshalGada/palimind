"""Portable sandbox enforcement for agent tools.

Deliberately avoids OS-specific facilities (seccomp, App Sandbox) so limits
behave identically on Windows, macOS and Linux: wall-clock timeout, output
size cap, and audit logging.
"""

from __future__ import annotations

import asyncio
import functools
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
