"""Build a portable chat bundle: transcript, artifacts, sources and manifest."""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from typing import Any

_EXTENSIONS = {
    "slide-outline": "md",
    "document": "md",
    "markdown": "md",
    "table": "md",
    "html": "html",
    "svg": "svg",
    "mermaid": "mmd",
    "react": "jsx",
    "code": "txt",
    "code-file": "txt",
    "multi-file": "txt",
}


def _slug(value: str, fallback: str = "item", limit: int = 72) -> str:
    text = re.sub(r"[^\w.-]+", "_", str(value or ""), flags=re.ASCII).strip("._")
    return (text or fallback)[:limit]


def _role_label(role: str) -> str:
    if role == "user":
        return "You"
    if role in {"assistant", "system"}:
        return "Assistant"
    if role == "tool":
        return "Tool"
    return str(role or "Message").capitalize()


def _source_lines(sources: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        title = str(source.get("title") or source.get("url") or source.get("file") or "Source")
        url = str(source.get("url") or "")
        file = str(source.get("file") or "")
        section = str(source.get("section") or "")
        location = url or (f"{file}" + (f" / {section}" if section else ""))
        lines.append(f"{index}. [{title}]({location})" if location else f"{index}. {title}")
    return lines


def build_chat_bundle(payload: dict[str, Any]) -> bytes:
    """Return a ZIP containing transcript.md, sources, artifacts and manifest."""
    title = str(payload.get("title") or "Conversation").strip() or "Conversation"
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else []
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    generated = datetime.now(UTC).isoformat()
    files: list[str] = []

    transcript: list[str] = [
        f"# {title}",
        "",
        f"*Exported from PaliMind · {generated}*",
        "",
        "---",
        "",
    ]
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            continue
        transcript.extend(
            [
                f"## {_role_label(str(message.get('role') or ''))}",
                "",
                str(message.get("content") or "").strip(),
                "",
                "---",
                "",
            ]
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("transcript.md", "\n".join(transcript).rstrip() + "\n")
        files.append("transcript.md")

        source_md = ["# Sources", "", *_source_lines(sources)]
        archive.writestr("sources.md", "\n".join(source_md).rstrip() + "\n")
        archive.writestr("sources.json", json.dumps(sources, indent=2, default=str) + "\n")
        files.extend(["sources.md", "sources.json"])

        used: set[str] = set()
        for index, artifact in enumerate(artifacts, start=1):
            if not isinstance(artifact, dict):
                continue
            artifact_title = str(artifact.get("title") or f"Artifact {index}")
            artifact_type = str(artifact.get("type") or "code")
            extension = _EXTENSIONS.get(artifact_type, "txt")
            base = _slug(artifact_title, f"artifact_{index}")
            name = f"artifacts/{base}.{extension}"
            if name in used:
                name = f"artifacts/{base}_{index}.{extension}"
            used.add(name)
            body = str(artifact.get("content") or "")
            archive.writestr(name, body.rstrip() + "\n")
            files.append(name)

        manifest = {
            "title": title,
            "generated_at": generated,
            "message_count": len(messages),
            "artifact_count": len(artifacts),
            "source_count": len(sources),
            "files": files,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        archive.writestr(
            "README.md",
            f"# {title}\n\nChat bundle exported from PaliMind on {generated}.\n\n"
            "- `transcript.md` — full conversation\n"
            "- `artifacts/` — generated outputs\n"
            "- `sources.md` and `sources.json` — citations and references\n"
            "- `manifest.json` — bundle metadata\n",
        )

    return buffer.getvalue()
