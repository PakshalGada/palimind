"""Agent tools for API keys stored outside the workspace."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from palimind.security.tokens import palimind_home

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _ctx() -> dict[str, Any]:
    from palimind.llm.mixture_of_expert.tools import _get_context

    return _get_context()


def _folder(agent_id: str = "") -> Path:
    caller = agent_id or str(_ctx().get("agent_id") or "")
    return palimind_home() / "agent-api-keys" / caller


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def request_api_key(name: str, description: str = "") -> str:
    name = str(name or "").strip()
    if not _NAME_RE.match(name):
        return "Error: key name must be letters, digits or underscore"
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass
    path = folder / name
    if not path.exists():
        path.write_text("", "utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return _json(
        {
            "requires_user_input": True,
            "name": name,
            "description": str(description or ""),
            "path": str(path),
            "message": "Ask the user for the value and store it at this path.",
        }
    )


def list_api_keys() -> str:
    folder = _folder()
    if not folder.is_dir():
        return _json({"keys": []})
    return _json(
        {
            "keys": [
                {
                    "name": item.name,
                    "path": str(item),
                    "configured": bool(item.read_text("utf-8").strip()) if item.is_file() else False,
                    "updated_at": item.stat().st_mtime if item.is_file() else 0,
                }
                for item in sorted(folder.iterdir())
                if item.is_file()
            ]
        }
    )


def remove_api_key(name: str) -> str:
    path = _folder() / str(name or "")
    if not path.is_file():
        return "Error: key not found"
    try:
        path.unlink()
        return _json({"removed": str(name)})
    except OSError as exc:
        return f"Error: {exc}"


TOOLS: dict[str, dict[str, Any]] = {
    "request_api_key": {
        "fn": request_api_key,
        "description": "Ask for an API key and return its private file path; never return the value.",
        "parameters": {
            "name": {"type": "string"},
            "description": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "list_api_keys": {
        "fn": list_api_keys,
        "description": "List this agent's API key names and whether each is configured.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
    },
    "remove_api_key": {
        "fn": remove_api_key,
        "description": "Delete one of this agent's API key files.",
        "parameters": {"name": {"type": "string"}},
        "tier": 2,
        "requires_approval": True,
    },
}
