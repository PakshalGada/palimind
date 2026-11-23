"""Saved searches and alerts inside a knowledge space.

A saved search stores a query and optional collection. When enabled, the
maintenance loop runs it periodically and records a normal `alert` source with
the top matches, so alerts are searchable and visible in the Sources library.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date
from pathlib import Path

from palimind.storage.db import get_connection, upsert_source

_COLUMNS = (
    "id",
    "name",
    "query",
    "collection",
    "alert",
    "last_checked",
    "last_count",
    "created_at",
    "updated_at",
)

CHECK_EVERY_SECONDS = 6 * 3600


def _row(row) -> dict:
    out = {name: row[index] for index, name in enumerate(_COLUMNS)}
    out["alert"] = bool(out.get("alert"))
    return out


def list_saved_searches(root: Path) -> list[dict]:
    conn = get_connection(Path(root))
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM saved_searches ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [_row(row) for row in rows]


def save_search(
    root: Path,
    *,
    name: str,
    query: str,
    collection: str = "",
    alert: bool = False,
    search_id: str = "",
) -> dict:
    name = (name or query or "Saved search").strip()[:120]
    query = (query or "").strip()
    if not query:
        raise ValueError("Search query is required.")
    search_id = search_id or uuid.uuid4().hex[:12]
    now = time.time()
    conn = get_connection(Path(root))
    try:
        conn.execute(
            f"""
            INSERT INTO saved_searches ({", ".join(_COLUMNS)})
            VALUES ({", ".join("?" * len(_COLUMNS))})
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, query=excluded.query,
                collection=excluded.collection, alert=excluded.alert,
                updated_at=excluded.updated_at
            """,
            (
                search_id,
                name,
                query,
                collection or "",
                1 if alert else 0,
                None,
                0,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM saved_searches WHERE id = ?",
            (search_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row(row)


def delete_search(root: Path, search_id: str) -> bool:
    conn = get_connection(Path(root))
    try:
        cur = conn.execute("DELETE FROM saved_searches WHERE id = ?", (search_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def run_search(root: Path, search_id: str, *, limit: int = 8) -> dict:
    from palimind import knowledge

    root = Path(root)
    conn = get_connection(root)
    try:
        row = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM saved_searches WHERE id = ?",
            (search_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"error": "Saved search not found"}
    search = _row(row)
    result = knowledge.search(
        root,
        str(search["query"]),
        limit=max(1, min(int(limit or 8), 30)),
        collection=str(search.get("collection") or ""),
    )
    hits = result.get("results") or []
    conn = get_connection(root)
    try:
        conn.execute(
            "UPDATE saved_searches SET last_checked = ?, last_count = ?, updated_at = ? "
            "WHERE id = ?",
            (time.time(), len(hits), time.time(), search_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"search": search, **result}


def _alert_source(root: Path, search: dict, hits: list[dict]) -> dict:
    today = date.today().isoformat()
    title = f"Alert: {search['name']} — {today}"
    lines = [f"# {title}", "", f"Query: `{search['query']}`", ""]
    for index, hit in enumerate(hits[:10], start=1):
        label = hit.get("title") or hit.get("file_path") or "Result"
        url = hit.get("url") or ""
        lines.append(f"{index}. [{label}]({url})" if url else f"{index}. {label}")
        if hit.get("content"):
            lines.append(f"   {str(hit['content'])[:240]}")
    text = "\n".join(lines)
    source_id = uuid.uuid4().hex[:12]
    rel = Path("sources") / "alerts" / f"{today}-{search['id']}-{source_id[:8]}.md"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    front = {
        "source_id": source_id,
        "source_type": "alert",
        "title": title,
        "query": search["query"],
        "created_at": time.time(),
    }
    content = ["---"]
    for key, value in front.items():
        content.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    content.extend(["---", "", text])
    target.write_text("\n".join(content), encoding="utf-8")
    conn = get_connection(root)
    try:
        return upsert_source(
            conn,
            {
                "id": source_id,
                "kind": "alert",
                "title": title,
                "file_path": str(rel),
                "status": "ready",
                "tags": json.dumps(["alert"]),
                "fetched_at": time.time(),
                "created_at": time.time(),
                "updated_at": time.time(),
                "note": f"Matched {len(hits)} result(s) for “{search['query']}”",
            },
        )
    finally:
        conn.close()


def run_due_searches() -> dict:
    from palimind import spaces

    created = failed = 0
    now = time.time()
    for space in spaces.list_spaces():
        root = Path(str(space.get("root") or ""))
        if not root.is_dir():
            continue
        space_created = 0
        for search in list_saved_searches(root):
            if not search.get("alert"):
                continue
            last = float(search.get("last_checked") or 0)
            if now - last < CHECK_EVERY_SECONDS:
                continue
            try:
                result = run_search(root, str(search["id"]), limit=8)
                hits = result.get("results") or []
                if hits:
                    _alert_source(root, search, hits)
                    created += 1
                    space_created += 1
            except Exception:  # noqa: BLE001 - one alert must not stop the loop
                failed += 1
        if space_created:
            try:
                from palimind import knowledge

                knowledge.run_index(root, wait=False)
            except Exception:  # noqa: BLE001
                pass
    return {"created": created, "failed": failed}
