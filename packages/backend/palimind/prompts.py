"""Reusable prompt templates with fill-in variables.

Stored user-globally in ``~/.palimind_prompts.json`` next to the global
config: prompts are a personal asset, not per-workspace state. Each prompt
has a unique slash command name; ``{variables}`` in the template are filled
in by the composer before sending.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

PROMPTS_PATH = Path.home() / ".palimind_prompts.json"

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


def _read() -> list[dict[str, Any]]:
    try:
        data = json.loads(PROMPTS_PATH.read_text("utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        return []
    prompts = data.get("prompts", [])
    return prompts if isinstance(prompts, list) else []


def _write(prompts: list[dict[str, Any]]) -> None:
    PROMPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROMPTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"prompts": prompts}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(PROMPTS_PATH)


def normalize_command(name: str) -> str:
    """Turn free text into a slash command slug (``/paper-summary``)."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(name or "").strip().lower()).strip("-")
    return slug[:32]


def _clean(prompt: dict[str, Any]) -> dict[str, Any] | None:
    name = str(prompt.get("name") or "").strip()
    template = str(prompt.get("template") or "").strip()
    command = normalize_command(prompt.get("command") or name)
    if not name or not template or not command:
        return None
    cleaned: dict[str, Any] = {
        "id": str(prompt.get("id") or uuid_key()),
        "name": name,
        "command": command,
        "template": template,
        "created_at": float(prompt.get("created_at") or time.time()),
    }
    description = str(prompt.get("description") or "").strip()
    if description:
        cleaned["description"] = description
    return cleaned


def uuid_key() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


def list_prompts() -> list[dict[str, Any]]:
    """All saved prompts, ordered by creation time."""
    prompts = [p for p in (_clean(raw) for raw in _read()) if p]
    prompts.sort(key=lambda item: item["created_at"])
    # De-duplicate commands (last wins) so the list can never collide.
    by_command: dict[str, dict[str, Any]] = {}
    for prompt in prompts:
        by_command[prompt["command"]] = prompt
    return sorted(by_command.values(), key=lambda item: item["created_at"])


def validate_command(command: str, prompt_id: str | None = None) -> str | None:
    """Error string when a command name cannot be used, else None."""
    if not _NAME_RE.match(command or ""):
        return "command must be letters, digits, '-' or '_' (max 32 chars)"
    reserved = {
        "doc",
        "docx",
        "pptx",
        "page",
        "code",
        "default",
        "moe",
        "research",
    }
    if command in reserved:
        return f"/{command} is a built-in command"
    for prompt in list_prompts():
        if prompt["command"] == command and prompt["id"] != prompt_id:
            return f"/{command} already exists"
    return None


def add_prompt(data: dict[str, Any]) -> dict[str, Any] | str:
    """Create a prompt. Returns the prompt or an error string."""
    cleaned = _clean(data)
    if not cleaned:
        return "name and template are required"
    error = validate_command(cleaned["command"])
    if error:
        return error
    prompts = list_prompts()
    prompts.append(cleaned)
    _write(prompts)
    return cleaned


def update_prompt(prompt_id: str, data: dict[str, Any]) -> dict[str, Any] | str:
    """Update a prompt. Returns the prompt or an error string."""
    prompts = list_prompts()
    index = next((i for i, p in enumerate(prompts) if p["id"] == prompt_id), None)
    if index is None:
        return "Prompt not found"
    merged = {**prompts[index], **data, "id": prompt_id}
    cleaned = _clean(merged)
    if not cleaned:
        return "name and template are required"
    error = validate_command(cleaned["command"], prompt_id)
    if error:
        return error
    prompts[index] = cleaned
    _write(prompts)
    return cleaned


def delete_prompt(prompt_id: str) -> bool:
    prompts = list_prompts()
    kept = [p for p in prompts if p["id"] != prompt_id]
    if len(kept) == len(prompts):
        return False
    _write(kept)
    return True
