"""Browser profiles, tab state and human takeover requests.

The state is durable even when the browser process restarts.  The browser host
uses a profile's storage partition; the agent only sees the profile name and
its tabs, never credentials.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from palimind.storage import state_store


def _now() -> float:
    return time.time()


def list_profiles() -> list[dict[str, Any]]:
    conn = state_store.state_connection()
    try:
        rows = conn.execute("SELECT * FROM browser_profiles ORDER BY created_at").fetchall()
    finally:
        conn.close()
    profiles = [dict(row) for row in rows]
    if not any(profile["id"] == "shared" for profile in profiles):
        profiles.insert(
            0,
            {
                "id": "shared",
                "name": "Shared",
                "color": "",
                "partition": "shared",
                "created_at": 0,
            },
        )
    return profiles


def create_profile(name: str, *, color: str = "", partition: str = "") -> dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise ValueError("profile name is required")
    profile_id = str(uuid.uuid4())
    conn = state_store.state_connection()
    try:
        conn.execute(
            "INSERT INTO browser_profiles(id, name, color, partition, created_at) VALUES (?, ?, ?, ?, ?)",
            (profile_id, name[:80], str(color or ""), str(partition or profile_id), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return next(p for p in list_profiles() if p["id"] == profile_id)


def update_profile(profile_id: str, **changes: Any) -> dict[str, Any] | None:
    if profile_id == "shared":
        return next(p for p in list_profiles() if p["id"] == "shared")
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM browser_profiles WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE browser_profiles SET name=?, color=? WHERE id=?",
            (
                str(changes.get("name", row["name"]))[:80],
                str(changes.get("color", row["color"])),
                profile_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return next((p for p in list_profiles() if p["id"] == profile_id), None)


def delete_profile(profile_id: str) -> bool:
    if profile_id == "shared":
        return False
    from palimind.agents.registry import get_registry

    for defn in get_registry().all():
        if str(getattr(defn, "browser_profile", "") or "") == profile_id:
            try:
                get_registry().update(defn.id, {"browser_profile": "shared"})
            except Exception:
                pass
    conn = state_store.state_connection()
    try:
        conn.execute("DELETE FROM browser_tabs WHERE profile_id=?", (profile_id,))
        cursor = conn.execute("DELETE FROM browser_profiles WHERE id=?", (profile_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def save_tab(
    profile_id: str,
    *,
    agent_id: str = "",
    url: str = "",
    title: str = "",
    opener_tab_id: str = "",
    tab_id: str = "",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tab_id = str(tab_id or uuid.uuid4())
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO browser_tabs(id, profile_id, agent_id, url, title, opener_tab_id, state, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                profile_id=excluded.profile_id, agent_id=excluded.agent_id,
                url=excluded.url, title=excluded.title,
                opener_tab_id=excluded.opener_tab_id, state=excluded.state,
                updated_at=excluded.updated_at
            """,
            (
                tab_id,
                str(profile_id or "shared"),
                str(agent_id or ""),
                str(url or ""),
                str(title or ""),
                str(opener_tab_id or ""),
                json.dumps(state or {}),
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return next(t for t in list_tabs(profile_id) if t["id"] == tab_id)


def list_tabs(profile_id: str = "", agent_id: str = "") -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if profile_id:
        clauses.append("profile_id=?")
        args.append(profile_id)
    if agent_id:
        clauses.append("agent_id=?")
        args.append(agent_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM browser_tabs {where} ORDER BY updated_at DESC", args
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        item = dict(row)
        item["state"] = json.loads(item.get("state") or "{}")
        out.append(item)
    return out


def delete_tab(tab_id: str) -> bool:
    conn = state_store.state_connection()
    try:
        cursor = conn.execute("DELETE FROM browser_tabs WHERE id=?", (tab_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def request_takeover(agent_id: str, *, tab_id: str = "", reason: str = "") -> dict[str, Any]:
    takeover_id = str(uuid.uuid4())
    conn = state_store.state_connection()
    try:
        conn.execute(
            "INSERT INTO browser_takeovers(id, agent_id, tab_id, reason, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (takeover_id, str(agent_id), str(tab_id or ""), str(reason or ""), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return get_takeover(takeover_id) or {}


def get_takeover(takeover_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM browser_takeovers WHERE id=?", (takeover_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def accept_takeover(takeover_id: str) -> dict[str, Any] | None:
    """Move a pending request to active. The browser lock is claimed by the API."""
    conn = state_store.state_connection()
    try:
        conn.execute(
            "UPDATE browser_takeovers SET status='active' WHERE id=? AND status='pending'",
            (takeover_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return get_takeover(takeover_id)


def list_takeovers(agent_id: str = "", *, status: str = "") -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if agent_id:
        clauses.append("agent_id=?")
        args.append(agent_id)
    if status:
        clauses.append("status=?")
        args.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM browser_takeovers {where} ORDER BY created_at DESC", args
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def resolve_takeover(takeover_id: str, *, status: str = "completed") -> dict[str, Any] | None:
    if status not in ("active", "completed", "cancelled", "expired"):
        raise ValueError("status must be active, completed, cancelled or expired")
    conn = state_store.state_connection()
    try:
        conn.execute(
            "UPDATE browser_takeovers SET status=?, finished_at=? WHERE id=?",
            (status, _now(), takeover_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_takeover(takeover_id)
