"""Minimal OpenAI-compatible chat client for the hosted benchmark baseline.

The local agent loop speaks Ollama's wire format. For a fair head-to-head we
need the hosted baseline to use *native* OpenAI ``tool_calls`` and ``role=tool``
messages, not the Ollama proxy's text fallback.

This module deliberately implements only what the agent loop needs:
chat-completions, tool calls, JSON mode, usage and a test ``transport`` seam.
It works with xAI/Grok, OpenCode Zen, OpenAI and any compatible endpoint.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

DEFAULT_OPENAI_BASE = "https://opencode.ai/zen/go/v1"


class MissingCredentials(RuntimeError):
    """Raised when a hosted call has no API key and no explicit auth."""


def _api_key(api_key: str | None) -> str:
    if api_key:
        return api_key
    try:
        from palimind.opencode.auth import get_key

        key = get_key("opencode")
        if key:
            return key
    except Exception:
        pass
    raise MissingCredentials(
        "No hosted API key configured. Set XAI_API_KEY / OPENAI_API_KEY or "
        "add an OpenCode key in Settings."
    )


def _tool_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve tool_calls/tool_call_id while dropping Ollama-only fields."""
    cleaned: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {
            "role": str(message.get("role") or "user"),
            "content": message.get("content") or "",
        }
        if message.get("tool_calls"):
            item["tool_calls"] = message["tool_calls"]
        if message.get("tool_call_id"):
            item["tool_call_id"] = message["tool_call_id"]
        cleaned.append(item)
    return cleaned


def openai_chat_safe(
    messages: list[dict[str, Any]],
    model: str,
    base_url: str = "",
    *,
    api_key: str | None = None,
    tools: list[dict] | None = None,
    format: str | None = None,
    temperature: float | None = None,
    read_timeout: float = 300.0,
    num_predict: int | None = None,
    transport: Any | None = None,
    error_prefix: str = "[hosted model",
    **_ignored: Any,
) -> dict[str, Any]:
    """Call an OpenAI-compatible chat endpoint; never raise to the agent loop."""
    base = (base_url or DEFAULT_OPENAI_BASE).rstrip("/")
    url = f"{base}/chat/completions"
    try:
        key = _api_key(api_key)
    except MissingCredentials as exc:
        return {"content": f"{error_prefix}: {exc}]", "tool_calls": [], "usage": {}}

    payload: dict[str, Any] = {
        "model": model,
        "messages": _tool_messages(messages),
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if format == "json":
        payload["response_format"] = {"type": "json_object"}
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if num_predict is not None:
        payload["max_tokens"] = int(num_predict)

    try:
        import httpx

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if "opencode.ai" in url:
            try:
                from palimind.opencode.session import SESSION_HEADER, opencode_session_id

                headers[SESSION_HEADER] = opencode_session_id()
            except Exception:
                pass
        with httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=read_timeout, write=20.0, pool=10.0),
            transport=transport,
        ) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                detail = resp.text[:400].replace("\n", " ")
                return {
                    "content": f"{error_prefix}: HTTP {resp.status_code} {detail}]",
                    "tool_calls": [],
                    "usage": {},
                }
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 - benchmark must record, not crash
        return {"content": f"{error_prefix}: {exc}]", "tool_calls": [], "usage": {}}

    choices = data.get("choices") or []
    message = (choices[0].get("message") if choices else {}) or {}
    tool_calls: list[dict[str, Any]] = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        name = str(fn.get("name") or "")
        if not name:
            continue
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (TypeError, ValueError):
                args = {"_raw": args}
        if not isinstance(args, dict):
            args = {"_raw": args}
        tool_calls.append(
            {
                "id": str(tc.get("id") or ""),
                "name": name,
                "arguments": args,
                "openai": True,
            }
        )
    usage_data = data.get("usage") or {}
    usage = {
        "prompt_tokens": int(usage_data.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage_data.get("completion_tokens", 0) or 0),
    }
    return {
        "content": str(message.get("content") or ""),
        "tool_calls": tool_calls,
        "usage": usage,
    }


def is_openai_endpoint(url: str) -> bool:
    """True when *url* looks like an OpenAI-compatible base, not Ollama."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return bool(
        parsed.scheme in ("http", "https")
        and host
        and host not in ("127.0.0.1", "localhost", "::1")
    )
