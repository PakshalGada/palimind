"""Routine flows: hand a routine result to other agents.

A flow is a small DAG keyed by routine.  A link belongs to one routine and
applies to runs that started after it.  An agent with several inbound links
waits for all of them; if every inbound step failed, the agent is skipped.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from palimind.storage import state_store


def _now() -> float:
    return time.time()


def _load(raw: Any, default: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        value = json.loads(raw or "")
        return value
    except (TypeError, json.JSONDecodeError):
        return default


def _flow_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "canvas_agent_id": row["canvas_agent_id"],
        "routine_id": row["routine_id"],
        "links": _load(row["links"], []),
        "positions": _load(row["positions"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _step_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def save_flow(
    canvas_agent_id: str,
    routine_id: str,
    *,
    links: list[dict[str, Any]] | None = None,
    positions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not str(routine_id or "").strip():
        raise ValueError("routine_id is required")
    existing = get_flow_by_canvas(canvas_agent_id)
    now = _now()
    if existing is None:
        flow_id = str(uuid.uuid4())
        conn = state_store.state_connection()
        try:
            conn.execute(
                """
                INSERT INTO routine_flows(id, canvas_agent_id, routine_id, links, positions, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    flow_id,
                    str(canvas_agent_id or ""),
                    str(routine_id),
                    json.dumps(links or []),
                    json.dumps(positions or {}),
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return get_flow(flow_id) or {}
    conn = state_store.state_connection()
    try:
        conn.execute(
            "UPDATE routine_flows SET links=?, positions=?, updated_at=? WHERE id=?",
            (
                json.dumps(links if links is not None else existing.get("links") or []),
                json.dumps(positions if positions is not None else existing.get("positions") or {}),
                now,
                existing["id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_flow(existing["id"]) or {}


def get_flow(flow_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM routine_flows WHERE id=?", (flow_id,)).fetchone()
    finally:
        conn.close()
    return _flow_row(row)


def get_flow_by_canvas(canvas_agent_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT * FROM routine_flows WHERE canvas_agent_id=? ORDER BY created_at ASC LIMIT 1",
            (canvas_agent_id,),
        ).fetchone()
    finally:
        conn.close()
    return _flow_row(row)


def get_flow_by_routine(canvas_agent_id: str, routine_id: str) -> dict[str, Any] | None:
    flow = get_flow_by_canvas(canvas_agent_id)
    if flow is None:
        return None
    if str(flow.get("routine_id") or "") == routine_id:
        return flow
    if any(str(link.get("routine_id")) == routine_id for link in flow.get("links") or []):
        return flow
    return None


def list_flows(canvas_agent_id: str = "") -> list[dict[str, Any]]:
    clause = "WHERE canvas_agent_id=?" if canvas_agent_id else ""
    args = (canvas_agent_id,) if canvas_agent_id else ()
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM routine_flows {clause} ORDER BY updated_at DESC", args
        ).fetchall()
    finally:
        conn.close()
    return [flow for flow in (_flow_row(row) for row in rows) if flow is not None]


def connect(canvas_agent_id: str, routine_id: str, to_agent_id: str) -> dict[str, Any]:
    if not str(to_agent_id or "").strip():
        raise ValueError("to_agent_id is required")
    flow = get_flow_by_routine(canvas_agent_id, routine_id) or save_flow(
        canvas_agent_id, routine_id
    )
    links = list(flow.get("links") or [])
    if not any(
        str(link.get("routine_id")) == routine_id and str(link.get("to_agent_id")) == to_agent_id
        for link in links
    ):
        links.append({"routine_id": routine_id, "to_agent_id": to_agent_id, "created_at": _now()})
    return save_flow(
        canvas_agent_id, routine_id, links=links, positions=flow.get("positions") or {}
    )


def disconnect(canvas_agent_id: str, routine_id: str, to_agent_id: str) -> dict[str, Any]:
    flow = get_flow_by_routine(canvas_agent_id, routine_id)
    if flow is None:
        return {}
    links = [
        link
        for link in flow.get("links") or []
        if not (
            str(link.get("routine_id")) == routine_id
            and str(link.get("to_agent_id")) == to_agent_id
        )
    ]
    return save_flow(
        canvas_agent_id, routine_id, links=links, positions=flow.get("positions") or {}
    )


def add_step(
    flow_id: str,
    *,
    from_routine: str,
    to_agent: str,
    from_run: str,
    input_text: str = "",
) -> dict[str, Any]:
    step_id = str(uuid.uuid4())
    now = _now()
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO routine_flow_steps
                (id, flow_id, from_routine, to_agent, from_run, status, input, output, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, '', '', ?, ?)
            """,
            (step_id, flow_id, from_routine, to_agent, from_run, str(input_text or ""), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return get_step(step_id) or {}


def get_step(step_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM routine_flow_steps WHERE id=?", (step_id,)).fetchone()
    finally:
        conn.close()
    return _step_row(row)


def list_steps(flow_id: str, *, status: str = "", limit: int = 500) -> list[dict[str, Any]]:
    clauses = ["flow_id=?"]
    args: list[Any] = [flow_id]
    if status:
        clauses.append("status=?")
        args.append(status)
    args.append(max(1, min(int(limit or 500), 2000)))
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM routine_flow_steps WHERE {' AND '.join(clauses)} ORDER BY created_at ASC LIMIT ?",
            args,
        ).fetchall()
    finally:
        conn.close()
    return [step for step in (_step_row(row) for row in rows) if step is not None]


def complete_step(step_id: str, output: str) -> dict[str, Any] | None:
    return _set_step(step_id, "succeeded", output=output)


def fail_step(step_id: str, error: str) -> dict[str, Any] | None:
    return _set_step(step_id, "failed", error=error)


def _set_step(
    step_id: str, status: str, *, output: str = "", error: str = ""
) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        conn.execute(
            "UPDATE routine_flow_steps SET status=?, output=?, error=?, updated_at=? WHERE id=?",
            (status, str(output or "")[:20_000], str(error or "")[:4_000], _now(), step_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_step(step_id)


def record_result(
    canvas_agent_id: str,
    routine_id: str,
    run_id: str,
    *,
    status: str,
    output: str = "",
    error: str = "",
) -> list[dict[str, Any]]:
    """Record a routine result and create the outbound steps it triggers."""
    flow = get_flow_by_routine(canvas_agent_id, routine_id)
    if flow is None:
        return []
    steps = []
    for link in flow.get("links") or []:
        if str(link.get("routine_id")) != routine_id:
            continue
        step = add_step(
            flow["id"],
            from_routine=routine_id,
            to_agent=str(link.get("to_agent_id")),
            from_run=run_id,
            input_text=output,
        )
        if status in ("success", "completed"):
            complete_step(step["id"], output)
        else:
            fail_step(step["id"], error or "routine failed")
        steps.append(get_step(step["id"]) or step)
    return steps


def ready_handoffs(flow_id: str, run_id: str) -> list[dict[str, Any]]:
    """Return target agents whose inbound steps for *run_id* all finished."""
    flow = get_flow(flow_id)
    if flow is None:
        return []
    expected: dict[str, set[str]] = {}
    for link in flow.get("links") or []:
        expected.setdefault(str(link.get("to_agent_id") or ""), set()).add(
            str(link.get("routine_id") or "")
        )
    steps = [s for s in list_steps(flow_id) if str(s.get("from_run")) == run_id]
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for step in steps:
        by_agent.setdefault(str(step.get("to_agent") or ""), []).append(step)
    out = []
    for agent_id, routines_for_agent in expected.items():
        if not agent_id:
            continue
        group = by_agent.get(agent_id, [])
        covered = {str(step.get("from_routine") or "") for step in group}
        if not routines_for_agent.issubset(covered):
            continue  # a routine in this fan-in has not reported yet
        if any(step.get("status") == "pending" for step in group):
            continue
        if group and all(step.get("status") == "failed" for step in group):
            continue
        out.append(
            {
                "agent_id": agent_id,
                "text": "\n\n".join(
                    str(step.get("output") or "")
                    for step in group
                    if step.get("status") == "succeeded"
                ),
                "steps": group,
            }
        )
    return out


def flow_status(flow_id: str) -> dict[str, Any] | None:
    flow = get_flow(flow_id)
    if flow is None:
        return None
    steps = list_steps(flow_id)
    return {
        **flow,
        "steps": steps,
        "pending": len([s for s in steps if s.get("status") == "pending"]),
        "failed": len([s for s in steps if s.get("status") == "failed"]),
    }
