"""File-backed store for Canvas documents (1.1).

Canvases are local-first: each document is a small JSON file under
``~/.palimind/canvases``. They are intentionally independent of the active
knowledge base so a canvas is always available, even with no workspace open.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

_ID_RE = re.compile(r"^[\w-]{1,64}$")


def canvases_dir() -> Path:
    return Path.home() / ".palimind" / "canvases"


def _canvas_file(canvas_id: str) -> Path:
    if not _ID_RE.match(canvas_id):
        raise ValueError(f"Invalid canvas_id: {canvas_id!r}")
    return canvases_dir() / f"{canvas_id}.json"


def list_canvases() -> list[dict]:
    directory = canvases_dir()
    if not directory.exists():
        return []
    items: list[dict] = []
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
        except Exception:
            continue
        items.append(
            {
                "id": data.get("id", path.stem),
                "title": data.get("title", "Untitled"),
                "updated_at": data.get("updated_at", 0),
                "created_at": data.get("created_at", 0),
            }
        )
    items.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
    return items


def load_canvas(canvas_id: str) -> dict | None:
    path = _canvas_file(canvas_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return None


def save_canvas(canvas_id: str, title: str, content: str) -> dict:
    path = _canvas_file(canvas_id)
    existing = load_canvas(canvas_id) or {}
    now = time.time()
    record = {
        "id": canvas_id,
        "title": title or existing.get("title") or "Untitled",
        "content": content,
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), "utf-8")
    return record


def delete_canvas(canvas_id: str) -> bool:
    path = _canvas_file(canvas_id)
    if path.exists():
        path.unlink()
        return True
    return False
