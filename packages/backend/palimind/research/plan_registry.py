"""Registry of research plans awaiting user review (Phase 3.1).

A deep-research run pauses after planning and emits a ``research_plan`` SSE
event. The user may edit the sub-topics and approve (or cancel) via the REST
endpoints, which resolve the corresponding :class:`PendingPlan`. This module
holds the in-flight plans; it is process-local and intentionally simple.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class PendingPlan:
    plan_id: str
    query: str
    plan: list[dict]
    event: asyncio.Event
    approved: bool = False
    cancelled: bool = False
    edited_plan: list[dict] | None = None
    created_at: float = field(default_factory=time.time)


_lock = threading.Lock()
_pending: dict[str, PendingPlan] = {}

# Plans older than this are considered abandoned.
_MAX_AGE_SECONDS = 30 * 60


def _prune_locked() -> None:
    cutoff = time.time() - _MAX_AGE_SECONDS
    stale = [pid for pid, p in _pending.items() if p.created_at < cutoff]
    for pid in stale:
        _pending.pop(pid, None)


def register_plan(query: str, plan: list[dict], event: asyncio.Event) -> PendingPlan:
    with _lock:
        _prune_locked()
        plan_id = uuid.uuid4().hex
        pending = PendingPlan(plan_id=plan_id, query=query, plan=plan, event=event)
        _pending[plan_id] = pending
        return pending


def get_pending_plan(plan_id: str) -> PendingPlan | None:
    with _lock:
        return _pending.get(plan_id)


def resolve_plan(
    plan_id: str,
    *,
    plan: list[dict] | None = None,
    cancelled: bool = False,
) -> bool:
    """Approve or cancel a pending plan and wake the waiting pipeline."""
    with _lock:
        pending = _pending.get(plan_id)
        if pending is None:
            return False
        pending.cancelled = cancelled
        if not cancelled:
            pending.approved = True
            pending.edited_plan = plan or pending.plan
        pending.event.set()
        return True


def discard_plan(plan_id: str) -> None:
    with _lock:
        _pending.pop(plan_id, None)
