"""Generate concise file summaries using the local chat model.

Called at index time, after chunking, so every file gets a 2-3 sentence
description stored in the ``files.summary`` SQLite column.
"""
from __future__ import annotations

import json

import httpx

from core.exceptions import ResponseError


_SYSTEM = (
    "You are a concise technical summariser. "
    "Write a 2-3 sentence plain-English summary of the document provided. "
    "Focus on what the document contains and its purpose. "
    "Do NOT include headings, bullet points, or markdown. "
    "Answer with the summary only."
)

_MAX_CHARS = 8_000


def summarise_file(
    text: str,
    ollama_url: str,
    chat_model: str,
    *,
    max_chars: int = _MAX_CHARS,
) -> str:
    """Return a short summary of *text* via the local chat model.

    Returns an empty string on empty input or model failure (never raises).
    """
    if not text or not text.strip():
        return ""

    excerpt = text[:max_chars]
    if len(text) > max_chars:
        excerpt += "\n[... truncated ...]"

    payload = {
        "model": chat_model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": excerpt},
        ],
        "stream": False,
    }

    url = f"{ollama_url.rstrip('/')}/api/chat"
    try:
        resp = httpx.post(url, json=payload, timeout=120.0)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()
    except (httpx.HTTPError, json.JSONDecodeError, KeyError):
        return ""
