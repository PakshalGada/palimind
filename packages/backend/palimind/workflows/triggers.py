"""Workflow triggers: cron, file changes and webhooks."""

from __future__ import annotations

import fnmatch
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from palimind.workflows import runtime, store


def enqueue_due_cron(now: datetime | None = None) -> int:
    """Enqueue enabled cron workflows matching the current minute."""
    from palimind.jobs.cron import cron_matches

    moment = now or datetime.now()
    count = 0
    for workflow in store.list_workflows(limit=1000):
        if not workflow.get("enabled"):
            continue
        trigger = workflow.get("trigger") or {}
        if str(trigger.get("type") or "") != "cron":
            continue
        if not cron_matches(str(trigger.get("cron") or ""), moment):
            continue
        runtime.enqueue_workflow(
            str(workflow["id"]),
            input_text=f"[Scheduled workflow trigger at {moment.isoformat()}]",
            trigger={"type": "cron", "cron": trigger.get("cron")},
            idempotency_key=f"workflow:{workflow['id']}:{moment.strftime('%Y%m%d%H%M')}",
        )
        count += 1
    return count


def enqueue_file_triggers(root: Path, changed_path: str = "") -> int:
    """Enqueue enabled file-trigger workflows whose glob matches the change."""
    rel = changed_path
    try:
        rel = str(Path(changed_path).resolve().relative_to(Path(root).resolve()))
    except Exception:
        pass
    count = 0
    for workflow in store.list_workflows(limit=1000):
        if not workflow.get("enabled"):
            continue
        trigger = workflow.get("trigger") or {}
        if str(trigger.get("type") or "") != "file":
            continue
        pattern = str(trigger.get("pattern") or "")
        if not pattern:
            continue
        if not (fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(Path(rel).name, pattern)):
            continue
        runtime.enqueue_workflow(
            str(workflow["id"]),
            input_text=f"[File trigger] {rel}",
            trigger={"type": "file", "path": rel, "pattern": pattern},
            workspace_root=root,
            idempotency_key=f"workflow-file:{workflow['id']}:{rel}:{int(time.time())}",
        )
        count += 1
    return count


def enqueue_webhook(token: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Enqueue a workflow selected by its webhook token."""
    workflow = store.get_by_webhook_token(token)
    if workflow is None or not workflow.get("enabled"):
        return None
    payload = payload or {}
    input_text = str(payload.get("input") or payload.get("q") or "")
    return runtime.enqueue_workflow(
        str(workflow["id"]),
        input_text=input_text,
        trigger={"type": "webhook", "payload": payload},
        idempotency_key=f"workflow-hook:{workflow['id']}:{time.time_ns()}",
    )
