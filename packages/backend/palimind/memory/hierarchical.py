from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from palimind.memory.session_store import get_sessions_index_file, load_session_by_id
from palimind.storage.chat_store import search_chat_episodes


def get_hierarchical_memory(
    root: Path,
    session_id: str | None,
    query: str,
    ollama_url: str,
    embed_model: str,
    short_term_limit: int = 5,
    long_term_limit: int = 3,
) -> dict[str, Any]:
    """Retrieve Hierarchical Memory (Short-term window, Mid-term summary, Long-term episodes)

    Returns dict with keys:
    - active_sess_id: str | None
    - short_term: list[dict]
    - mid_term_summary: str | None
    - long_term_episodes: list[dict]
    - formatted_memory_context: str
    """
    # Resolve the active session ID
    active_sess_id = session_id
    if not active_sess_id:
        try:
            index_file = get_sessions_index_file(root)
            if index_file.exists():
                index_data = json.loads(index_file.read_text("utf-8"))
                active_sess_id = index_data.get("active_session_id")
        except Exception:
            pass

    short_term: list[dict] = []
    mid_term_summary: str | None = None

    if active_sess_id:
        target_sess = load_session_by_id(root, active_sess_id)

        if target_sess:
            mid_term_summary = target_sess.get("summary")
            raw_msgs = target_sess.get("messages", [])
            for msg in raw_msgs[-short_term_limit:]:
                role = msg.get("role", "user")
                if role == "system":
                    role = "assistant"
                short_term.append({"role": role, "content": msg.get("content", "")})

    long_term_episodes: list[dict] = []
    if long_term_limit > 0 and query and query.strip():
        try:
            from palimind.core.embedder import generate_embeddings_batch

            embs = generate_embeddings_batch([query], ollama_url, embed_model)
            if embs and embs[0]:
                episodes = search_chat_episodes(root, embs[0], limit=long_term_limit)
                for ep in episodes:
                    long_term_episodes.append(ep)
        except Exception as e:
            print(f"[Memory] Failed to retrieve long-term episodes: {e}")

    formatted_context = format_hierarchical_memory_context(
        mid_term_summary=mid_term_summary,
        long_term_episodes=long_term_episodes,
    )

    return {
        "active_sess_id": active_sess_id,
        "short_term": short_term,
        "mid_term_summary": mid_term_summary,
        "long_term_episodes": long_term_episodes,
        "formatted_memory_context": formatted_context,
    }


def format_hierarchical_memory_context(
    mid_term_summary: str | None,
    long_term_episodes: list[dict],
) -> str:
    """Format mid-term summary and long-term episodes into a context block for system prompts."""
    parts = []
    if mid_term_summary and mid_term_summary.strip():
        parts.append(
            f"### Running Conversation Summary (Mid-term Memory)\n{mid_term_summary.strip()}"
        )

    if long_term_episodes:
        ep_lines = []
        for i, ep in enumerate(long_term_episodes, start=1):
            content = ep.get("content", "").strip()
            if content:
                ep_lines.append(f"- Episode {i}: {content}")
        if ep_lines:
            parts.append(
                "### Relevant Past Conversations (Long-term Episodic Memory)\n"
                + "\n".join(ep_lines)
            )

    if not parts:
        return ""

    return "\n\n".join(parts)
