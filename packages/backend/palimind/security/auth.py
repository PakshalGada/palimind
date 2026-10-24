"""FastAPI middleware enforcing bearer tokens and loopback-only access."""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Callable
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs

from palimind.security.tokens import allow_remote, auth_disabled, get_api_token

COOKIE_NAME = "palimind_token"
_TOKEN_HEADERS = ("x-palimind-token", "x-proxy-token")
_PUBLIC_PATHS = {"/", "/health", "/ready", "/favicon.ico", "/openapi.json", "/docs", "/redoc"}


def _header(scope: dict[str, Any], name: str) -> str:
    for key, value in scope.get("headers", []):
        if key.decode("latin-1").lower() == name:
            return value.decode("latin-1")
    return ""


def _query_token(scope: dict[str, Any]) -> str:
    qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    return (qs.get("token") or [""])[0]


def _cookie_token(scope: dict[str, Any]) -> str:
    raw = _header(scope, "cookie")
    if not raw:
        return ""
    try:
        jar = SimpleCookie()
        jar.load(raw)
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else ""
    except Exception:
        return ""


def extract_token(scope: dict[str, Any]) -> str:
    """Pull a candidate secret from headers, cookie, or query string."""
    auth = _header(scope, "authorization")
    if auth:
        scheme, _, value = auth.partition(" ")
        scheme = scheme.lower()
        if scheme == "bearer" and value.strip():
            return value.strip()
        if scheme == "basic" and value.strip():
            # ``http://<token>@host`` URLs make httpx send Basic auth. Accept
            # the username as the secret so internal clients work unchanged.
            import base64

            try:
                decoded = base64.b64decode(value.strip()).decode("utf-8", "replace")
                return decoded.split(":", 1)[0]
            except Exception:
                return ""
    for name in _TOKEN_HEADERS:
        value = _header(scope, name)
        if value:
            return value.strip()
    cookie = _cookie_token(scope)
    if cookie:
        return cookie
    return _query_token(scope)


def _is_loopback(scope: dict[str, Any]) -> bool:
    client = scope.get("client")
    if not client:
        return True  # in-process ASGI transports
    host = str(client[0])
    if host in ("testclient", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _constant_time_match(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return hmac.compare_digest(candidate.encode(), expected.encode())


class AuthMiddleware:
    """Pure-ASGI authentication + network-boundary middleware.

    * Requires a bearer token for every protected path.
    * Rejects non-loopback clients unless ``PALIMIND_ALLOW_REMOTE=1``.
    * On a UI request, sets an HttpOnly ``palimind_token`` cookie so the
      same-origin browser app (including ``EventSource``) authenticates
      automatically without embedding the secret in JavaScript.
    """

    def __init__(
        self,
        app: Any,
        *,
        token_provider: Callable[[], str],
        protected_prefixes: tuple[str, ...] = ("/api",),
        cookie_path_prefix: str | None = None,
        public_paths: set[str] | None = None,
    ) -> None:
        self.app = app
        self.token_provider = token_provider
        self.protected_prefixes = protected_prefixes
        self.cookie_path_prefix = cookie_path_prefix
        self.public_paths = _PUBLIC_PATHS if public_paths is None else public_paths

    def _protected(self, path: str) -> bool:
        if path in self.public_paths:
            return False
        return any(path == p or path.startswith(p + "/") for p in self.protected_prefixes)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        if not allow_remote() and not _is_loopback(scope):
            await _json_response(send, 403, "Remote access is disabled; use a loopback client.")
            return

        if auth_disabled():
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        token = self.token_provider()
        candidate = extract_token(scope)

        if self._protected(path):
            if not _constant_time_match(candidate, token):
                await _json_response(
                    send,
                    401,
                    "Missing or invalid bearer token. Send 'Authorization: Bearer <token>' "
                    "(token file: ~/.palimind/api_token).",
                )
                return
            await self.app(scope, receive, send)
            return

        # Serve the UI and attach the cookie so subsequent /api requests from
        # the same origin are authenticated.
        if (
            self.cookie_path_prefix
            and path.startswith(self.cookie_path_prefix)
            and scope.get("method", "GET").upper() == "GET"
            # Never hand the token to an unauthenticated remote client. Local
            # desktop clients get it transparently; remote clients must pass
            # ?token=... once.
            and (_is_loopback(scope) or _constant_time_match(candidate, token))
        ):
            set_cookie = True

            async def send_with_cookie(message: dict[str, Any]) -> None:
                if message.get("type") == "http.response.start" and set_cookie:
                    headers = list(message.get("headers", []))
                    headers.append(
                        (
                            b"set-cookie",
                            f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; "
                            "Max-Age=86400".encode("latin-1"),
                        )
                    )
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_with_cookie)
            return

        await self.app(scope, receive, send)


async def _json_response(send: Any, status: int, detail: str) -> None:
    import json

    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def install_auth(
    app: Any,
    *,
    token_provider: Callable[[], str],
    protected_prefixes: tuple[str, ...] = ("/api",),
    cookie_path_prefix: str | None = None,
    public_paths: set[str] | None = None,
) -> None:
    """Wrap *app* with :class:`AuthMiddleware`."""
    app.add_middleware(
        AuthMiddleware,
        token_provider=token_provider,
        protected_prefixes=protected_prefixes,
        cookie_path_prefix=cookie_path_prefix,
        public_paths=public_paths,
    )


async def require_auth(request: Any) -> None:
    """FastAPI dependency for routes that need explicit protection.

    The global middleware already guards ``/api/*``; this helper is available
    for routers mounted elsewhere or tests that want a ``Depends``.
    """
    if auth_disabled():
        return
    candidate = extract_token(request.scope)
    if _constant_time_match(candidate, get_api_token()):
        return
    from fastapi import HTTPException

    raise HTTPException(
        status_code=401,
        detail="Missing or invalid bearer token.",
    )
