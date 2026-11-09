"""Local plugin catalog.

A plugin bundles one MCP app, its skills and listing text.  Installation is
explicit and idempotent; it never runs code from the catalog.
"""

from __future__ import annotations

import json
import time
from typing import Any

from palimind.agents import mcp, skills
from palimind.storage import state_store

NAMESPACE = "plugins"
CATALOG: list[dict[str, Any]] = [
    {
        "id": "filesystem",
        "name": "Filesystem tools",
        "description": "Read and search files through a local MCP filesystem server.",
        "mcp": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        },
        "skills": [],
    },
    {
        "id": "web-research-pack",
        "name": "Web research pack",
        "description": "A research skill bundle for the local marketplace.",
        "skills": [
            {
                "id": "plugin-web-research",
                "name": "Plugin web research",
                "description": "Search, read and cite sources.",
                "command": "/p-research",
                "tools": ["web_search", "fetch_url"],
                "instructions": "Search multiple independent sources and cite every claim.",
            }
        ],
    },
]


def list_plugins() -> list[dict[str, Any]]:
    installed = {
        item.get("plugin_id"): item for item in state_store.list_json(NAMESPACE, limit=500)
    }
    return [{**plugin, "installed": plugin["id"] in installed} for plugin in CATALOG]


def get_plugin(plugin_id: str) -> dict[str, Any] | None:
    return next((plugin for plugin in CATALOG if plugin["id"] == plugin_id), None)


def _record_key(plugin_id: str) -> str:
    return plugin_id


def install_plugin(
    plugin_id: str, *, agent_id: str = "", overwrite: bool = False
) -> dict[str, Any]:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise KeyError(f"unknown plugin: {plugin_id}")
    existing = state_store.get_json(NAMESPACE, _record_key(plugin_id), default=None)
    if existing and not overwrite:
        return existing
    installed_skills = []
    for skill in plugin.get("skills") or []:
        try:
            installed = skills.install_skill(skill, source="plugin", overwrite=overwrite)
            installed_skills.append(installed["id"])
        except ValueError:
            # A built-in with the same id is already available; that is fine.
            installed_skills.append(str(skill.get("id")))
    mcp_name = ""
    mcp_config = plugin.get("mcp")
    if isinstance(mcp_config, dict) and mcp_config.get("command"):
        path = mcp.config_path()
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        servers = data.get("servers") if isinstance(data.get("servers"), dict) else {}
        mcp_name = str(plugin_id)
        servers[mcp_name] = {
            "command": str(mcp_config.get("command")),
            "args": [str(a) for a in (mcp_config.get("args") or [])],
            "trusted": True,
            "enabled": True,
        }
        data["servers"] = servers
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), "utf-8")
    record = {
        "plugin_id": plugin_id,
        "agent_id": str(agent_id or ""),
        "skills": installed_skills,
        "mcp_name": mcp_name,
        "installed_at": time.time(),
    }
    state_store.set_json(NAMESPACE, _record_key(plugin_id), record)
    return record


def uninstall_plugin(plugin_id: str) -> bool:
    record = state_store.get_json(NAMESPACE, _record_key(plugin_id), default=None)
    if not isinstance(record, dict):
        return False
    for skill_id in record.get("skills") or []:
        try:
            skills.uninstall_skill(str(skill_id))
        except Exception:
            pass
    mcp_name = str(record.get("mcp_name") or "")
    if mcp_name:
        path = mcp.config_path()
        try:
            data = json.loads(path.read_text("utf-8"))
            servers = data.get("servers") if isinstance(data.get("servers"), dict) else {}
            servers.pop(mcp_name, None)
            data["servers"] = servers
            path.write_text(json.dumps(data, indent=2), "utf-8")
        except (OSError, json.JSONDecodeError):
            pass
    state_store.delete_json(NAMESPACE, _record_key(plugin_id))
    return True
