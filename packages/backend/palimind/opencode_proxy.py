"""OpenCode proxy: translates Ollama-style API calls into OpenAI-compatible calls.

Palimind's internals speak the Ollama wire format (see packages/backend/palimind/generative/responder.py
and packages/backend/palimind/llm/stream.py, which parse NDJSON lines of shape
``{"message": {"role": ..., "content": ...}}``). This FastAPI app accepts those
Ollama-style requests on localhost and forwards them to an OpenAI-compatible
endpoint (https://opencode.ai/zen/go/v1) with Bearer auth, converting payloads
and streaming responses in both directions.

Run with: ``python3 -m palimind.opencode_proxy``
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11435

BASE_URL = os.environ.get("OPENCODE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
PROXY_HOST = os.environ.get("OPENCODE_PROXY_HOST", DEFAULT_HOST)
try:
    PROXY_PORT = int(os.environ.get("OPENCODE_PROXY_PORT", str(DEFAULT_PORT)))
except ValueError:
    PROXY_PORT = DEFAULT_PORT

UPSTREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Manually parse a .env file of KEY=VALUE lines (no python-dotenv)."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _load_api_key() -> str | None:
    """Resolve the OpenCode API key.

    Order: OPENCODE_API_KEY env var → repo-root .env → the global OpenCode
    CLI auth.json (via palimind.opencode.auth, e.g.
    ~/.local/share/opencode/auth.json).
    """
    key = os.environ.get("OPENCODE_API_KEY")
    if key:
        return key
    key = _parse_dotenv(_REPO_ROOT / ".env").get("OPENCODE_API_KEY")
    if key:
        return key
    try:
        # Lazy import: keeps proxy startup cheap and never fails hard if the
        # global auth store is unavailable or unreadable.
        from palimind.opencode.auth import get_key

        return get_key("opencode")
    except Exception:
        return None


def _auth_headers() -> dict[str, str]:
    key = _load_api_key()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def _upstream_headers(client_headers: dict | None = None) -> dict[str, str]:
    """Headers for upstream OpenCode Go requests.

    Always includes ``x-opencode-session``: the value passed in by the caller
    (per-conversation) when present, otherwise a stable per-process id. This
    header is required by OpenCode Go.
    """
    from palimind.opencode.session import SESSION_HEADER, opencode_session_id

    headers = _auth_headers()
    session = (client_headers or {}).get(SESSION_HEADER)
    headers[SESSION_HEADER] = session or opencode_session_id()
    return headers


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="opencode-proxy")

_embedder = None  # lazy singleton for sentence-transformers model


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        model_name = os.environ.get("PALIMIND_LOCAL_EMBED_MODEL", "all-MiniLM-L6-v2")
        _embedder = SentenceTransformer(model_name)
    return _embedder


_models_cache: list[str] | None = None


async def _fetch_model_ids(client: httpx.AsyncClient) -> list[str]:
    """Fetch and cache available model ids from the upstream /models endpoint."""
    global _models_cache
    if _models_cache is None:
        resp = await client.get(f"{BASE_URL}/models", headers=_upstream_headers())
        resp.raise_for_status()
        data = resp.json()
        _models_cache = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    return _models_cache


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""
    images: list[str] | None = None


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False


class EmbedRequest(BaseModel):
    input: str | list[str]
    model: str = ""


class GenerateRequest(BaseModel):
    model: str
    prompt: str
    images: list[str] | None = None


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _to_openai_messages(messages: list[ChatMessage]) -> list[dict]:
    """Convert Ollama-style messages to OpenAI-style messages.

    Messages carrying base64 images become multimodal content parts:
    [{type: text}, {type: image_url, image_url: {url: data:image/png;base64,...}}]
    """
    out: list[dict] = []
    for msg in messages:
        if msg.images:
            parts: list[dict] = [{"type": "text", "text": msg.content}]
            for b64 in msg.images:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    }
                )
            out.append({"role": msg.role, "content": parts})
        else:
            out.append({"role": msg.role, "content": msg.content})
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "upstream": BASE_URL,
        "key_loaded": bool(_load_api_key()),
    }


@app.get("/api/tags")
async def api_tags():
    """Ollama-style model listing backed by the OpenAI-compatible /models."""
    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            resp = await client.get(f"{BASE_URL}/models", headers=_upstream_headers())
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return JSONResponse({"models": []})

    models = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        models.append(
            {
                "name": mid,
                "model": mid,
                "size": 0,
                "digest": "",
                "details": {"family": "", "parameter_size": ""},
            }
        )
    return {"models": models}


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    openai_messages = _to_openai_messages(req.messages)
    payload = {
        "model": req.model,
        "messages": openai_messages,
        "stream": req.stream,
    }

    if not req.stream:
        try:
            async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
                resp = await client.post(
                    f"{BASE_URL}/chat/completions",
                    json=payload,
                    headers=_upstream_headers(req.headers),
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {e}") from e

        content = ""
        choices = data.get("choices") or []
        if choices:
            content = (choices[0].get("message") or {}).get("content", "")
        return {
            "model": req.model,
            "message": {"role": "assistant", "content": content},
            "done": True,
        }

    # Streaming: convert upstream SSE to NDJSON Ollama-style lines.
    async def ndjson_stream():
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{BASE_URL}/chat/completions",
                json=payload,
                headers=_upstream_headers(req.headers),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    body = line[len("data:") :].strip()
                    if body == "[DONE]":
                        break
                    try:
                        chunk = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    delta_content = ""
                    if choices:
                        delta = choices[0].get("delta") or {}
                        delta_content = delta.get("content") or delta.get("reasoning_content") or ""
                    if delta_content:
                        yield (
                            json.dumps(
                                {
                                    "model": req.model,
                                    "message": {
                                        "role": "assistant",
                                        "content": delta_content,
                                    },
                                    "done": False,
                                }
                            )
                            + "\n"
                        )
        yield (
            json.dumps(
                {
                    "model": req.model,
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                }
            )
            + "\n"
        )

    return StreamingResponse(ndjson_stream(), media_type="application/x-ndjson")


@app.post("/api/embed")
async def api_embed(req: EmbedRequest):
    inputs = req.input if isinstance(req.input, list) else [req.input]
    try:
        embedder = _get_embedder()
        vectors = embedder.encode(inputs, show_progress_bar=False)
        embeddings = [[float(x) for x in vec] for vec in vectors]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding error: {e}") from e
    return {"model": req.model, "embeddings": embeddings}


@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    # Resolve model: fall back to vision model when the requested one is unknown.
    used_model = req.model
    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            known_ids = await _fetch_model_ids(client)
    except Exception:
        known_ids = []
    if req.model not in known_ids:
        used_model = os.environ.get("OPENCODE_VISION_MODEL", "ox-alpha-free")

    content_parts: list[dict] = [{"type": "text", "text": req.prompt}]
    for b64 in req.images or []:
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    payload = {
        "model": used_model,
        "messages": [{"role": "user", "content": content_parts}],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                json=payload,
                headers=_upstream_headers(req.headers),
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}") from e

    content = ""
    choices = data.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content", "")
    return {"model": used_model, "response": content, "done": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT)
