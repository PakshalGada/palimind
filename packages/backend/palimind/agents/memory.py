"""Agent memory: hybrid semantic + lexical recall, editing and consolidation.

The original store was a plain list with lexical overlap recall. This version
keeps the same SQLite-backed storage and adds:

* stable entry ids, confidence, usage timestamps and ``superseded_by`` links
* a local vector representation (hashed token/bigram embedding by default;
  optionally the configured Ollama embedding model) used for semantic recall
* hybrid ranking: vector similarity + lexical overlap + recency + confidence
* editing, deletion by id and consolidation of near-duplicate memories

The default embedding is deliberately local and dependency-free so memory
continues to work offline. Set ``PALIMIND_MEMORY_EMBEDDINGS=ollama`` to use the
configured local embedding model when Ollama is available.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from palimind.settings import (
    AGENT_MEMORY_MAX_ENTRIES,
    MEMORY_CONSOLIDATE_THRESHOLD,
    MEMORY_EMBEDDINGS,
    MEMORY_LEXICAL_WEIGHT,
    MEMORY_RECENCY_WEIGHT,
    MEMORY_SEMANTIC_WEIGHT,
)

ALLOWED_TYPES = ("fact", "preference", "result", "error", "decision", "entity")

# Serialises read-modify-write of memory stores: run completion, background
# fact extraction (worker thread) and parallel team members can append to the
# same store at once and would otherwise drop each other's entries.
write_lock = threading.RLock()

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "with", "that", "this", "from",
    "have", "has", "had", "you", "your", "our", "its", "into", "about", "what",
    "when", "where", "which", "who", "how", "why", "can", "will", "would",
    "should", "could", "not", "but", "all", "any", "some", "use", "using",
    "run", "ran", "been", "being", "they", "them", "their", "there", "then",
    "than", "also", "just", "over", "under", "more", "most", "very",
}  # fmt: skip

_HASH_DIM = 256


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) > 2 and w not in _STOPWORDS}


def _memory_path(agent_id: str) -> Path | None:
    """Resolve the agent's memory store from its mode + knowledge scope."""
    from palimind.agents.registry import get_registry
    from palimind.agents.scope import memory_file_for

    registry = get_registry()
    defn = registry.get_by_id(agent_id)
    if defn is None:
        return None
    return memory_file_for(defn, getattr(registry, "field_root", None))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _memory_namespace(path: Path) -> str:
    return f"agent_memory:{path.expanduser().resolve()}"


def _entry_id(entry: dict[str, Any]) -> str:
    raw = f"{entry.get('timestamp', '')}|{entry.get('type', '')}|{entry.get('content', '')}"
    return entry.get("id") or hashlib.sha1(raw.encode()).hexdigest()[:20]


def _hash_embedding(text: str, dim: int = _HASH_DIM) -> list[float]:
    """Dependency-free local embedding: hashed unigrams + bigrams, normalized."""
    tokens = [w for w in _WORD_RE.findall(str(text or "").lower()) if w not in _STOPWORDS]
    vec = [0.0] * dim
    grams = list(tokens)
    grams.extend(f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False))
    for gram in grams:
        digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm:
        vec = [v / norm for v in vec]
    return vec


def _embed_text(text: str) -> list[float]:
    mode = str(MEMORY_EMBEDDINGS or "hash").lower()
    if mode == "ollama":
        try:
            from palimind.config import load_global_config
            from palimind.core.embedder import generate_embedding

            cfg = load_global_config()
            return generate_embedding(
                str(text),
                str(cfg.get("ollama_base_url") or "http://localhost:11434"),
                str(cfg.get("embed_model") or "bge-m3"),
            )
        except Exception:
            pass
    return _hash_embedding(text)


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b, strict=False))))


def _read_entries(agent_id: str) -> list[dict[str, Any]]:
    path = _memory_path(agent_id)
    if path is None:
        return []
    from palimind.storage import state_store

    namespace = _memory_namespace(path)
    state_store.migrate_json_file(namespace, "entries", path, default=[])
    data = state_store.get_json(namespace, "entries", default=[])
    if not isinstance(data, list):
        return []
    entries: list[dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        entry = dict(raw)
        entry["id"] = _entry_id(entry)
        entry.setdefault("type", "fact")
        entry.setdefault("timestamp", _now_iso())
        entry.setdefault("confidence", 1.0)
        entry.setdefault("last_used_at", entry["timestamp"])
        entries.append(entry)
    entries.sort(key=lambda e: str(e.get("timestamp", "")))
    return entries


def _write_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    from palimind.storage import state_store

    state_store.set_json(_memory_namespace(path), "entries", entries[-AGENT_MEMORY_MAX_ENTRIES:])


def read_memory(agent_id: str) -> list[dict[str, Any]]:
    """Return the agent's memory entries, oldest first."""
    return _read_entries(agent_id)


def recall_memory(
    agent_id: str,
    query: str,
    k: int = 8,
    *,
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    """Return the entries most relevant to *query* using hybrid ranking."""
    entries = read_memory(agent_id)
    if not include_superseded:
        entries = [e for e in entries if not e.get("superseded_by")]
    if not entries:
        return []
    limit = max(1, min(int(k or 8), 100))
    query_tokens = _tokens(query)
    if not query_tokens:
        return entries[-limit:]

    query_vec = _embed_text(query)
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for entry in entries:
        text = str(entry.get("content", ""))
        entry_tokens = _tokens(text)
        lexical = len(query_tokens & entry_tokens) / max(1, len(query_tokens))
        semantic = _cosine(query_vec, entry.get("embedding") or _hash_embedding(text))
        try:
            confidence = max(0.0, min(1.0, float(entry.get("confidence", 1.0) or 0.0)))
        except (TypeError, ValueError):
            confidence = 1.0
        try:
            age_days = max(
                0.0,
                (datetime.now(UTC) - datetime.fromisoformat(str(entry.get("timestamp")))).days,
            )
        except (TypeError, ValueError):
            age_days = 0.0
        recency = 1.0 / (1.0 + age_days / 30.0)
        score = (
            MEMORY_SEMANTIC_WEIGHT * semantic
            + MEMORY_LEXICAL_WEIGHT * lexical
            + MEMORY_RECENCY_WEIGHT * recency
            + 0.05 * confidence
        )
        scored.append((score, str(entry.get("timestamp", "")), entry))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    relevant = [entry for score, _ts, entry in scored if score > 0.02][:limit]
    return relevant or entries[-limit:]


def append_memory(
    agent_id: str,
    entry_type: str,
    content: str,
    *,
    confidence: float = 1.0,
    supersedes: list[str] | None = None,
    source_run_id: str = "",
    embedding: list[float] | None = None,
) -> dict[str, Any] | None:
    """Append a memory entry and return it.

    ``supersedes`` marks older entries as replaced by this one; superseded
    entries are hidden from default recall but remain auditable.
    """
    if entry_type not in ALLOWED_TYPES:
        entry_type = "fact"
    path = _memory_path(agent_id)
    if path is None:
        return None

    text = str(content).strip()
    if not text:
        return None
    with write_lock:
        entries = read_memory(agent_id)
        entry = {
            "id": hashlib.sha1(
                f"{_now_iso()}|{entry_type}|{text}|{len(entries)}".encode()
            ).hexdigest()[:20],
            "timestamp": _now_iso(),
            "type": entry_type,
            "content": text[:4000],
            "confidence": max(0.0, min(1.0, float(confidence))),
            "last_used_at": _now_iso(),
            "source_run_id": str(source_run_id or ""),
            "embedding": embedding or _embed_text(text),
        }
        replace = {str(x) for x in (supersedes or []) if str(x).strip()}
        for old in entries:
            if old.get("id") in replace:
                old["superseded_by"] = entry["id"]
        entries.append(entry)
        _write_entries(path, entries)
    return entry


def update_memory_entry(
    agent_id: str,
    entry_id: str,
    *,
    content: str | None = None,
    entry_type: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any] | None:
    path = _memory_path(agent_id)
    if path is None:
        return None
    with write_lock:
        entries = read_memory(agent_id)
        for entry in entries:
            if entry.get("id") != entry_id:
                continue
            if content is not None:
                entry["content"] = str(content).strip()[:4000]
                entry["embedding"] = _embed_text(entry["content"])
            if entry_type in ALLOWED_TYPES:
                entry["type"] = entry_type
            if confidence is not None:
                entry["confidence"] = max(0.0, min(1.0, float(confidence)))
            entry["last_used_at"] = _now_iso()
            _write_entries(path, entries)
            return entry
    return None


def delete_memory_entry_by_id(agent_id: str, entry_id: str) -> bool:
    path = _memory_path(agent_id)
    if path is None:
        return False
    with write_lock:
        entries = read_memory(agent_id)
        remaining = [e for e in entries if e.get("id") != entry_id]
        if len(remaining) == len(entries):
            return False
        _write_entries(path, remaining)
        return True


def consolidate_memory(
    agent_id: str,
    threshold: float = MEMORY_CONSOLIDATE_THRESHOLD,
) -> int:
    """Mark older near-duplicate entries as superseded by the newest match."""
    path = _memory_path(agent_id)
    if path is None:
        return 0
    with write_lock:
        entries = read_memory(agent_id)
        active = [e for e in entries if not e.get("superseded_by")]
        active.sort(key=lambda e: str(e.get("timestamp", "")), reverse=True)
        kept: list[dict[str, Any]] = []
        marked = 0
        for entry in active:
            vec = entry.get("embedding") or _hash_embedding(str(entry.get("content", "")))
            duplicate = next(
                (
                    newer
                    for newer in kept
                    if _cosine(
                        vec,
                        newer.get("embedding") or _hash_embedding(str(newer.get("content", ""))),
                    )
                    >= float(threshold)
                ),
                None,
            )
            if duplicate is not None:
                entry["superseded_by"] = duplicate["id"]
                marked += 1
            else:
                kept.append(entry)
        if marked:
            _write_entries(path, entries)
        return marked


def memory_stats(agent_id: str) -> dict[str, int]:
    entries = read_memory(agent_id)
    return {
        "total": len(entries),
        "active": sum(1 for e in entries if not e.get("superseded_by")),
        "superseded": sum(1 for e in entries if e.get("superseded_by")),
    }
