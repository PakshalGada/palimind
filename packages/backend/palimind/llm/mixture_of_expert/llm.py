"""Unified Ollama chat client for the MoE pipeline.

Consolidates the duplicated `_llm_chat` helpers and adds support for:
- Native function calling via the `tools` parameter (models that support
  it emit `message.tool_calls` instead of free-text tool syntax).
- Structured output via `format="json"`.
- Per-call temperature and timeout tuning.
"""

from __future__ import annotations

import json
import time
from typing import Any


class LLMError(Exception):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


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
    num_ctx: int | None = None,
    transport: Any | None = None,
) -> dict[str, Any]:
    """Call Ollama /api/chat and return a normalized result dict.

    Returns:
        {
            "content": str,                      # text content
            "tool_calls": [                      # normalized native tool calls
                {"name": str, "arguments": dict}
            ],
            "usage": {                           # token counts when available
                "prompt_tokens": int,
                "completion_tokens": int,
            },
        }
    Raises:
        LLMError on HTTP/timeout/decode failures.

    ``transport`` is a test seam (httpx.MockTransport) and is never set in
    production callers.
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
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    if options:
        payload["options"] = options

    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=read_timeout, write=10.0, pool=10.0),
            transport=transport,
        ) as client:
            resp = client.post(url, json=payload)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:200]}", transient=True)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException as e:
        raise LLMError(f"LLM timed out: {e}", transient=True) from e
    except httpx.HTTPError as e:
        raise LLMError(f"LLM HTTP error: {e}", transient=True) from e
    except json.JSONDecodeError as e:
        raise LLMError(f"Invalid LLM response: {e}") from e

    message = data.get("message", {}) or {}
    content = message.get("content", "") or ""

    tool_calls = _normalize_tool_calls(message)

    usage: dict[str, int] = {}
    if data.get("prompt_eval_count") is not None:
        usage["prompt_tokens"] = int(data["prompt_eval_count"])
    if data.get("eval_count") is not None:
        usage["completion_tokens"] = int(data["eval_count"])

    return {"content": content, "tool_calls": tool_calls, "usage": usage}


def _normalize_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize Ollama `message.tool_calls` into {name, arguments} dicts."""
    calls: list[dict[str, Any]] = []
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
        calls.append({"name": name, "arguments": args or {}})
    return calls


def llm_chat_stream(
    messages: list[dict[str, str]],
    model: str,
    ollama_url: str,
    *,
    tools: list[dict] | None = None,
    format: str | None = None,
    temperature: float | None = None,
    read_timeout: float = 300.0,
    num_predict: int | None = None,
    num_ctx: int | None = None,
    transport: Any | None = None,
):
    """Stream Ollama /api/chat, yielding incremental events.

    Yields dicts:
        {"type": "token", "text": str}          # content delta
        {"type": "tool_calls", "tool_calls": [...], "content": str}
        {"type": "usage", "usage": {...}, "content": str}
        {"type": "done"}

    Raises :class:`LLMError` on connection/HTTP/decode failures. Callers that
    need retries should catch ``LLMError`` before any token is consumed.
    """
    import httpx

    url = f"{ollama_url.rstrip('/')}/api/chat"
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
    if format:
        payload["format"] = format
    options: dict[str, Any] = {}
    if temperature is not None:
        options["temperature"] = temperature
    if num_predict is not None:
        options["num_predict"] = num_predict
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    if options:
        payload["options"] = options

    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, int] = {}

    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=read_timeout, write=10.0, pool=10.0),
            transport=transport,
        ) as client:
            with client.stream("POST", url, json=payload) as resp:
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(
                        f"LLM HTTP {resp.status_code}: {resp.text[:200]}", transient=True
                    )
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = data.get("message", {}) or {}
                    delta = message.get("content") or ""
                    if delta:
                        content_parts.append(delta)
                        yield {"type": "token", "text": delta}
                    if message.get("tool_calls"):
                        tool_calls.extend(_normalize_tool_calls(message))
                    if data.get("prompt_eval_count") is not None:
                        usage["prompt_tokens"] = int(data["prompt_eval_count"])
                    if data.get("eval_count") is not None:
                        usage["completion_tokens"] = int(data["eval_count"])
                    if data.get("done"):
                        break
    except httpx.TimeoutException as e:
        raise LLMError(f"LLM timed out: {e}", transient=True) from e
    except httpx.HTTPError as e:
        raise LLMError(f"LLM HTTP error: {e}", transient=True) from e

    content = "".join(content_parts)
    yield {"type": "tool_calls", "tool_calls": tool_calls, "content": content}
    yield {"type": "usage", "usage": usage, "content": content}
    yield {"type": "done"}


def llm_chat_safe(
    messages: list[dict[str, str]],
    model: str,
    ollama_url: str,
    *,
    error_prefix: str = "[LLM error",
    retries: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """llm_chat that never raises; errors come back as content.

    Transient failures (timeouts, HTTP 5xx/429) are retried with a short
    backoff; permanent errors surface immediately as content.
    """
    from palimind.settings import LLM_RETRIES

    if retries is None:
        retries = LLM_RETRIES
    attempt = 0
    while True:
        try:
            return llm_chat(messages, model, ollama_url, **kwargs)
        except LLMError as e:
            if e.transient and attempt < retries:
                attempt += 1
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 4.0))
                continue
            return {"content": f"{error_prefix}: {e}]", "tool_calls": [], "usage": {}}


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
