"""Helpers for authenticating internal calls to the OpenCode proxy.

The proxy speaks the Ollama wire format, so the chat/embedding stack treats it
like another Ollama base URL. These helpers add the per-install proxy bearer
token only when the destination is the proxy, leaving local Ollama untouched.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse


def _proxy_origin() -> tuple[str, int] | None:
    raw = os.environ.get("OPENCODE_PROXY_URL", "http://127.0.0.1:11435")
    try:
        parsed = urlparse(raw)
        if not parsed.hostname:
            return None
        return parsed.hostname, int(parsed.port or 80)
    except (TypeError, ValueError):
        return None


def proxy_auth_headers(url: str) -> dict[str, str]:
    """Return an Authorization header when *url* targets the OpenCode proxy."""
    try:
        parsed = urlparse(url)
        origin = _proxy_origin()
        if origin is None or not parsed.hostname:
            return {}
        port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
        if (parsed.hostname, port) != origin:
            return {}
        from palimind.security.tokens import get_proxy_token

        return {"Authorization": f"Bearer {get_proxy_token()}"}
    except Exception:
        return {}
