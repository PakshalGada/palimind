"""Tests for the local MCP stdio client and tool registration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from palimind.agents import mcp

SERVER_SOURCE = r"""
import json
import sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method = msg.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo text back",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "danger",
                    "description": "A destructive tool",
                    "inputSchema": {"type": "object", "properties": {}},
                    "annotations": {"readOnlyHint": False, "destructiveHint": True},
                },
            ]
        }
    elif method == "tools/call":
        args = msg.get("params", {}).get("arguments", {})
        result = {
            "content": [{"type": "text", "text": "echo:" + str(args.get("text", ""))}],
            "isError": False,
        }
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
"""


@pytest.fixture()
def fake_server(tmp_path: Path) -> mcp.MCPServerConfig:
    script = tmp_path / "server.py"
    script.write_text(SERVER_SOURCE, encoding="utf-8")
    return mcp.MCPServerConfig(
        name="fake",
        command=sys.executable,
        args=[str(script)],
        trusted=True,
        timeout_s=10,
    )


def test_config_load_and_trust(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    "yes": {"command": "echo", "trusted": True},
                    "no": {"command": "echo", "trusted": False},
                }
            }
        ),
        encoding="utf-8",
    )
    configs = mcp.load_config(path)
    assert set(configs) == {"yes", "no"}
    assert configs["yes"].trusted and not configs["no"].trusted


def test_client_initialize_list_and_call(fake_server: mcp.MCPServerConfig) -> None:
    client = mcp.MCPClient(fake_server)
    try:
        info = client.initialize()
        assert info["serverInfo"]["name"] == "fake"
        tools = client.list_tools()
        assert {t["name"] for t in tools} == {"echo", "danger"}
        assert client.call_tool("echo", {"text": "hi"}) == "echo:hi"
    finally:
        client.close()


def test_manager_registers_typed_tools(fake_server: mcp.MCPServerConfig) -> None:
    manager = mcp.MCPManager({"fake": fake_server})
    registry: dict = {}
    try:
        added = manager.register_into(registry)
        assert added == 2
        name = "mcp__fake__echo"
        assert name in registry
        entry = registry[name]
        assert entry["source"] == "mcp:fake"
        assert entry["meta"]["tier"] == 1
        assert entry["meta"]["requires_approval"] is False
        assert entry["parallel_safe"] is True
        assert entry["parameters"]["required"] == ["text"]
        assert entry["fn"](text="hi") == "echo:hi"

        danger = registry["mcp__fake__danger"]
        assert danger["meta"]["tier"] == 2
        assert danger["meta"]["requires_approval"] is True
        assert danger["parallel_safe"] is False
    finally:
        manager.close()


def test_untrusted_servers_are_not_started(fake_server: mcp.MCPServerConfig) -> None:
    fake_server.trusted = False
    manager = mcp.MCPManager({"fake": fake_server})
    try:
        assert manager.discover() == {}
        assert manager.tool_specs() == []
        assert manager.register_into({}) == 0
    finally:
        manager.close()
