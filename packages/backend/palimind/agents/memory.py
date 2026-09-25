from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from palimind.settings import AGENT_MEMORY_MAX_ENTRIES

ALLOWED_TYPES = ("fact", "preference", "result", "error")

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "are",
    "was",
    "were",
    "with",
    "that",
    "this",
    "from",
    "have",
    "has",
    "had",
    "you",
    "your",
    "our",
    "its",
    "into",
    "about",
    "what",
    "when",
    "where",
    "which",
    "who",
    "how",
    "why",
    "can",
    "will",
    "would",
    "should",
    "could",
    "not",
    "but",
    "all",
    "any",
    "some",
    "use",
    "using",
    "run",
    "ran",
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) > 2 and w not in _STOPWORDS}


def _memory_path(agent_id: str) -> Path | None:
    """Resolve the agent's memory file from its definition."""
    from palimind.agents.registry import get_registry

    defn = get_registry().get_by_id(agent_id)
    if defn is None or not defn.memory_file:
        return None
    p = Path(defn.memory_file).expanduser()
    return p


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_memory(agent_id: str) -> list[dict[str, Any]]:
    """Return the agent's memory entries as a list of
    {timestamp, type, content} dicts, oldest first.

    The file path comes from the agent's definition (memory_file); agents
    with memory_scope 'none' have no memory file and return [].
    """
    path = _memory_path(agent_id)
    if path is None or not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, list):
            return []
        entries = [e for e in data if isinstance(e, dict)]
        return sorted(entries, key=lambda e: str(e.get("timestamp", "")))
    except Exception:
        return []


def recall_memory(agent_id: str, query: str, k: int = 8) -> list[dict[str, Any]]:
    """Return the memory entries most relevant to *query*.

    Uses lightweight lexical overlap (fast, no embedding call) and falls back
    to the most recent entries when nothing matches.
    """
    entries = read_memory(agent_id)
    if not entries:
        return []
    query_tokens = _tokens(query)
    if not query_tokens:
        return entries[-k:]
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for e in entries:
        overlap = len(query_tokens & _tokens(str(e.get("content", ""))))
        scored.append((overlap, str(e.get("timestamp", "")), e))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    relevant = [e for score, _ts, e in scored if score > 0][:k]
    return relevant or entries[-k:]


def append_memory(agent_id: str, entry_type: str, content: str) -> None:
    """Append a single memory entry, enforcing
    settings.AGENT_MEMORY_MAX_ENTRIES by dropping the oldest entries when
    the cap is exceeded. Silently no-ops for agents without a memory file.
    """
    if entry_type not in ALLOWED_TYPES:
        entry_type = "fact"
    path = _memory_path(agent_id)
    if path is None:
        return

    entries = read_memory(agent_id)
    entries.append({"timestamp": _now_iso(), "type": entry_type, "content": str(content)})
    if len(entries) > AGENT_MEMORY_MAX_ENTRIES:
        entries = entries[-AGENT_MEMORY_MAX_ENTRIES:]

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, indent=2), "utf-8")
    except OSError as e:
        print(f"[agents] failed to write memory for {agent_id}: {e}")
