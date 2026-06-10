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

_CHAT_SUMMARY_SYSTEM = (
    "You are an AI assistant tasked with summarizing an ongoing conversation. "
    "Given the previous summary (if any) and the recent messages, update the summary to reflect the "
    "most important points, decisions, and context of the entire conversation so far. "
    "Keep it concise but informative. Do not use formatting, just plain text."
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


def summarise_conversation(
    recent_messages: list[dict],
    previous_summary: str,
    ollama_url: str,
    chat_model: str,
) -> str:
    """Update the running summary of a conversation."""
    if not recent_messages:
        return previous_summary

    prompt_lines = []
    if previous_summary:
        prompt_lines.append(f"Previous Summary: {previous_summary}\n")
    
    prompt_lines.append("Recent Messages:")
    for m in recent_messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        prompt_lines.append(f"{role.capitalize()}: {content}")
        
    user_content = "\n".join(prompt_lines)
    
    payload = {
        "model": chat_model,
        "messages": [
            {"role": "system", "content": _CHAT_SUMMARY_SYSTEM},
            {"role": "user", "content": user_content},
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
        return previous_summary
