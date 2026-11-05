"""Tests for parallel read-only tool execution."""

from __future__ import annotations

import time

from palimind.llm.mixture_of_expert.agents import _execute_tool_batch, _is_parallel_safe
from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY


def _register(name: str, *, parallel_safe: bool, delay: float = 0.3) -> None:
    def _slow() -> str:
        time.sleep(delay)
        return f"ok:{name}"

    TOOL_REGISTRY[name] = {
        "fn": _slow,
        "description": "test tool",
        "parameters": {},
        "meta": {"tier": 1, "requires_approval": False},
        "parallel_safe": parallel_safe,
        "idempotent": True,
        "timeout_s": 10,
    }


def test_parallel_safe_requires_registered_tier1_read_tool() -> None:
    _register("_parallel_probe", parallel_safe=True)
    try:
        assert _is_parallel_safe("_parallel_probe", {"tools": ["_parallel_probe"]})
        assert not _is_parallel_safe("_parallel_probe", {"tools": ["other_tool"]})
        assert not _is_parallel_safe("write_file", {"tools": ["write_file"]})
        assert not _is_parallel_safe("does_not_exist", {"tools": []})
    finally:
        TOOL_REGISTRY.pop("_parallel_probe", None)


def test_read_only_calls_run_concurrently() -> None:
    names = ["_p1", "_p2", "_p3", "_p4"]
    for name in names:
        _register(name, parallel_safe=True, delay=0.3)
    try:
        calls = [{"name": name, "arguments": {}} for name in names]
        started = time.monotonic()
        batch = _execute_tool_batch(1, calls, {"tools": names}, None, [], run_control=None)
        elapsed = time.monotonic() - started
        assert [r for _c, r in batch] == [f"ok:{n}" for n in names]
        # Four 0.3s calls in parallel should finish well under the 1.2s serial
        # time. Allow generous CI headroom.
        assert elapsed < 0.9, elapsed
    finally:
        for name in names:
            TOOL_REGISTRY.pop(name, None)


def test_write_calls_stay_serial() -> None:
    names = ["_w1", "_w2"]
    for name in names:
        _register(name, parallel_safe=False, delay=0.3)
    try:
        calls = [{"name": name, "arguments": {}} for name in names]
        started = time.monotonic()
        _execute_tool_batch(1, calls, {"tools": names}, None, [], run_control=None)
        elapsed = time.monotonic() - started
        assert elapsed >= 0.55, elapsed
    finally:
        for name in names:
            TOOL_REGISTRY.pop(name, None)


def test_results_keep_model_call_order() -> None:
    _register("_fast", parallel_safe=True, delay=0.05)
    _register("_slow", parallel_safe=True, delay=0.3)
    try:
        calls = [
            {"name": "_slow", "arguments": {}},
            {"name": "_fast", "arguments": {}},
        ]
        batch = _execute_tool_batch(
            1, calls, {"tools": ["_slow", "_fast"]}, None, [], run_control=None
        )
        assert [c["name"] for c, _r in batch] == ["_slow", "_fast"]
        assert [r for _c, r in batch] == ["ok:_slow", "ok:_fast"]
    finally:
        TOOL_REGISTRY.pop("_fast", None)
        TOOL_REGISTRY.pop("_slow", None)
