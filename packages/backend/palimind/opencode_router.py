"""OpenCode model routing for the main API server.

Palimind's chat stack speaks the Ollama wire format to ``ollama_url``. The
OpenCode proxy (``palimind.opencode_proxy``, port 11435) exposes OpenCode Zen
models on that same wire format, so the app can use cloud models without
touching the LLM call sites.

This module:
  - lazily starts the proxy as a sidecar when an OpenCode API key exists,
  - lists OpenCode models (Ollama-style entries with provider "opencode"),
  - resolves whether a given model id must be served by the proxy.

All HTTP here is blocking (``urllib``) and guarded by a lock so it can be
called from both async handlers and sync worker threads without tripping
over a running event loop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

PROXY_URL = os.environ.get("OPENCODE_PROXY_URL", "http://127.0.0.1:11435").rstrip("/")
OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1").rstrip("/")

_REPO_ROOT = Path(__file__).resolve().parent.parent

_models_cache: list[dict] | None = None
_cache_lock = threading.Lock()
_proxy_started = False


def _proxy_alive() -> bool:
    """Return True if the OpenCode proxy is reachable on its port."""
    try:
        req = urllib.request.Request(f"{PROXY_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _key_configured() -> bool:
    try:
        from palimind.opencode_auth import get_key

        return bool(get_key("opencode"))
    except Exception:
        return False


def ensure_proxy() -> bool:
    """Start the OpenCode proxy sidecar if a key exists and it is not running.

    Non-fatal: returns True when the proxy is (now) reachable. A missing key
    or a failed spawn simply returns False.
    """
    global _proxy_started
    if _proxy_alive():
        return True
    if not _key_configured():
        return False
    if _proxy_started:
        return False
    _proxy_started = True
    try:
        log = open(str(_REPO_ROOT / ".opencode-proxy.log"), "ab")
        subprocess.Popen(
            [sys.executable, "-m", "palimind.opencode_proxy"],
            cwd=str(_REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as e:
        print(f"[opencode] failed to start proxy: {e}")
    return False


def _get_json(url: str, headers: dict | None = None, timeout: int = 8) -> dict | None:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "Palimind/2.0")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" in ctype:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[opencode] GET failed ({url}): {e}")
        return None


def _from_ollama_tags(data: dict) -> list[dict]:
    out = []
    for m in data.get("models", []):
        mid = m.get("model") or m.get("name", "")
        if not mid:
            continue
        out.append(
            {
                "model_id": mid,
                "display_name": mid,
                "family": "",
                "parameter_size": "",
                "size_gb": 0,
                "provider": "opencode",
            }
        )
    return out


def _fetch_sync() -> list[dict]:
    """Blocking fetch of OpenCode models (proxy first, then direct Zen)."""
    models: list[dict] = []
    if ensure_proxy():
        data = _get_json(f"{PROXY_URL}/api/tags")
        if data:
            models = _from_ollama_tags(data)

    if not models:
        from palimind.opencode_auth import get_key

        key = get_key("opencode")
        if key:
            data = _get_json(
                f"{OPENCODE_BASE_URL}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            if data:
                models = [
                    {
                        "model_id": m.get("id", ""),
                        "display_name": m.get("id", ""),
                        "family": "",
                        "parameter_size": "",
                        "size_gb": 0,
                        "provider": "opencode",
                    }
                    for m in data.get("data", [])
                    if m.get("id")
                ]
    return models


def list_opencode_models() -> list[dict]:
    """Return OpenCode models as Ollama-style entries (provider 'opencode')."""
    global _models_cache
    with _cache_lock:
        if _models_cache is None or (_models_cache == [] and _key_configured()):
            _models_cache = _fetch_sync()
        return list(_models_cache)


def opencode_model_ids() -> set[str]:
    return {m["model_id"] for m in list_opencode_models()}


def reset_cache() -> None:
    global _models_cache
    with _cache_lock:
        _models_cache = None


def resolve_model_url(model_id: str, default_ollama_url: str) -> str:
    """Return the backend URL that can serve *model_id*.

    OpenCode model ids are routed to the proxy; everything else stays on the
    configured Ollama instance.
    """
    if model_id and model_id in opencode_model_ids():
        return PROXY_URL
    return default_ollama_url


def fetch_ollama_model_ids(ollama_url: str, timeout: int = 8) -> set[str]:
    """Return the model ids served by an Ollama-compatible endpoint.

    Tries the configured URL first, then falls back to the local Ollama
    instance (``http://localhost:11434``) when the configured URL is remote
    or unreachable.
    """
    base = (ollama_url or "http://localhost:11434").rstrip("/")
    candidates = [base]
    if "localhost" not in base and "127.0.0.1" not in base:
        candidates.append("http://localhost:11434")

    ids: set[str] = set()
    for url in candidates:
        data = _get_json(f"{url}/api/tags", timeout=timeout)
        if not data:
            continue
        for m in data.get("models", []) or []:
            mid = m.get("name") or m.get("model", "")
            if mid:
                ids.add(mid)
        if ids:
            break
    return ids


def available_model_ids(ollama_url: str) -> set[str]:
    """Every model id the app can serve: local Ollama + OpenCode proxy."""
    return fetch_ollama_model_ids(ollama_url) | opencode_model_ids()
