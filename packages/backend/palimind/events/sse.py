"""SSE formatting/parsing helpers shared by replayable streams."""

from __future__ import annotations

import json
from typing import Any


def format_event(event: dict[str, Any]) -> str:
    event_id = event.get("event_id")
    data = {k: v for k, v in event.items() if k not in ("event_id", "stream", "created_at")}
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False, default=str)}")
    return "\n".join(lines) + "\n\n"


def parse_data(chunk: Any) -> dict[str, Any] | None:
    if isinstance(chunk, (bytes, bytearray, memoryview)):
        chunk = bytes(chunk).decode("utf-8", "replace")
    for line in str(chunk).splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            value = json.loads(line[5:].strip())
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def last_event_id(headers: Any = None, query_value: str | int | None = None) -> int:
    """Read Last-Event-ID from headers or a query fallback."""
    raw: Any = None
    try:
        from fastapi import Request

        if isinstance(headers, Request):
            raw = headers.headers.get("last-event-id") or headers.query_params.get("last_event_id")
        else:
            raw = None
            if headers is not None:
                raw = getattr(headers, "get", lambda *_: None)("last-event-id")
            raw = raw or query_value
    except Exception:
        raw = query_value
    try:
        return max(0, int(str(raw or 0).strip()))
    except (TypeError, ValueError):
        return 0
