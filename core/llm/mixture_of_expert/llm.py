"""Unified Ollama chat client for the MoE pipeline.

Consolidates the duplicated `_llm_chat` helpers and adds support for:
- Native function calling via the `tools` parameter (models that support
  it emit `message.tool_calls` instead of free-text tool syntax).
- Structured output via `format="json"`.
- Per-call temperature and timeout tuning.
"""
from __future__ import annotations

import json
from typing import Any


class LLMError(Exception):
    pass


def llm_chat(
    messages: list[dict[str, str]],
    model: str,
    ollama_url: str,
    *,
    tools: list[dict] | None = None,
    format: str | None = None,
    temperature: float | None = None,
    read_timeout: float = 300.0,
    num_predict: int | None = None,
) -> dict[str, Any]:
    """Call Ollama /api/chat and return a normalized result dict.

    Returns:
        {
            "content": str,                      # text content
            "tool_calls": [                      # normalized native tool calls
                {"name": str, "arguments": dict}
            ],
        }
    Raises:
        LLMError on HTTP/timeout/decode failures.
    """
    import httpx

    url = f"{ollama_url.rstrip('/')}/api/chat"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    if format:
        payload["format"] = format

    options: dict[str, Any] = {}
    if temperature is not None:
        options["temperature"] = temperature
    if num_predict is not None:
        options["num_predict"] = num_predict
    if options:
        payload["options"] = options

    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=read_timeout, write=10.0, pool=10.0)
        ) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException as e:
        raise LLMError(f"LLM timed out: {e}") from e
    except httpx.HTTPError as e:
        raise LLMError(f"LLM HTTP error: {e}") from e
    except json.JSONDecodeError as e:
        raise LLMError(f"Invalid LLM response: {e}") from e

    message = data.get("message", {}) or {}
    content = message.get("content", "") or ""

    tool_calls: list[dict[str, Any]] = []
    for tc in message.get("tool_calls", []) or []:
        fn = tc.get("function", {}) or {}
        name = fn.get("name", "")
        if not name:
            continue
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        tool_calls.append({"name": name, "arguments": args or {}})

    return {"content": content, "tool_calls": tool_calls}


def llm_chat_safe(
    messages: list[dict[str, str]],
    model: str,
    ollama_url: str,
    *,
    error_prefix: str = "[LLM error",
    **kwargs: Any,
) -> dict[str, Any]:
    """llm_chat that never raises; errors come back as content."""
    try:
        return llm_chat(messages, model, ollama_url, **kwargs)
    except LLMError as e:
        return {"content": f"{error_prefix}: {e}]", "tool_calls": []}


# ── native tool schemas ──────────────────────────────────────────────

def ollama_tools_from_registry(registry: dict[str, dict]) -> list[dict]:
    """Convert the MoE TOOL_REGISTRY into Ollama `tools` format."""
    tools: list[dict] = []
    for name, info in sorted(registry.items()):
        params = info.get("parameters", {})
        properties: dict[str, Any] = {}
        required: list[str] = []
        for pname, pdesc in params.items():
            properties[pname] = {"type": "string", "description": pdesc}
            if not pdesc.lower().startswith("optional") and "default" not in pdesc.lower():
                required.append(pname)
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": info.get("description", ""),
                    "parameters": schema,
                },
            }
        )
    return tools
