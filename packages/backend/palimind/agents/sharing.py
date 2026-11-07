"""Agent import, export, transfer and link-only templates.

Secrets never enter an export: provider keys, MCP headers/env, agent API keys,
webhook tokens and account credentials are removed or blanked.  Import goes
through the same catalog service as manual creation.
"""

from __future__ import annotations

import json
import re
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from palimind.agents import memory, routines

FORMAT = "palimind-import"
VERSION = 1
MAX_ENTRIES = 50_000
MAX_BYTES = 2 * 1024 * 1024 * 1024

_SECRET_FIELDS = {"webhook_token", "api_key", "token", "password", "secret"}


def _safe_name(name: str) -> str:
    value = re.sub(r"[^\w.-]+", "-", str(name or "agent")).strip("-.")
    return value[:80] or "agent"


def _profile(defn: Any) -> dict[str, Any]:
    data = defn.to_dict()
    for key in list(data):
        if key in _SECRET_FIELDS or any(hint in key.lower() for hint in ("secret", "password", "token")):
            data.pop(key, None)
    data.pop("id", None)
    data.pop("created_at", None)
    data.pop("schema_version", None)
    return data


def export_agents(agent_ids: list[str], *, include_workspace: bool = False) -> dict[str, Any]:
    from palimind.agents.registry import get_registry

    registry = get_registry()
    agents = []
    for agent_id in agent_ids:
        defn = registry.get_by_id(agent_id)
        if defn is None:
            continue
        agents.append(
            {
                "key": defn.name,
                "profile": _profile(defn),
                "skills": list(defn.skills or []),
                "routines": [
                    r
                    for r in routines.list_routines(limit=1000)
                    if str(r.get("target_id") or "") == defn.id
                ],
                "memories": memory.read_memory(defn.id),
            }
        )
    return {
        "format": FORMAT,
        "version": VERSION,
        "created_at": time.time(),
        "agents": agents,
        "cleared": ["provider keys", "mcp headers/env", "agent api keys", "webhook tokens"],
        "include_workspace": bool(include_workspace),
    }


def import_agents(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise ValueError("not a PaliMind agent export")
    if int(payload.get("version") or 0) > VERSION:
        raise ValueError("export version is newer than this app")
    from palimind.agents.catalog import AgentDefinition
    from palimind.agents.registry import get_registry

    registry = get_registry()
    created = []
    warnings = []
    for item in payload.get("agents") or []:
        if not isinstance(item, dict):
            continue
        profile_value = item.get("profile")
        profile: dict[str, Any] = dict(profile_value) if isinstance(profile_value, dict) else {}
        name = str(profile.get("name") or item.get("key") or "agent")
        if registry.get(name) is not None:
            name = f"{name}-imported"
            suffix = 2
            while registry.get(name) is not None:
                name = f"{name}-{suffix}"
                suffix += 1
        profile["name"] = name
        profile["display_name"] = str(profile.get("display_name") or name)
        try:
            defn = AgentDefinition.from_dict(profile)
            saved = registry.create(defn)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{name}: {exc}")
            continue
        for entry in item.get("memories") or []:
            if not isinstance(entry, dict):
                continue
            try:
                memory.append_memory(
                    saved.id,
                    str(entry.get("type") or entry.get("entry_type") or "fact"),
                    str(entry.get("content") or ""),
                    confidence=float(entry.get("confidence") or 1.0),
                )
            except Exception:
                pass
        created.append({"id": saved.id, "name": saved.name})
    return {"created": created, "warnings": warnings}


def export_archive(path: str | Path, agent_ids: list[str], *, include_workspace: bool = False) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = export_agents(agent_ids, include_workspace=include_workspace)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("palimind-import.json", json.dumps(payload, indent=2))
        for item in payload["agents"]:
            key = _safe_name(str(item.get("key") or "agent"))
            archive.writestr(f"agents/{key}/profile.json", json.dumps(item["profile"], indent=2))
    return str(target)


def _safe_archive_path(name: str) -> bool:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    if any(part in (".env", "node_modules", ".git") for part in path.parts):
        return False
    return True


def import_archive(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if target.stat().st_size > MAX_BYTES:
        raise ValueError("archive is too large")
    with zipfile.ZipFile(target) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES:
            raise ValueError("archive has too many entries")
        for entry in entries:
            if not _safe_archive_path(entry.filename):
                raise ValueError(f"unsafe archive path: {entry.filename}")
        try:
            payload = json.loads(archive.read("palimind-import.json"))
        except KeyError as exc:
            raise ValueError("archive has no palimind-import.json") from exc
    return import_agents(payload)


def template_from_agent(agent_id: str) -> dict[str, Any]:
    from palimind.agents.registry import get_registry

    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        raise KeyError("agent not found")
    return {
        "format": "palimind-agent-template",
        "version": 1,
        "id": str(uuid.uuid4()),
        "name": defn.name,
        "display_name": defn.display_name,
        "title": defn.title,
        "description": defn.description,
        "system_prompt": defn.system_prompt,
        "custom_instructions": defn.custom_instructions,
        "avatar_type": defn.avatar_type,
        "avatar_config": dict(defn.avatar_config or {}),
        "provider": defn.provider,
        "model": defn.model,
        "reasoning_effort": defn.reasoning_effort,
        "skills": list(defn.skills or []),
        "routines": [
            r
            for r in routines.list_routines(limit=1000)
            if str(r.get("target_id") or "") == defn.id
        ],
    }


def install_template(template: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(template, dict) or template.get("format") != "palimind-agent-template":
        raise ValueError("not a PaliMind agent template")
    profile = {key: value for key, value in template.items() if key not in ("format", "version", "id", "routines")}
    return import_agents({"format": FORMAT, "version": VERSION, "agents": [{"profile": profile, "routines": template.get("routines") or []}]})
