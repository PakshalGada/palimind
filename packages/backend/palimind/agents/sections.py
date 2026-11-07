"""Agent sidebar sections.

Sections are a small ordered grouping over agents.  They are stored globally
with the agents, not in a workspace config file.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from palimind.storage import state_store


def _now() -> float:
    return time.time()


def list_sections() -> list[dict[str, Any]]:
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM agent_sections ORDER BY sort_order ASC, created_at ASC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def get_section(section_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM agent_sections WHERE id=?", (section_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def create_section(name: str, *, sort_order: int = 0) -> dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise ValueError("section name is required")
    section_id = str(uuid.uuid4())
    conn = state_store.state_connection()
    try:
        conn.execute(
            "INSERT INTO agent_sections(id, name, sort_order, created_at) VALUES (?, ?, ?, ?)",
            (section_id, name[:80], int(sort_order or 0), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return get_section(section_id) or {}


def rename_section(section_id: str, name: str) -> dict[str, Any] | None:
    name = str(name or "").strip()
    if not name:
        raise ValueError("section name is required")
    conn = state_store.state_connection()
    try:
        conn.execute(
            "UPDATE agent_sections SET name=? WHERE id=?", (name[:80], section_id)
        )
        conn.commit()
    finally:
        conn.close()
    return get_section(section_id)


def delete_section(section_id: str) -> bool:
    from palimind.agents.registry import get_registry

    for defn in get_registry().all():
        if str(getattr(defn, "section_id", "") or "") == section_id:
            try:
                get_registry().update(defn.id, {"section_id": ""})
            except Exception:
                pass
    conn = state_store.state_connection()
    try:
        cursor = conn.execute("DELETE FROM agent_sections WHERE id=?", (section_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def assign_agent_section(agent_id: str, section_id: str) -> Any:
    from palimind.agents.registry import get_registry

    if section_id and get_section(section_id) is None:
        raise ValueError("section not found")
    return get_registry().update(agent_id, {"section_id": section_id or ""})
