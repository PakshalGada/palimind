"""Global OpenCode provider-auth storage, shared with the OpenCode CLI.

The OpenCode CLI stores provider credentials globally in
``~/.local/share/opencode/auth.json`` (or ``$XDG_DATA_HOME/opencode/auth.json``
when XDG_DATA_HOME is set). The file maps provider names to credential
entries::

    {
        "opencode": {"type": "api", "key": "..."},
        "openrouter": {"type": "api", "key": "..."}
    }

Palimind reads and writes the same file so a key pasted once in the Settings
UI is picked up automatically by both the OpenCode CLI and Palimind's proxy
(``palimind.opencode_proxy``). Sibling provider entries are always preserved,
writes are atomic (tmp file + ``os.replace``), and the file is chmod'ed
0o600 where the platform supports it. Full keys are never logged.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

__all__ = ["auth_path", "get_key", "set_key", "remove_key", "masked_preview"]

_AUTH_RELATIVE = Path("opencode") / "auth.json"


def auth_path() -> Path:
    """Resolve the global ``auth.json`` path used for BOTH reads and writes.

    ``$XDG_DATA_HOME/opencode/auth.json`` when XDG_DATA_HOME is set, else
    ``~/.local/share/opencode/auth.json``. The same canonical path is used on
    every platform (including Windows): modern OpenCode resolves its data
    directory through the XDG convention everywhere, so reads and writes must
    always target one file. Reads consult XDG_DATA_HOME/HOME at call time so
    tests can redirect the location via ``monkeypatch.setenv``.
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / _AUTH_RELATIVE
    return Path.home() / ".local" / "share" / _AUTH_RELATIVE


def _load_entries(path: Path) -> dict:
    """Load the raw auth.json mapping from *path*.

    Returns ``{}`` only when the file does not exist. Raises OSError when an
    existing file cannot be read (permissions, ...) and ValueError when it
    contains invalid JSON or is not a JSON object — callers that would rewrite
    the file must surface these instead of silently clobbering it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise OSError(f"cannot read {path}: {e}") from e
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(
            f"{path} contains invalid JSON ({e}); fix or remove the file "
            "manually to avoid losing existing provider credentials"
        ) from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def get_key(provider: str = "opencode") -> str | None:
    """Return the stored API key for *provider*, or None.

    Returns None when the file or the entry is missing. Accepts entries whose
    ``type`` is ``"api"`` as well as any entry that simply carries a non-empty
    ``key`` field. Raises OSError when an existing auth file is unreadable and
    ValueError when it contains invalid JSON or is not a JSON object, so
    callers can distinguish "no key configured" from a broken store (wrap in
    try/except if silent degradation is desired).
    """
    data = _load_entries(auth_path())
    entry = data.get(provider)
    if not isinstance(entry, dict):
        return None
    key = entry.get("key")
    if isinstance(key, str) and key:
        return key
    return None


def _atomic_write_json(target: Path, data: dict) -> None:
    """Write *data* to *target* atomically with 0o600 permissions."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".auth-", suffix=".json.tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp_path, 0o600)  # no-op/limited on some platforms (Windows)
        except OSError:
            pass
        os.replace(tmp_path, target)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def set_key(key: str, provider: str = "opencode") -> None:
    """Store *key* for *provider* in the global auth file.

    Preserves every other existing entry untouched and writes atomically to
    the canonical path. Raises ValueError for empty/whitespace-only keys and
    when an existing auth file contains invalid JSON or is not a JSON object;
    raises OSError when an existing file cannot be read. The file is never
    silently overwritten in any of those cases.
    """
    if not isinstance(key, str) or not key.strip():
        raise ValueError("API key must be a non-empty string")
    entries = _load_entries(auth_path())
    entries[provider] = {"type": "api", "key": key}
    _atomic_write_json(auth_path(), entries)


def remove_key(provider: str = "opencode") -> bool:
    """Remove *provider*'s entry from the global auth file.

    Returns True when an entry was removed, False when the file or the entry
    is absent. Other entries are preserved; the write is atomic. Raises
    ValueError on invalid/non-object JSON and OSError on unreadable files
    rather than silently overwriting the file.
    """
    source = auth_path()
    if not source.exists():
        return False
    entries = _load_entries(source)  # raises ValueError/OSError on broken files
    if provider not in entries:
        return False
    del entries[provider]
    _atomic_write_json(source, entries)
    return True


def masked_preview(key: str) -> str:
    """Return a safe display fragment, e.g. ``"…abc4"``.

    Empty string when the key is shorter than 4 characters.
    """
    if len(key) < 4:
        return ""
    return "…" + key[-4:]
