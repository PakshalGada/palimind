"""Agent tools to manage local MCP servers.

Changes are host-global, so every mutating call is approval-gated.  Secrets in
headers/environment are never returned; list output shows only the command and
whether values are configured.
"""

from __future__ import annotations

import json
from typing import Any

from palimind.agents import mcp


def _read() -> dict[str, Any]:
    path = mcp.config_path()
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("servers"), dict):
        data["servers"] = {}
    return data


def _write(data: dict[str, Any]) -> None:
    path = mcp.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), "utf-8")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def list_mcp_servers() -> str:
    configs = mcp.load_config()
    return _json(
        {
            "servers": [
                {
                    "name": cfg.name,
                    "transport": "stdio",
                    "command": cfg.command,
                    "enabled": cfg.enabled,
                    "trusted": cfg.trusted,
                    "has_env": bool(cfg.env),
                    "args_count": len(cfg.args),
                }
                for cfg in configs.values()
            ]
        }
    )


def save_mcp_server(
    name: str,
    command: str = "",
    args: str = "",
    env: str = "",
    enabled: bool = True,
    trusted: bool = True,
) -> str:
    name = str(name or "").strip()
    if not name:
        return "Error: name is required"
    data = _read()
    servers = data["servers"]
    existing = servers.get(name) if isinstance(servers.get(name), dict) else {}
    try:
        arg_list = json.loads(args) if str(args or "").strip() else list(existing.get("args") or [])
        env_map = json.loads(env) if str(env or "").strip() else dict(existing.get("env") or {})
    except json.JSONDecodeError:
        return "Error: args and env must be JSON"
    if not isinstance(arg_list, list) or not isinstance(env_map, dict):
        return "Error: args must be a JSON list and env a JSON object"
    command = str(command or existing.get("command") or "")
    if not command:
        return "Error: command is required for a stdio server"
    servers[name] = {
        **existing,
        "command": command,
        "args": [str(a) for a in arg_list],
        "env": {str(k): str(v) for k, v in env_map.items()},
        "enabled": bool(enabled),
        "trusted": bool(trusted),
    }
    _write(data)
    return _json({"saved": name, "enabled": bool(enabled), "trusted": bool(trusted)})


def test_mcp_server(name: str) -> str:
    cfg = mcp.load_config().get(str(name or ""))
    if cfg is None:
        return "Error: server not found"
    client = mcp.MCPClient(cfg)
    try:
        client.start()
        client.initialize()
        tools = client.list_tools()
        return _json({"name": name, "tools": [t.get("name") for t in tools]})
    except Exception as exc:  # noqa: BLE001
        return f"Error: MCP server test failed: {exc}"
    finally:
        try:
            client.close()
        except Exception:
            pass


def set_mcp_server_enabled(name: str, enabled: bool) -> str:
    data = _read()
    server = data["servers"].get(str(name or ""))
    if not isinstance(server, dict):
        return "Error: server not found"
    server["enabled"] = bool(enabled)
    _write(data)
    return _json({"name": name, "enabled": bool(enabled)})


def remove_mcp_server(name: str) -> str:
    data = _read()
    if str(name or "") not in data["servers"]:
        return "Error: server not found"
    data["servers"].pop(str(name), None)
    _write(data)
    return _json({"removed": str(name)})


TOOLS: dict[str, dict[str, Any]] = {
    "list_mcp_servers": {
        "fn": list_mcp_servers,
        "description": "List local MCP servers without exposing secrets.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
    },
    "save_mcp_server": {
        "fn": save_mcp_server,
        "description": "Add or update a local stdio MCP server (host-global).",
        "parameters": {
            "name": {"type": "string"},
            "command": {"type": "string", "required": False},
            "args": {"type": "string", "description": "JSON list.", "required": False},
            "env": {"type": "string", "description": "JSON object.", "required": False},
            "enabled": {"type": "boolean", "required": False},
            "trusted": {"type": "boolean", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "test_mcp_server": {
        "fn": test_mcp_server,
        "description": "Start an MCP server, initialize it and list its tools.",
        "parameters": {"name": {"type": "string"}},
        "tier": 1,
        "requires_approval": False,
    },
    "set_mcp_server_enabled": {
        "fn": set_mcp_server_enabled,
        "description": "Turn a local MCP server on or off.",
        "parameters": {"name": {"type": "string"}, "enabled": {"type": "boolean"}},
        "tier": 2,
        "requires_approval": True,
    },
    "remove_mcp_server": {
        "fn": remove_mcp_server,
        "description": "Remove a local MCP server configuration.",
        "parameters": {"name": {"type": "string"}},
        "tier": 2,
        "requires_approval": True,
    },
}
