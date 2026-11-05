"""Minimal Model Context Protocol (MCP) client for local tools.

MCP lets PaliMind use the local tool ecosystem (filesystem, git, sqlite,
browser, …) without adding a bespoke adapter for every server. Servers are
declared in ``~/.palimind/mcp.json`` and must be explicitly trusted:

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/me/docs"],
      "trusted": true
    }
  }
}
```

This client implements the stdio transport (newline-delimited JSON-RPC 2.0):
``initialize`` -> ``notifications/initialized`` -> ``tools/list`` ->
``tools/call``. HTTP/SSE transports can be layered on later; stdio covers the
vast majority of local servers and needs no extra dependency.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = Path.home() / ".palimind" / "mcp.json"
PROTOCOL_VERSION = "2024-11-05"
_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")

# Environment variables that must not leak to a third-party MCP server unless
# the server config explicitly sets them.
_SECRET_HINTS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY")


def config_path() -> Path:
    override = os.environ.get("PALIMIND_MCP_CONFIG", "").strip()
    return Path(override).expanduser() if override else DEFAULT_CONFIG


def _safe_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        str(k): str(v)
        for k, v in os.environ.items()
        if not any(hint in str(k).upper() for hint in _SECRET_HINTS)
    }
    for key, value in (extra or {}).items():
        env[str(key)] = str(value)
    return env


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    trusted: bool = False
    enabled: bool = True
    timeout_s: float = 30.0

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> MCPServerConfig:
        return cls(
            name=str(name),
            command=str(data.get("command") or ""),
            args=[str(a) for a in (data.get("args") or [])],
            env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
            cwd=str(data.get("cwd") or ""),
            trusted=bool(data.get("trusted", False)),
            enabled=bool(data.get("enabled", True)),
            timeout_s=float(data.get("timeout_s") or 30.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "cwd": self.cwd,
            "trusted": self.trusted,
            "enabled": self.enabled,
            "timeout_s": self.timeout_s,
        }


def load_config(path: Path | None = None) -> dict[str, MCPServerConfig]:
    """Load server configs; malformed entries are skipped, never fatal."""
    target = path or config_path()
    try:
        data = json.loads(target.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    servers = data.get("servers")
    items: Any
    if isinstance(servers, dict):
        items = servers.items()
    else:
        # Also accept a top-level mapping of server name -> config.
        items = ((k, v) for k, v in data.items() if isinstance(v, dict))
    out: dict[str, MCPServerConfig] = {}
    for name, raw in items:
        if not isinstance(raw, dict):
            continue
        cfg = MCPServerConfig.from_dict(str(name), raw)
        if cfg.command:
            out[cfg.name] = cfg
    return out


class MCPError(RuntimeError):
    pass


class MCPClient:
    """One stdio MCP server process."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.process: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.Lock()
        self._next_id = 0
        self._stderr: list[str] = []
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self.tools: list[dict[str, Any]] = []

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return
            cmd = [self.config.command, *self.config.args]
            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    cwd=self.config.cwd or None,
                    env=_safe_env(self.config.env),
                )
            except OSError as exc:
                raise MCPError(f"could not start MCP server '{self.config.name}': {exc}") from exc
            self._queue = queue.Queue()
            self._reader = threading.Thread(
                target=self._read_stdout,
                name=f"mcp-{self.config.name}-stdout",
                daemon=True,
            )
            self._reader.start()
            self._stderr_reader = threading.Thread(
                target=self._read_stderr,
                name=f"mcp-{self.config.name}-stderr",
                daemon=True,
            )
            self._stderr_reader.start()

    def close(self) -> None:
        with self._lock:
            proc = self.process
            self.process = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _read_stdout(self) -> None:
        proc = self.process
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Ignoring non-JSON MCP output from %s", self.config.name)
                continue
            if isinstance(message, dict):
                self._queue.put(message)

    def _read_stderr(self) -> None:
        proc = self.process
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            self._stderr.append(line.rstrip()[:500])
            del self._stderr[:-50]

    def _send(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MCPError(f"MCP server '{self.config.name}' is not running")
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPError(f"MCP server '{self.config.name}' pipe closed: {exc}") from exc

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.start()
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            deadline = time.monotonic() + float(self.config.timeout_s or 30.0)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPError(f"MCP '{self.config.name}' timed out on {method}")
                try:
                    message = self._queue.get(timeout=remaining)
                except queue.Empty as exc:
                    raise MCPError(f"MCP '{self.config.name}' timed out on {method}") from exc
                if message.get("id") != request_id:
                    # Notification or a stale response: ignore and keep waiting.
                    continue
                if "error" in message:
                    error = message["error"]
                    detail = error.get("message") if isinstance(error, dict) else str(error)
                    raise MCPError(f"MCP '{self.config.name}' {method}: {detail}")
                return message.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.start()
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "palimind", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized")
        return result if isinstance(result, dict) else {}

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list")
        tools = result.get("tools") if isinstance(result, dict) else []
        if not isinstance(tools, list):
            return []
        self.tools = [t for t in tools if isinstance(t, dict) and t.get("name")]
        return self.tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        try:
            result = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        except MCPError as exc:
            return f"Error: {exc}"
        if not isinstance(result, dict):
            return ""
        parts: list[str] = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        text = "\n".join(parts)
        if result.get("isError"):
            return f"Error: {text or 'MCP tool failed'}"
        return text

    def status(self) -> dict[str, Any]:
        running = self.process is not None and self.process.poll() is None
        return {
            **self.config.to_dict(),
            "running": running,
            "tools": len(self.tools),
            "stderr": list(self._stderr[-10:]),
        }


class MCPManager:
    """Owns configured MCP clients and merges their tools into a registry."""

    def __init__(self, configs: dict[str, MCPServerConfig] | None = None) -> None:
        self.configs = configs or {}
        self.clients: dict[str, MCPClient] = {}
        self._loaded = False
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, path: Path | None = None) -> MCPManager:
        return cls(load_config(path))

    def _enabled_configs(self) -> list[MCPServerConfig]:
        return [cfg for cfg in self.configs.values() if cfg.enabled and cfg.trusted and cfg.command]

    def discover(self) -> dict[str, list[dict[str, Any]]]:
        """Start trusted servers and return ``server -> tools``."""
        with self._lock:
            discovered: dict[str, list[dict[str, Any]]] = {}
            for cfg in self._enabled_configs():
                client = self.clients.get(cfg.name)
                if client is None:
                    client = MCPClient(cfg)
                    self.clients[cfg.name] = client
                try:
                    client.initialize()
                    discovered[cfg.name] = client.list_tools()
                except Exception as exc:  # noqa: BLE001 - one server must not kill all
                    logger.warning("MCP server %s unavailable: %s", cfg.name, exc)
                    discovered[cfg.name] = []
            self._loaded = True
            return discovered

    def tool_specs(self) -> list[dict[str, Any]]:
        if not self._loaded:
            self.discover()
        specs: list[dict[str, Any]] = []
        for name, client in self.clients.items():
            for tool in client.tools:
                tool_name = str(tool.get("name") or "")
                if not tool_name:
                    continue
                safe_server = _NAME_RE.sub("_", name).strip("_")
                safe_tool = _NAME_RE.sub("_", tool_name).strip("_")
                public_name = f"mcp__{safe_server}__{safe_tool}"
                annotations = tool.get("annotations") or {}
                read_only = (
                    bool(annotations.get("readOnlyHint"))
                    if isinstance(annotations, dict)
                    else False
                )
                destructive = (
                    bool(annotations.get("destructiveHint"))
                    if isinstance(annotations, dict)
                    else False
                )
                specs.append(
                    {
                        "name": public_name,
                        "server": name,
                        "tool": tool_name,
                        "description": str(tool.get("description") or f"MCP tool {tool_name}"),
                        "input_schema": tool.get("inputSchema") or {"type": "object"},
                        "tier": 1 if read_only and not destructive else 2,
                        "requires_approval": not (read_only and not destructive),
                        "parallel_safe": read_only and not destructive,
                        "idempotent": read_only and not destructive,
                    }
                )
        return specs

    def register_into(self, registry: dict[str, dict[str, Any]]) -> int:
        """Merge MCP tools into a live ``TOOL_REGISTRY``; return the count added."""
        added = 0
        for spec in self.tool_specs():
            name = spec["name"]
            if name in registry:
                continue
            client = self.clients.get(spec["server"])
            if client is None:
                continue
            tool_name = spec["tool"]
            registry[name] = {
                "fn": (lambda _c=client, _t=tool_name, **kwargs: _c.call_tool(_t, kwargs)),
                "description": spec["description"],
                "parameters": spec["input_schema"],
                "meta": {
                    "tier": int(spec["tier"]),
                    "requires_approval": bool(spec["requires_approval"]),
                },
                "timeout_s": int(client.config.timeout_s or 30),
                "parallel_safe": bool(spec["parallel_safe"]),
                "idempotent": bool(spec["idempotent"]),
                "source": f"mcp:{spec['server']}",
            }
            added += 1
        return added

    def status(self) -> list[dict[str, Any]]:
        if not self._loaded:
            return [cfg.to_dict() for cfg in self.configs.values()]
        return [client.status() for client in self.clients.values()]

    def close(self) -> None:
        for client in self.clients.values():
            client.close()
        self.clients.clear()
        self._loaded = False


_manager: MCPManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> MCPManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = MCPManager.from_config()
        return _manager


def reload_manager() -> MCPManager:
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.close()
        _manager = MCPManager.from_config()
        return _manager
