"""Research package (Phase 3.5 foundation + 3.1 plan review)."""

from palimind.research.plan_registry import (
    PendingPlan,
    discard_plan,
    get_pending_plan,
    register_plan,
    resolve_plan,
)
from palimind.research.project_store import (
    add_finding,
    add_report,
    add_sources,
    create_project,
    delete_project,
    list_projects,
    load_project,
    save_project,
    update_project,
)
from palimind.research.sources import (
    dedupe_sources,
    score_source,
    score_sources,
    sources_from_collected,
)

__all__ = [
    "PendingPlan",
    "discard_plan",
    "get_pending_plan",
    "register_plan",
    "resolve_plan",
    "add_finding",
    "add_report",
    "add_sources",
    "create_project",
    "delete_project",
    "list_projects",
    "load_project",
    "save_project",
    "update_project",
    "dedupe_sources",
    "score_source",
    "score_sources",
    "sources_from_collected",
]
