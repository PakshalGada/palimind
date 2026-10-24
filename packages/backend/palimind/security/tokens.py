"""Per-user secrets for Palimind's local services.

Secrets are generated once, stored with ``0600`` permissions under
``~/.palimind`` (or ``PALIMIND_HOME``) and can be overridden with environment
variables.  They are deliberately *not* compiled into the app: every install
gets its own value, and rotating a secret only requires deleting its file.
"""

from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path

_TOKEN_BYTES = 32

_API_ENV = "PALIMIND_API_TOKEN"
_PROXY_ENV = "OPENCODE_PROXY_TOKEN"


def palimind_home() -> Path:
    """Return the per-user Palimind state directory."""
    override = os.environ.get("PALIMIND_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".palimind"


def token_file(name: str) -> Path:
    return palimind_home() / f"{name}_token"


def _read_token_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def get_or_create_token(name: str, env_var: str) -> str:
    """Return the secret for *name*, creating it on first use.

    Order of precedence: environment variable → existing ``0600`` file →
    freshly generated value.
    """
    env_value = os.environ.get(env_var, "").strip()
    if env_value:
        return env_value

    path = token_file(name)
    existing = _read_token_file(path)
    if existing:
        # Repair overly permissive permissions from older installs.
        try:
            if path.stat().st_mode & 0o077:
                os.chmod(path, 0o600)
        except OSError:
            pass
        return existing

    value = secrets.token_urlsafe(_TOKEN_BYTES)
    try:
        _atomic_write(path, value)
    except OSError:
        # Read-only home / container: the in-memory value still protects this
        # process, but callers that need the value elsewhere must use the env
        # var instead.
        pass
    return value


def get_api_token() -> str:
    """Bearer token required by the local FastAPI server."""
    return get_or_create_token("api", _API_ENV)


def get_proxy_token() -> str:
    """Per-install secret required by the OpenCode proxy."""
    return get_or_create_token("opencode_proxy", _PROXY_ENV)


def auth_disabled() -> bool:
    """Explicit opt-out used by tests and advanced local-only setups."""
    raw = os.environ.get("PALIMIND_AUTH_DISABLED", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def allow_remote() -> bool:
    """Whether non-loopback clients may reach the API (Docker deployments)."""
    raw = os.environ.get("PALIMIND_ALLOW_REMOTE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")
