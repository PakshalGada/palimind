"""Agent Skills: reusable behaviour bundles invocable as slash commands.

A skill is a self-contained behaviour bundle — e.g. "research and cite
sources", "review code for edge cases" or a user command like ``/commit``.
Built-ins ship with the app; users can drop additional skill files into
``~/.palimind/skills/`` (global) or ``<workspace>/.palimind/skills/``
(per-knowledge-base). Both ``*.json`` and ``*.yaml``/``*.yml`` are supported:

    id: my-skill
    name: My Skill
    description: One line
    category: writing
    command: /myskill          # optional slash command
    tools: [web_search]
    compose: [web-research]    # optional: inherit tools/instructions
    instructions: |
      Always ...

Attaching a skill to an agent injects its ``instructions`` into the system
prompt and unions its ``tools`` into the agent's allowed tool set. A skill with
a ``command`` is exposed as a user-invocable slash command and can be shared
through the bundled marketplace catalog.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from palimind.settings import SKILL_MAX_INSTRUCTIONS, SKILLS_ENABLE_MARKETPLACE

SKILLS_DIR = Path.home() / ".palimind" / "skills"
WORKSPACE_SKILLS_SUBDIR = Path(".palimind") / "skills"

_ID_RE = re.compile(r"^[\w-]{1,64}$")
_COMMAND_RE = re.compile(r"^/[a-zA-Z0-9][\w-]{0,31}$")

BUILTIN_SKILLS: list[dict[str, Any]] = [
    {
        "id": "web-research",
        "name": "Web research",
        "description": "Search the live web, read sources and cite them.",
        "category": "research",
        "command": "/research",
        "tools": [
            "web_search",
            "fetch_url",
            "browser_open",
            "browser_snapshot",
            "browser_extract",
            "arxiv_search",
            "semantic_scholar_search",
            "wikipedia_search",
            "news_search",
            "fetch_rss",
        ],
        "instructions": (
            "Research method: break the question into sub-questions. Search the "
            "web for each, open the most authoritative sources, and cross-check "
            "claims across at least two independent sources. Prefer primary "
            "sources. In your final answer, cite each claim with its source URL "
            "and clearly separate what is verified from what is uncertain. Never "
            "invent a source."
        ),
    },
    {
        "id": "deep-analysis",
        "name": "Deep analysis",
        "description": "Structured, assumption-aware analysis of data and documents.",
        "category": "analysis",
        "command": "/analyze",
        "tools": ["document_search", "csv_query", "sqlite_query", "query_graph", "run_python"],
        "instructions": (
            "Analysis method: state the question and the data you are using. "
            "Show your steps, quantify where possible, and present findings as "
            "tables or bullet points. Label every assumption and estimate. If "
            "data is missing, say so rather than guessing. End with the "
            "implications of the findings."
        ),
    },
    {
        "id": "code-review",
        "name": "Code review",
        "description": "Review code for correctness, edge cases and clarity.",
        "category": "engineering",
        "command": "/review",
        "tools": ["read_file", "list_files", "glob_files", "grep_files"],
        "instructions": (
            "Review method: read the relevant code before commenting. Look for "
            "correctness bugs, unhandled edge cases, error handling gaps, and "
            "unclear naming. For each finding give the file and line, why it "
            "matters, and a concrete fix. Rank findings by severity and avoid "
            "style nitpicks unless asked."
        ),
    },
    {
        "id": "fact-check",
        "name": "Fact check",
        "description": "Verify specific claims against sources and flag uncertainty.",
        "category": "research",
        "command": "/factcheck",
        "tools": ["web_search", "fetch_url", "document_search"],
        "instructions": (
            "Verification method: restate each claim as a checkable statement. "
            "For each, search for supporting and contradicting evidence, then "
            "label it Verified, Disputed, or Unverified, with sources. Be "
            "explicit about confidence and about the difference between absence "
            "of evidence and evidence of absence."
        ),
    },
    {
        "id": "concise-writer",
        "name": "Concise writer",
        "description": "Write tight, plain-language prose.",
        "category": "writing",
        "command": "/concise",
        "tools": [],
        "instructions": (
            "Writing style: lead with the answer, then supporting detail. Use "
            "short sentences and plain language. Cut filler, hedging and "
            "repetition. Prefer concrete examples over abstractions. Match the "
            "tone the user asks for."
        ),
    },
    {
        "id": "commit",
        "name": "Commit changes",
        "description": "Stage and commit the current workspace changes with a clear message.",
        "category": "engineering",
        "command": "/commit",
        "tools": ["run_shell", "read_file", "list_files", "grep_files"],
        "instructions": (
            "Commit method: inspect the working tree first (git status, git diff). "
            "Group changes into one logical commit, write a concise imperative "
            "commit message describing the why, stage only the intended files and "
            "commit. Never force-push and never commit secrets."
        ),
    },
]

# Skills offered through the bundled marketplace. They are not installed until
# the user explicitly installs them.
MARKETPLACE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "release-notes",
        "name": "Release notes",
        "description": "Turn merged changes into user-facing release notes.",
        "category": "engineering",
        "command": "/release-notes",
        "version": "1.0.0",
        "author": "PaliMind",
        "tools": ["run_shell", "read_file", "grep_files"],
        "instructions": (
            "Release-notes method: collect the commits/changes since the last tag. "
            "Group them into Added, Changed, Fixed and Removed. Write each entry in "
            "plain language for end users, not developers. Omit internal refactors "
            "unless they change behaviour."
        ),
    },
    {
        "id": "meeting-notes",
        "name": "Meeting notes",
        "description": "Summarise a transcript into decisions and action items.",
        "category": "writing",
        "command": "/meeting",
        "version": "1.0.0",
        "author": "PaliMind",
        "tools": ["document_search", "summarize"],
        "instructions": (
            "Meeting-notes method: read the transcript, then output: a one-line "
            "summary, the key decisions, and a table of action items with owner and "
            "due date when stated. Distinguish decisions from open questions."
        ),
    },
    {
        "id": "security-audit",
        "name": "Security audit",
        "description": "Audit code for common security weaknesses.",
        "category": "engineering",
        "command": "/security-audit",
        "version": "1.0.0",
        "author": "PaliMind",
        "tools": ["read_file", "list_files", "grep_files", "run_shell"],
        "instructions": (
            "Security method: look for injection, path traversal, unsafe "
            "deserialization, secrets in code, missing authorization, and SSRF. For "
            "each finding give the location, the attack scenario, severity, and a "
            "concrete remediation. Do not invent issues; mark uncertain items."
        ),
    },
]


def _normalize_skill(data: dict[str, Any], *, builtin: bool) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    sid = str(data.get("id") or "").strip()
    if not sid:
        return None
    tools = data.get("tools", [])
    if not isinstance(tools, list):
        tools = [tools]
    compose = data.get("compose", [])
    if not isinstance(compose, list):
        compose = [compose]
    return {
        "id": sid,
        "name": str(data.get("name") or sid),
        "description": str(data.get("description", "")),
        "category": str(data.get("category", "custom")),
        "command": str(data.get("command", "") or ""),
        "tools": [str(t) for t in tools if isinstance(t, str) and t],
        "compose": [str(c) for c in compose if isinstance(c, str) and c],
        "instructions": str(data.get("instructions", "")),
        "version": str(data.get("version", "") or ""),
        "author": str(data.get("author", "") or ""),
        "tags": [str(t) for t in data.get("tags", []) if isinstance(t, str)]
        if isinstance(data.get("tags", []), list)
        else [],
        "enabled": bool(data.get("enabled", True)),
        "source": str(data.get("source", "builtin" if builtin else "user")),
        "builtin": builtin,
    }


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ImportError:
        return None
    try:
        return yaml.safe_load(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - invalid YAML is skipped
        return None


def _load_skill_file(path: Path) -> dict[str, Any] | None:
    try:
        if path.suffix.lower() in (".yaml", ".yml"):
            data = _load_yaml(path)
        else:
            data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", path.stem)
    return _normalize_skill(data, builtin=False)


def _load_user_skills(directory: Path | None = None) -> list[dict[str, Any]]:
    root = directory if directory is not None else SKILLS_DIR
    if not root.is_dir():
        return []
    skills: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern in ("*.json", "*.yaml", "*.yml"):
        for path in sorted(root.glob(pattern)):
            skill = _load_skill_file(path)
            if skill is None or skill["id"] in seen:
                continue
            seen.add(skill["id"])
            skills.append(skill)
    return skills


def list_skills(workspace_root: Path | str | None = None) -> list[dict[str, Any]]:
    """All skills (built-ins + user files, user overriding by id).

    ``workspace_root`` adds per-workspace skills from
    ``<workspace_root>/.palimind/skills`` which take precedence over global
    user skills.
    """
    merged: dict[str, dict[str, Any]] = {}
    for builtin in BUILTIN_SKILLS:
        normalized = _normalize_skill(builtin, builtin=True)
        if normalized is not None:
            merged[normalized["id"]] = normalized
    for skill in _load_user_skills():
        merged[skill["id"]] = skill
    for skill in _PLUGIN_SKILLS.values():
        merged[skill["id"]] = skill
    if workspace_root:
        ws_dir = Path(workspace_root) / WORKSPACE_SKILLS_SUBDIR
        for skill in _load_user_skills(ws_dir):
            skill["source"] = "workspace"
            merged[skill["id"]] = skill
    return sorted(merged.values(), key=lambda s: s["id"])


def get_skill(skill_id: str, workspace_root: Path | str | None = None) -> dict[str, Any] | None:
    for skill in list_skills(workspace_root):
        if skill["id"] == skill_id:
            return skill
    return None


def expand_skill(
    skill_id: str,
    _seen: set[str] | None = None,
    workspace_root: Path | str | None = None,
) -> dict[str, Any] | None:
    """Resolve a skill including everything it composes (cycle-safe)."""
    seen = _seen if _seen is not None else set()
    if skill_id in seen:
        return None
    seen.add(skill_id)
    skill = get_skill(skill_id, workspace_root)
    if skill is None or not skill.get("enabled", True):
        return None
    tools = list(skill.get("tools", []))
    instructions = [skill.get("instructions", "").strip()]
    for composed_id in skill.get("compose", []):
        composed = expand_skill(composed_id, seen, workspace_root)
        if composed is None:
            continue
        for t in composed.get("tools", []):
            if t not in tools:
                tools.append(t)
        if composed.get("instructions"):
            instructions.append(composed["instructions"].strip())
    return {
        **skill,
        "tools": tools,
        "instructions": "\n\n".join(i for i in instructions if i),
    }


def skill_tools(skill_ids: list[str] | None, workspace_root: Path | str | None = None) -> list[str]:
    """Union of the tools declared by the given skills (unknown ids ignored)."""
    tools: list[str] = []
    for sid in skill_ids or []:
        skill = expand_skill(str(sid), workspace_root=workspace_root)
        if skill:
            for t in skill.get("tools", []):
                if t not in tools:
                    tools.append(t)
    return tools


def skill_instructions(
    skill_ids: list[str] | None, workspace_root: Path | str | None = None
) -> str:
    """Concatenated instructions block for the given skills, or ''."""
    blocks: list[str] = []
    for sid in skill_ids or []:
        skill = expand_skill(str(sid), workspace_root=workspace_root)
        if skill and skill.get("instructions", "").strip():
            blocks.append(f"## Skill: {skill['name']}\n{skill['instructions'].strip()}")
    if not blocks:
        return ""
    return "[SKILLS]\n" + "\n\n".join(blocks) + "\n"


# ── slash commands ────────────────────────────────────────────────────────


def skill_commands(workspace_root: Path | str | None = None) -> list[dict[str, Any]]:
    """All installed skills that expose a slash command."""
    commands: list[dict[str, Any]] = []
    for skill in list_skills(workspace_root):
        command = str(skill.get("command", "") or "")
        if command and skill.get("enabled", True):
            commands.append(
                {
                    "command": command,
                    "skill_id": skill["id"],
                    "name": skill["name"],
                    "description": skill["description"],
                    "category": skill["category"],
                }
            )
    return sorted(commands, key=lambda c: c["command"])


def resolve_command(text: str, workspace_root: Path | str | None = None) -> dict[str, Any] | None:
    """Resolve ``/command rest of input`` to its skill and remaining input."""
    raw = str(text or "").strip()
    if not raw.startswith("/"):
        return None
    head, _, rest = raw.partition(" ")
    command = head.strip()
    for entry in skill_commands(workspace_root):
        if entry["command"].lower() == command.lower():
            skill = get_skill(entry["skill_id"], workspace_root)
            return {
                "command": command,
                "skill": skill,
                "input": rest.strip(),
            }
    return None


# ── validation, install, marketplace ──────────────────────────────────────


def validate_skill(data: dict[str, Any]) -> str | None:
    """Return an error string for an invalid skill, else None."""
    if not isinstance(data, dict):
        return "skill must be an object"
    sid = str(data.get("id", "")).strip()
    if not _ID_RE.match(sid):
        return "id must be 1-64 chars of letters, digits, underscore or dash"
    name = str(data.get("name", "")).strip()
    if not name:
        return "name is required"
    if len(name) > 120:
        return "name must be at most 120 characters"
    instructions = str(data.get("instructions", ""))
    if len(instructions) > SKILL_MAX_INSTRUCTIONS:
        return f"instructions exceed {SKILL_MAX_INSTRUCTIONS} characters"
    command = str(data.get("command", "") or "").strip()
    if command and not _COMMAND_RE.match(command):
        return "command must look like /name (letters, digits, dash)"
    tools = data.get("tools", [])
    if not isinstance(tools, list):
        return "tools must be a list"
    if tools:
        from palimind.llm.mixture_of_expert.tools import get_tool_names

        known = set(get_tool_names())
        unknown = [str(t) for t in tools if str(t) not in known]
        if unknown:
            return f"unknown tools: {', '.join(unknown)}"
    compose = data.get("compose", [])
    if not isinstance(compose, list):
        return "compose must be a list"
    for composed in compose:
        if not _ID_RE.match(str(composed)):
            return f"invalid composed skill id: {composed}"
    return None


def _skill_write_path(skill_id: str) -> Path:
    safe = "".join(c for c in str(skill_id) if c.isalnum() or c in "-_")
    return SKILLS_DIR / f"{safe}.json"


def install_skill(
    data: dict[str, Any],
    *,
    source: str = "user",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Validate and persist a skill to the global skills directory.

    Raises ``ValueError`` on validation failure or when the skill is built-in
    and *overwrite* is False.
    """
    error = validate_skill(data)
    if error:
        raise ValueError(error)
    sid = str(data["id"])
    existing = get_skill(sid)
    if existing and existing.get("builtin") and not overwrite:
        raise ValueError(f"'{sid}' is a built-in skill; pass overwrite to replace it")
    if _skill_write_path(sid).exists() and not overwrite:
        raise ValueError(f"skill '{sid}' already exists")
    normalized = _normalize_skill(data, builtin=False)
    if normalized is None:
        raise ValueError("invalid skill")
    payload = {**normalized, "source": source}
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    _skill_write_path(sid).write_text(json.dumps(payload, indent=2), "utf-8")
    return payload


def uninstall_skill(skill_id: str) -> bool:
    """Remove a user-installed skill. Built-ins cannot be removed."""
    skill = get_skill(skill_id)
    if skill is None or skill.get("builtin"):
        return False
    path = _skill_write_path(skill_id)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


def export_skill(skill_id: str) -> dict[str, Any] | None:
    """Serialize a skill (expanded) for sharing."""
    skill = expand_skill(skill_id)
    if skill is None:
        return None
    return {
        "id": skill["id"],
        "name": skill["name"],
        "description": skill["description"],
        "category": skill["category"],
        "command": skill.get("command", ""),
        "version": skill.get("version", ""),
        "author": skill.get("author", ""),
        "tools": skill.get("tools", []),
        "instructions": skill.get("instructions", ""),
    }


def list_marketplace() -> list[dict[str, Any]]:
    """Bundled marketplace entries, annotated with installed state."""
    if not SKILLS_ENABLE_MARKETPLACE:
        return []
    installed = {s["id"] for s in list_skills()}
    return [{**entry, "installed": entry["id"] in installed} for entry in MARKETPLACE_CATALOG]


def install_from_marketplace(skill_id: str, *, overwrite: bool = False) -> dict[str, Any]:
    """Install a skill from the bundled marketplace catalog."""
    if not SKILLS_ENABLE_MARKETPLACE:
        raise ValueError("the skill marketplace is disabled")
    entry = next((e for e in MARKETPLACE_CATALOG if e["id"] == skill_id), None)
    if entry is None:
        raise ValueError(f"unknown marketplace skill: {skill_id}")
    return install_skill(entry, source="marketplace", overwrite=overwrite)


def register_plugin_skill(data: dict[str, Any]) -> dict[str, Any]:
    """Register an in-memory skill supplied by a plugin (not persisted)."""
    error = validate_skill(data)
    if error:
        raise ValueError(error)
    skill = _normalize_skill(data, builtin=False)
    if skill is None:
        raise ValueError("invalid skill")
    skill = {**skill, "source": "plugin"}
    _PLUGIN_SKILLS[skill["id"]] = skill
    return skill


_PLUGIN_SKILLS: dict[str, dict[str, Any]] = {}


__all__ = [
    "BUILTIN_SKILLS",
    "MARKETPLACE_CATALOG",
    "SKILLS_DIR",
    "WORKSPACE_SKILLS_SUBDIR",
    "expand_skill",
    "export_skill",
    "get_skill",
    "install_from_marketplace",
    "install_skill",
    "list_marketplace",
    "list_skills",
    "register_plugin_skill",
    "resolve_command",
    "skill_commands",
    "skill_instructions",
    "skill_tools",
    "uninstall_skill",
    "validate_skill",
]
