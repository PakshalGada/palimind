"""File-backed research project store (Phase 3.5).

Each project is a small JSON document under ``~/.palimind/research`` holding
notes, findings, a deduplicated source library, a timeline and saved reports.
Independent of any active knowledge base so research persists globally.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from palimind.research.sources import dedupe_sources, sources_from_collected

_ID_RE = re.compile(r"^[\w-]{1,64}$")


def projects_dir() -> Path:
    return Path.home() / ".palimind" / "research"


def _project_file(project_id: str) -> Path:
    if not _ID_RE.match(project_id):
        raise ValueError(f"Invalid project_id: {project_id!r}")
    return projects_dir() / f"{project_id}.json"


def _now() -> float:
    return time.time()


def _empty_project(title: str, query: str = "") -> dict:
    now = _now()
    return {
        "id": uuid.uuid4().hex,
        "title": title or "Untitled Research",
        "query": query,
        "created_at": now,
        "updated_at": now,
        "notes": "",
        "findings": [],
        "sources": [],
        "timeline": [],
        "reports": [],
    }


def list_projects() -> list[dict]:
    directory = projects_dir()
    if not directory.exists():
        return []
    out: list[dict] = []
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
        except Exception:
            continue
        out.append(
            {
                "id": data.get("id", path.stem),
                "title": data.get("title", "Untitled"),
                "query": data.get("query", ""),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "source_count": len(data.get("sources", [])),
                "finding_count": len(data.get("findings", [])),
            }
        )
    out.sort(key=lambda p: p.get("updated_at", 0), reverse=True)
    return out


def load_project(project_id: str) -> dict | None:
    path = _project_file(project_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return None


def save_project(project: dict) -> dict:
    path = _project_file(project["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    project["updated_at"] = _now()
    path.write_text(json.dumps(project, indent=2), "utf-8")
    return project


def create_project(title: str, query: str = "") -> dict:
    project = _empty_project(title, query)
    project["timeline"].append(
        {"at": _now(), "type": "created", "text": f"Project “{project['title']}” created"}
    )
    return save_project(project)


def delete_project(project_id: str) -> bool:
    path = _project_file(project_id)
    if path.exists():
        path.unlink()
        return True
    return False


def update_project(project_id: str, changes: dict) -> dict | None:
    project = load_project(project_id)
    if project is None:
        return None
    for key in ("title", "query", "notes"):
        if key in changes and isinstance(changes[key], str):
            project[key] = changes[key]
    return save_project(project)


def add_finding(project_id: str, title: str, content: str) -> dict | None:
    project = load_project(project_id)
    if project is None:
        return None
    finding = {
        "id": uuid.uuid4().hex,
        "title": title or "Finding",
        "content": content,
        "created_at": _now(),
    }
    project["findings"].append(finding)
    project["timeline"].append(
        {"at": _now(), "type": "finding", "text": f"Finding added: {finding['title']}"}
    )
    save_project(project)
    return finding


def add_sources(project_id: str, raw_sources: list[dict]) -> dict | None:
    project = load_project(project_id)
    if project is None:
        return None
    existing = sources_from_collected(project.get("sources", []))
    incoming = sources_from_collected(raw_sources)
    merged = dedupe_sources(existing + incoming)
    project["sources"] = [s.to_dict() for s in merged]
    added = len(merged) - len(existing)
    if added > 0:
        project["timeline"].append(
            {"at": _now(), "type": "sources", "text": f"{added} new source(s) added"}
        )
    save_project(project)
    return project


def add_report(project_id: str, query: str, report: str) -> dict | None:
    project = load_project(project_id)
    if project is None:
        return None
    project["reports"].append(
        {"id": uuid.uuid4().hex, "query": query, "report": report, "created_at": _now()}
    )
    project["timeline"].append({"at": _now(), "type": "report", "text": "Research report saved"})
    save_project(project)
    return project
