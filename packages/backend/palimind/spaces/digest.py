"""Daily digests for a knowledge space.

A digest is a normal Markdown source (kind ``digest``) so it appears in the
library, is searchable, and can be exported with the rest of the vault. It is
generated from activity in the space and is opt-in per space.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from palimind.storage.db import (
    SOURCE_COLUMNS,
    get_connection,
    upsert_source,
)

DIGEST_KIND = "digest"


def _rows(root: Path, sql: str, params: tuple = ()) -> list[dict]:
    conn = get_connection(root)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [{name: row[index] for index, name in enumerate(SOURCE_COLUMNS)} for row in rows]


def _top_entities(root: Path, limit: int = 8) -> list[dict]:
    conn = get_connection(root)
    try:
        rows = conn.execute(
            """
            SELECT em.entity_text, COUNT(*) AS mentions
            FROM entity_mentions em
            GROUP BY em.entity_text
            ORDER BY mentions DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                """
                SELECT entity_name, COUNT(*) FROM files
                WHERE COALESCE(entity_name, '') <> ''
                GROUP BY entity_name ORDER BY COUNT(*) DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except Exception:  # noqa: BLE001 - graph/entity tables are optional
        rows = []
    finally:
        conn.close()
    return [{"name": row[0], "mentions": int(row[1] or 0)} for row in rows if row[0]]


def build_digest(root: Path, *, days: int = 1) -> dict[str, Any]:
    root = Path(root)
    days = max(1, min(int(days or 1), 30))
    since = time.time() - days * 86400
    fresh = _rows(
        root,
        f"SELECT {', '.join(SOURCE_COLUMNS)} FROM sources "
        "WHERE kind <> ? AND COALESCE(fetched_at, created_at, 0) >= ? "
        "ORDER BY COALESCE(fetched_at, created_at, 0) DESC LIMIT 40",
        (DIGEST_KIND, since),
    )
    changed = [
        row for row in fresh if str(row.get("change_summary") or "").strip()
    ]
    attention = [
        row
        for row in fresh
        if str(row.get("status") or "") in ("failed", "blocked")
    ]
    entities = _top_entities(root)
    contradictions: list[dict] = []
    try:
        from palimind.spaces import analysis

        contradictions = analysis.contradiction_candidates(root, limit=5)
    except Exception:  # noqa: BLE001 - digest must still build
        contradictions = []

    today = date.today().isoformat()
    lines = [f"# Daily digest — {today}", ""]
    lines.append(
        f"{len(fresh)} new or updated source(s) in the last {days} day"
        f"{'s' if days != 1 else ''}."
    )
    if fresh:
        lines.extend(["", "## Saved", ""])
        for row in fresh[:20]:
            title = row.get("title") or row.get("url") or row.get("file_path") or "Source"
            site = row.get("site") or ""
            suffix = f" — {site}" if site else ""
            url = row.get("url") or ""
            lines.append(f"- [{title}]({url}){suffix}" if url else f"- {title}{suffix}")
    if changed:
        lines.extend(["", "## Changed", ""])
        for row in changed[:10]:
            title = row.get("title") or row.get("url") or "Source"
            lines.append(f"- {title}: {row.get('change_summary')}")
    if attention:
        lines.extend(["", "## Needs attention", ""])
        for row in attention[:10]:
            title = row.get("title") or row.get("url") or "Source"
            lines.append(f"- {title}: {row.get('error') or row.get('status')}")
    if entities:
        lines.extend(["", "## Top entities", ""])
        lines.append(", ".join(f"{item['name']} ({item['mentions']})" for item in entities))
    if contradictions:
        lines.extend(["", "## Possible contradictions", ""])
        for item in contradictions:
            lines.append(
                f"- **{item.get('entity') or 'Claim'}**: "
                f"{item.get('a', {}).get('file_path', '')} vs "
                f"{item.get('b', {}).get('file_path', '')} — {item.get('reason', '')}"
            )
    lines.append("")
    return {
        "title": f"Daily digest {today}",
        "date": today,
        "days": days,
        "text": "\n".join(lines),
        "source_count": len(fresh),
        "changed_count": len(changed),
        "attention_count": len(attention),
        "contradictions": contradictions,
    }


def find_digest(root: Path, day: str) -> dict | None:
    conn = get_connection(root)
    try:
        row = conn.execute(
            f"SELECT {', '.join(SOURCE_COLUMNS)} FROM sources "
            "WHERE kind = ? AND title = ? LIMIT 1",
            (DIGEST_KIND, f"Daily digest {day}"),
        ).fetchone()
    finally:
        conn.close()
    return (
        {name: row[index] for index, name in enumerate(SOURCE_COLUMNS)}
        if row is not None
        else None
    )


def create_digest(root: Path, *, days: int = 1, force: bool = False) -> dict:
    root = Path(root)
    payload = build_digest(root, days=days)
    existing = find_digest(root, payload["date"])
    if existing is not None and not force:
        return {"status": "exists", "source": existing, "digest": payload}

    from palimind.spaces import policy

    try:
        policy.check_quota(root, len(payload["text"].encode("utf-8")))
    except policy.PolicyError as exc:
        return {"status": "error", "error": str(exc), "digest": payload}
    source_id = uuid.uuid4().hex[:12]
    rel = Path("sources") / "digests" / f"{payload['date']}-{source_id[:8]}.md"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    front = {
        "source_id": source_id,
        "source_type": "digest",
        "title": payload["title"],
        "created_at": time.time(),
    }
    lines = ["---"]
    for key, value in front.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.extend(["---", "", payload["text"]])
    target.write_text("\n".join(lines), encoding="utf-8")

    conn = get_connection(root)
    try:
        saved = upsert_source(
            conn,
            {
                "id": source_id,
                "kind": DIGEST_KIND,
                "title": payload["title"],
                "file_path": str(rel),
                "status": "ready",
                "fetched_at": time.time(),
                "created_at": time.time(),
                "updated_at": time.time(),
                "note": (
                    f"{payload['source_count']} saved, "
                    f"{payload['changed_count']} changed, "
                    f"{payload['attention_count']} need attention"
                ),
            },
        )
    finally:
        conn.close()
    try:
        from palimind.spaces import sources as sources_mod

        saved = sources_mod.index_source(root, source_id)
    except Exception:  # noqa: BLE001 - digest remains readable on disk
        pass
    return {"status": "created", "source": saved, "digest": payload}


def list_digests(root: Path, limit: int = 30) -> list[dict]:
    return _rows(
        Path(root),
        f"SELECT {', '.join(SOURCE_COLUMNS)} FROM sources "
        "WHERE kind = ? ORDER BY COALESCE(created_at, 0) DESC LIMIT ?",
        (DIGEST_KIND, max(1, min(int(limit or 30), 200))),
    )


def due_spaces() -> list[dict]:
    from palimind import spaces

    today = date.today().isoformat()
    due = []
    for space in spaces.list_spaces():
        if not space.get("digest_enabled"):
            continue
        root = Path(str(space.get("root") or ""))
        if not root.is_dir():
            continue
        if find_digest(root, today) is None:
            due.append(space)
    return due


def run_due_digests() -> dict:
    created = failed = 0
    for space in due_spaces():
        try:
            result = create_digest(Path(str(space["root"])))
            if result.get("status") == "created":
                created += 1
        except Exception:  # noqa: BLE001 - one space must not stop the loop
            failed += 1
    return {"created": created, "failed": failed}
