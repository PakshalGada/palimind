"""File-backed store for visual workflows (Phase 1).

Each workflow is a JSON document under ``~/.palimind/workflows``. Workflows are
local-first and independent of the active knowledge base so a saved pipeline is
always available, even with no workspace open. The record mirrors the frontend
model: ``id``, ``name``, ``description``, ``nodes``, ``edges``, timestamps and
``status``.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

_ID_RE = re.compile(r"^[\w-]{1,64}$")


def workflows_dir() -> Path:
    return Path.home() / ".palimind" / "workflows"


def _workflow_file(workflow_id: str) -> Path:
    if not _ID_RE.match(str(workflow_id)):
        raise ValueError(f"Invalid workflow_id: {workflow_id!r}")
    return workflows_dir() / f"{workflow_id}.json"


def _normalize(record: dict) -> dict:
    now = time.time()
    workflow_id = str(record.get("id") or "").strip()
    if not workflow_id:
        raise ValueError("workflow id is required")
    return {
        "id": workflow_id,
        "name": str(record.get("name") or "Untitled Workflow"),
        "description": str(record.get("description") or ""),
        "nodes": record.get("nodes") or [],
        "edges": record.get("edges") or [],
        "created_at": record.get("created_at") or now,
        "updated_at": now,
        "status": record.get("status") or "draft",
        "version": int(record.get("version") or 1),
        "last_execution": record.get("last_execution"),
    }


def list_workflows() -> list[dict]:
    directory = workflows_dir()
    if not directory.exists():
        return []
    items: list[dict] = []
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            items.append(data)
    items.sort(key=lambda w: w.get("updated_at", 0), reverse=True)
    return items


def load_workflow(workflow_id: str) -> dict | None:
    path = _workflow_file(workflow_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_workflow(record: dict) -> dict:
    workflow_id = str(record.get("id") or "").strip()
    path = _workflow_file(workflow_id)
    existing = load_workflow(workflow_id) or {}
    merged = {**existing, **record}
    normalized = _normalize(merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2), "utf-8")
    return normalized


def delete_workflow(workflow_id: str) -> bool:
    path = _workflow_file(workflow_id)
    if path.exists():
        path.unlink()
        return True
    return False
