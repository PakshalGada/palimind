"""OpenAI-compatible local API.

This lets existing OpenAI clients, editors and scripts use PaliMind's local
Ollama models without a cloud key:

* ``GET  /v1/models``
* ``POST /v1/chat/completions`` (streaming and non-streaming)
* ``POST /v1/embeddings``

The implementation deliberately maps OpenAI message/tool shapes onto Ollama's
wire format and reuses the same local model router and embedding cache as the
rest of the app. Authentication is the same per-install bearer token used by
``/api/*``.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from palimind.config import load_global_config
from palimind.core.embedder import generate_embeddings_batch
from palimind.llm.mixture_of_expert.llm import (
    LLMError,
    llm_chat,
    llm_chat_stream,
)

router = APIRouter(prefix="/v1", tags=["openai"])


def _config() -> dict[str, Any]:
    return load_global_config()


def _ollama_url(config: dict[str, Any] | None = None) -> str:
    cfg = config or _config()
    return str(cfg.get("ollama_base_url") or "http://localhost:11434")


def _error(message: str, *, status: int = 400, code: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": code, "code": code}},
    )


def _models(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = config or _config()
    url = _ollama_url(cfg)
    models: list[dict[str, Any]] = []
    try:
        resp = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=5.0)
        if resp.status_code < 400:
            for item in resp.json().get("models", []):
                mid = item.get("name") or item.get("model") or ""
                if mid:
                    models.append(
                        {
                            "id": mid,
                            "object": "model",
                            "created": 0,
                            "owned_by": "local",
                        }
                    )
    except Exception:
        pass

    try:
        from palimind.opencode.router import list_opencode_models

        seen = {m["id"] for m in models}
        for item in list_opencode_models():
            mid = str(item.get("model_id") or "")
            if mid and mid not in seen:
                models.append({"id": mid, "object": "model", "created": 0, "owned_by": "opencode"})
    except Exception:
        pass

    if not models:
        for mid in (cfg.get("chat_model"), cfg.get("embed_model")):
            if mid:
                models.append(
                    {"id": str(mid), "object": "model", "created": 0, "owned_by": "local"}
                )
    return models


@router.get("/models")
async def list_models():
    return {"object": "list", "data": await asyncio.to_thread(_models)}


@router.get("/models/{model_id:path}")
async def get_model(model_id: str):
    found = next((m for m in await asyncio.to_thread(_models) if m["id"] == model_id), None)
    if found is None:
        return _error(f"model '{model_id}' not found", status=404, code="model_not_found")
    return found


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text") or ""))
                elif part.get("type") == "input_text":
                    parts.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(p for p in parts if p)
    return ""


def _map_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in messages or []:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "user")
        content = _content_text(raw.get("content"))
        if role == "tool":
            tool_id = str(raw.get("tool_call_id") or "")
            prefix = f"Tool result ({tool_id}):" if tool_id else "Tool result:"
            out.append({"role": "user", "content": f"{prefix}\n{content}"})
            continue
        if role not in ("system", "user", "assistant"):
            role = "user"
        message: dict[str, Any] = {"role": role, "content": content}
        tool_calls = raw.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            mapped: list[dict[str, Any]] = []
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"_raw": args}
                if not isinstance(args, dict):
                    args = {}
                mapped.append(
                    {
                        "function": {
                            "name": str(fn.get("name") or ""),
                            "arguments": args,
                        }
                    }
                )
            if mapped:
                message["tool_calls"] = mapped
        out.append(message)
    return out


def _map_tools(tools: Any, tool_choice: Any) -> list[dict[str, Any]] | None:
    if str(tool_choice or "") == "none":
        return None
    if not isinstance(tools, list):
        return None
    mapped: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        fn = tool.get("function") or {}
        name = str(fn.get("name") or "")
        if not name:
            continue
        mapped.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(fn.get("description") or ""),
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return mapped or None


def _tool_calls(result: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for call in result.get("tool_calls") or []:
        name = str(call.get("name") or "")
        if not name:
            continue
        calls.append(
            {
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
                },
            }
        )
    return calls


def _completion(
    *,
    completion_id: str,
    model: str,
    created: int,
    content: str,
    tool_calls: list[dict[str, Any]],
    finish_reason: str,
    usage: dict[str, int],
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "message": message, "logprobs": None, "finish_reason": finish_reason}
        ],
        "usage": usage,
    }


def _usage(result: dict[str, Any]) -> dict[str, int]:
    raw = result.get("usage") or {}
    prompt = int(raw.get("prompt_tokens", 0) or 0)
    completion = int(raw.get("completion_tokens", 0) or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _resolve(model: str, cfg: dict[str, Any]) -> tuple[str, str]:
    from palimind.opencode.router import resolve_model_url

    chosen = model or str(cfg.get("chat_model") or "llama3")
    url = resolve_model_url(chosen, _ollama_url(cfg))
    return chosen, url


@router.post("/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body")
    if not isinstance(body, dict):
        return _error("body must be a JSON object")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return _error("'messages' must be a non-empty array")

    cfg = _config()
    model, url = _resolve(str(body.get("model") or ""), cfg)
    mapped_messages = _map_messages(messages)
    tools = _map_tools(body.get("tools"), body.get("tool_choice"))
    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens") or body.get("max_completion_tokens")
    response_format = body.get("response_format")
    fmt = (
        "json"
        if isinstance(response_format, dict)
        and response_format.get("type")
        in (
            "json_object",
            "json_schema",
        )
        else None
    )
    stream = bool(body.get("stream"))
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    kwargs: dict[str, Any] = {
        "tools": tools,
        "temperature": float(temperature) if temperature is not None else None,
        "num_predict": int(max_tokens) if max_tokens is not None else None,
        "format": fmt,
        "num_ctx": int(cfg.get("num_ctx") or 8192),
    }

    if not stream:
        try:
            result = await asyncio.to_thread(llm_chat, mapped_messages, model, url, **kwargs)
        except LLMError as exc:
            return _error(str(exc), status=502, code="upstream_error")
        tool_calls = _tool_calls(result)
        return _completion(
            completion_id=completion_id,
            model=model,
            created=created,
            content=str(result.get("content") or ""),
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=_usage(result),
        )

    return StreamingResponse(
        _stream_chunks(
            completion_id=completion_id,
            model=model,
            created=created,
            messages=mapped_messages,
            url=url,
            kwargs=kwargs,
            include_usage=bool(
                isinstance(body.get("stream_options"), dict)
                and body["stream_options"].get("include_usage")
            ),
        ),
        media_type="text/event-stream",
    )


async def _stream_chunks(
    *,
    completion_id: str,
    model: str,
    created: int,
    messages: list[dict[str, Any]],
    url: str,
    kwargs: dict[str, Any],
    include_usage: bool,
):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def worker() -> None:
        try:
            for event in llm_chat_stream(messages, model, url, **kwargs):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:  # noqa: BLE001 - delivered as an error frame
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "end"})

    threading.Thread(target=worker, name="openai-stream", daemon=True).start()

    def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    yield chunk({"role": "assistant", "content": ""})

    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}
    try:
        while True:
            event = await queue.get()
            etype = event.get("type")
            if etype == "token":
                text = str(event.get("text") or "")
                if text:
                    yield chunk({"content": text})
            elif etype == "tool_calls":
                tool_calls = event.get("tool_calls") or []
            elif etype == "usage":
                usage = event.get("usage") or {}
            elif etype == "error":
                yield f"data: {json.dumps({'error': {'message': event.get('message'), 'type': 'upstream_error'}})}\n\n"
                yield "data: [DONE]\n\n"
                return
            elif etype in ("done", "end"):
                break
    finally:
        # Ensure the worker thread is not left waiting on a client disconnect.
        pass

    if tool_calls:
        mapped = _tool_calls({"tool_calls": tool_calls})
        yield chunk(
            {"tool_calls": [{"index": i, **call} for i, call in enumerate(mapped)]},
            finish="tool_calls",
        )
    else:
        yield chunk({}, finish="stop")
    if include_usage:
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        yield (
            "data: "
            + json.dumps(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": prompt,
                        "completion_tokens": completion,
                        "total_tokens": prompt + completion,
                    },
                }
            )
            + "\n\n"
        )
    yield "data: [DONE]\n\n"


@router.post("/embeddings")
async def embeddings(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body")
    if not isinstance(body, dict):
        return _error("body must be a JSON object")
    raw_input = body.get("input")
    if isinstance(raw_input, str):
        texts = [raw_input]
    elif isinstance(raw_input, list) and all(isinstance(x, str) for x in raw_input):
        texts = [str(x) for x in raw_input]
    else:
        return _error("'input' must be a string or an array of strings")
    if not texts:
        return _error("'input' must not be empty")

    cfg = _config()
    model = str(body.get("model") or cfg.get("embed_model") or "bge-m3")
    try:
        vectors = await asyncio.to_thread(generate_embeddings_batch, texts, _ollama_url(cfg), model)
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc), status=502, code="upstream_error")

    prompt_tokens = sum(max(1, len(t) // 4) for t in texts)
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": vector, "index": i}
            for i, vector in enumerate(vectors)
        ],
        "model": model,
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }
