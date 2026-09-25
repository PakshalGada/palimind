"""Agent Skills: reusable prompt fragments (+ optional tools) attachable to an
agent.

A skill is a small, self-contained behaviour bundle — e.g. "research and cite
sources" or "review code for edge cases". Built-ins ship with the app; users
can drop additional ``~/.palimind/skills/<id>.json`` files with the same shape:

    {
      "id": "my-skill",
      "name": "My Skill",
      "description": "One line",
      "category": "writing",
      "tools": ["web_search"],
      "instructions": "Always ..."
    }

Attaching a skill to an agent injects its ``instructions`` into the system
prompt and unions its ``tools`` into the agent's allowed tool set.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SKILLS_DIR = Path.home() / ".palimind" / "skills"

BUILTIN_SKILLS: list[dict[str, Any]] = [
    {
        "id": "web-research",
        "name": "Web research",
        "description": "Search the live web, read sources and cite them.",
        "category": "research",
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
        "tools": [],
        "instructions": (
            "Writing style: lead with the answer, then supporting detail. Use "
            "short sentences and plain language. Cut filler, hedging and "
            "repetition. Prefer concrete examples over abstractions. Match the "
            "tone the user asks for."
        ),
    },
]


def _load_user_skills() -> list[dict[str, Any]]:
    if not SKILLS_DIR.is_dir():
        return []
    skills: list[dict[str, Any]] = []
    for path in sorted(SKILLS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        sid = str(data.get("id") or path.stem)
        skills.append(
            {
                "id": sid,
                "name": str(data.get("name") or sid),
                "description": str(data.get("description", "")),
                "category": str(data.get("category", "custom")),
                "tools": [str(t) for t in data.get("tools", []) if isinstance(t, str)],
                "instructions": str(data.get("instructions", "")),
                "builtin": False,
            }
        )
    return skills


def list_skills() -> list[dict[str, Any]]:
    """All skills (built-ins + user files, user overriding by id)."""
    merged: dict[str, dict[str, Any]] = {s["id"]: {**s, "builtin": True} for s in BUILTIN_SKILLS}
    for skill in _load_user_skills():
        merged[skill["id"]] = skill
    return sorted(merged.values(), key=lambda s: s["id"])


def get_skill(skill_id: str) -> dict[str, Any] | None:
    for skill in list_skills():
        if skill["id"] == skill_id:
            return skill
    return None


def skill_tools(skill_ids: list[str] | None) -> list[str]:
    """Union of the tools declared by the given skills (unknown ids ignored)."""
    tools: list[str] = []
    for sid in skill_ids or []:
        skill = get_skill(str(sid))
        if skill:
            for t in skill.get("tools", []):
                if t not in tools:
                    tools.append(t)
    return tools


def skill_instructions(skill_ids: list[str] | None) -> str:
    """Concatenated instructions block for the given skills, or ''."""
    blocks: list[str] = []
    for sid in skill_ids or []:
        skill = get_skill(str(sid))
        if skill and skill.get("instructions", "").strip():
            blocks.append(f"## Skill: {skill['name']}\n{skill['instructions'].strip()}")
    if not blocks:
        return ""
    return "[SKILLS]\n" + "\n\n".join(blocks) + "\n"
