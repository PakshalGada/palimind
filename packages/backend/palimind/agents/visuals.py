"""Sandboxed visual replies.

An HTML reply is stored as a local artifact and served with a sandbox CSP.  The
page gets an opaque origin and cannot read PaliMind state.  A per-visual token
keeps the route from being guessed.
"""

from __future__ import annotations

import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from palimind.security.tokens import palimind_home


def visual_root() -> Path:
    return palimind_home() / "visuals"


def create_visual(
    html: str,
    *,
    title: str = "",
    height: int = 600,
    agent_id: str = "",
    message: str = "",
) -> dict[str, Any]:
    visual_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(24)
    folder = visual_root() / visual_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(str(html or ""), "utf-8")
    record = {
        "id": visual_id,
        "token": token,
        "title": str(title or "Visual reply")[:200],
        "height": max(80, min(int(height or 600), 4000)),
        "agent_id": str(agent_id or ""),
        "message": str(message or "")[:4000],
        "created_at": time.time(),
        "url": f"/api/visuals/{visual_id}?token={token}",
    }
    (folder / "meta.json").write_text(json.dumps(record, indent=2), "utf-8")
    return record


def get_visual(visual_id: str) -> dict[str, Any] | None:
    folder = visual_root() / str(visual_id or "")
    try:
        record = json.loads((folder / "meta.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def read_visual(visual_id: str, token: str) -> str | None:
    record = get_visual(visual_id)
    if record is None or not secrets.compare_digest(str(record.get("token") or ""), str(token or "")):
        return None
    try:
        return (visual_root() / visual_id / "index.html").read_text("utf-8")
    except OSError:
        return None


def list_visuals(agent_id: str = "") -> list[dict[str, Any]]:
    root = visual_root()
    if not root.is_dir():
        return []
    out = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        record = get_visual(folder.name)
        if record is None:
            continue
        if agent_id and str(record.get("agent_id") or "") != agent_id:
            continue
        out.append(record)
    return out
