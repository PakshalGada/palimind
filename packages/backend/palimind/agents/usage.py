"""Local usage records and aggregates.

Usage never leaves the process or the local SQLite database.  Cost is an
API-equivalent estimate from configured per-million-token prices; unknown
prices stay unpriced.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from palimind.storage import state_store


def _day(value: str = "") -> str:
    if value:
        return value[:10]
    return datetime.now(UTC).date().isoformat()


def record_usage(
    agent_id: str,
    *,
    thread_id: str = "",
    provider: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_estimate: float = 0.0,
    day: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "id": str(uuid.uuid4()),
        "agent_id": str(agent_id or ""),
        "thread_id": str(thread_id or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "day": _day(day),
        "prompt_tokens": max(0, int(prompt_tokens or 0)),
        "completion_tokens": max(0, int(completion_tokens or 0)),
        "cost_estimate": max(0.0, float(cost_estimate or 0.0)),
        "metadata": dict(metadata or {}),
        "created_at": time.time(),
    }
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO usage_records
                (id, agent_id, thread_id, provider, model, day, prompt_tokens,
                 completion_tokens, cost_estimate, value, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["agent_id"],
                record["thread_id"],
                record["provider"],
                record["model"],
                record["day"],
                record["prompt_tokens"],
                record["completion_tokens"],
                record["cost_estimate"],
                json.dumps(record["metadata"]),
                record["created_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return record


def list_usage(
    agent_id: str = "",
    *,
    start: str = "",
    end: str = "",
    provider: str = "",
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if agent_id:
        clauses.append("agent_id=?")
        args.append(agent_id)
    if start:
        clauses.append("day>=?")
        args.append(start[:10])
    if end:
        clauses.append("day<=?")
        args.append(end[:10])
    if provider:
        clauses.append("provider=?")
        args.append(provider)
    args.append(max(1, min(int(limit or 10_000), 50_000)))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM usage_records {where} ORDER BY day DESC, created_at DESC LIMIT ?", args
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def aggregate(
    agent_id: str = "",
    *,
    start: str = "",
    end: str = "",
    provider: str = "",
) -> dict[str, Any]:
    rows = list_usage(agent_id, start=start, end=end, provider=provider)
    by_day: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}
    total = {"prompt_tokens": 0, "completion_tokens": 0, "cost_estimate": 0.0, "calls": 0}
    for row in rows:
        prompt = int(row.get("prompt_tokens") or 0)
        completion = int(row.get("completion_tokens") or 0)
        cost = float(row.get("cost_estimate") or 0.0)
        total["prompt_tokens"] += prompt
        total["completion_tokens"] += completion
        total["cost_estimate"] += cost
        total["calls"] += 1
        for bucket, key in (
            (by_day, str(row.get("day") or "")),
            (by_agent, str(row.get("agent_id") or "")),
            (by_provider, str(row.get("provider") or "")),
        ):
            entry = bucket.setdefault(
                key, {"prompt_tokens": 0, "completion_tokens": 0, "cost_estimate": 0.0, "calls": 0}
            )
            entry["prompt_tokens"] += prompt
            entry["completion_tokens"] += completion
            entry["cost_estimate"] += cost
            entry["calls"] += 1
    return {
        "total": total,
        "by_day": [{"day": k, **v} for k, v in sorted(by_day.items())],
        "by_agent": [{"agent_id": k, **v} for k, v in sorted(by_agent.items())],
        "by_provider": [{"provider": k, **v} for k, v in sorted(by_provider.items())],
        "unpriced_calls": len([row for row in rows if not row.get("cost_estimate")]),
    }


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    *,
    input_per_mtok: float = 0.0,
    output_per_mtok: float = 0.0,
) -> float:
    return round(
        (max(0, int(prompt_tokens or 0)) / 1_000_000.0) * max(0.0, float(input_per_mtok or 0.0))
        + (max(0, int(completion_tokens or 0)) / 1_000_000.0)
        * max(0.0, float(output_per_mtok or 0.0)),
        6,
    )


def default_range(days: int = 30) -> tuple[str, str]:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=max(1, int(days)) - 1)
    return start.isoformat(), end.isoformat()
