from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def sqlite_query(query: str, params: list | None = None) -> str:
    """Run a read-only parameterized SQLite query against the field's
    index.db. Only SELECT statements are allowed and parameters are bound
    via '?' placeholders (never concatenated). Returns rows as a JSON
    list of dicts."""
    from palimind.llm.mixture_of_expert.tools import _get_context

    ctx = _get_context()
    root: Path | None = ctx.get("root")
    if root is None:
        return "Error: no active workspace configured for database queries."

    from palimind.config import db_path

    db = db_path(root)
    if not db.exists():
        return f"Error: index database not found at {db}"

    if not isinstance(query, str) or not query.strip():
        return "Error: query is required"

    stripped = query.strip().lstrip()
    if not stripped.upper().startswith("SELECT"):
        return "Error: only read-only SELECT queries are allowed"

    # Parameters are bound via placeholders only — reject any literal that
    # is not paired with a bound parameter (no string concatenation).
    placeholders = query.count("?")
    bound = params if isinstance(params, list) else []
    if placeholders != len(bound):
        return (
            f"Error: query has {placeholders} placeholders but {len(bound)} "
            "bound params — pass params separately."
        )

    import sqlite3

    try:
        conn = sqlite3.connect(str(db), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(query, tuple(bound))
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
        finally:
            conn.close()
    except sqlite3.Error as e:
        return f"Error running query: {e}"
    except Exception as e:
        return f"Error running query: {e}"

    if not rows:
        return "[]"
    return json.dumps(rows[:200], default=str, ensure_ascii=False)


# registry metadata for the main TOOL_REGISTRY
TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Run a read-only SELECT query against the field's index.db (SQLite). "
        "Parameterized via '?' placeholders only — pass query and params "
        "separately. Returns up to 200 rows as JSON."
    ),
    "parameters": {
        "query": "The SELECT SQL statement (use ? placeholders)",
        "params": "Optional: list of bound parameter values for the placeholders",
    },
    "tier": 1,
    "requires_approval": False,
}
