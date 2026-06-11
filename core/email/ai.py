"""AI engine for the PaliMind email module.

Calls Ollama via httpx — matching the pattern in core/generative/summariser.py.
All functions return graceful defaults on failure — never raises.
Email content is sent in the user role; prompt templates are in the system role.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

# httpx is already a project dependency (>=0.27)
try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_REQUEST_TIMEOUT = 120.0  # seconds — AI can be slow


@lru_cache(maxsize=16)
def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Email prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _render_prompt(name: str, **kwargs: str) -> str:
    text = _load_prompt(name)
    for key, value in kwargs.items():
        text = text.replace("{" + key + "}", value)
    return text


def _get_ollama_settings() -> tuple[str, str]:
    """Return (ollama_base_url, chat_model) from config or sensible defaults."""
    try:
        from pathlib import Path as _Path
        from core.config import load_config
        config = load_config(_Path.cwd())
    except Exception:
        config = {}
    url = config.get("ollama_base_url", "https://heavy-hounds-hunt.loca.lt")
    model = config.get("chat_model", "gemma3:latest")
    return url, model


def _call_ollama(system_prompt: str, user_content: str) -> str | None:
    """Make a synchronous Ollama /api/chat call. Returns text or None on error."""
    if httpx is None:
        return None
    url, model = _get_ollama_settings()
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    try:
        resp = httpx.post(
            f"{url}/api/chat",
            json=payload,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data.get("message", {}).get("content", "").strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def summarise_email(body_text: str) -> str:
    """Return a 2-3 sentence summary of the email body, or '' on failure."""
    if not body_text.strip():
        return ""
    prompt = _render_prompt("summarise", body_text=body_text[:6000])
    result = _call_ollama("You are a precise email summariser.", prompt)
    return result or ""


def classify_tags(subject: str, body_text: str) -> list[str]:
    """Return a list of 1-5 classification tags, or [] on failure."""
    prompt = _render_prompt(
        "classify",
        subject=subject[:200],
        body_text=body_text[:4000],
    )
    result = _call_ollama("You are an email classifier. Reply only with a comma-separated tag list.", prompt)
    if not result:
        return []
    tags = [t.strip().lower() for t in result.split(",") if t.strip()]
    return tags[:5]


def score_priority(subject: str, body_text: str, sender: str) -> int:
    """Return a priority score 0-5, or 0 on failure."""
    prompt = _render_prompt(
        "priority",
        sender=sender[:200],
        subject=subject[:200],
        body_text=body_text[:4000],
    )
    result = _call_ollama("You are an email priority scorer. Reply only with a single integer.", prompt)
    if not result:
        return 0
    m = re.search(r"\b([0-5])\b", result)
    return int(m.group(1)) if m else 0


def score_spam(subject: str, body_text: str, sender: str) -> int:
    """Return a spam score 0-100, or 0 on failure."""
    prompt = _render_prompt(
        "spam",
        sender=sender[:200],
        subject=subject[:200],
        body_text=body_text[:4000],
    )
    result = _call_ollama("You are a spam detector. Reply only with a single integer 0-100.", prompt)
    if not result:
        return 0
    m = re.search(r"\b([0-9]{1,3})\b", result)
    if m:
        return min(100, max(0, int(m.group(1))))
    return 0


def draft_reply(
    *,
    sender: str,
    subject: str,
    body_text: str,
    intent: str,
) -> str:
    """Draft a reply to an email. Returns draft text or '' on failure."""
    prompt = _render_prompt(
        "draft_reply",
        sender=sender[:200],
        subject=subject[:200],
        body_text=body_text[:4000],
        intent=intent[:500],
    )
    result = _call_ollama(
        "You are an expert email writer. Draft clear, professional replies.",
        prompt,
    )
    return result or ""


def draft_compose(*, intent: str, recipient: str) -> str:
    """Draft a new email from scratch. Returns draft text or '' on failure."""
    prompt = _render_prompt(
        "draft_compose",
        recipient=recipient[:200],
        intent=intent[:500],
    )
    result = _call_ollama(
        "You are an expert email writer. Draft clear, professional emails.",
        prompt,
    )
    return result or ""
