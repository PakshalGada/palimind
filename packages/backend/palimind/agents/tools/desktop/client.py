"""stdio JSON-RPC client for the ``palimind-desktop`` daemon.

The daemon is a same-user child of the Python backend. It keeps the AT-SPI
connection, the interaction lease and snapshot refs in memory, and exposes a
stop switch. Requests and responses are newline-delimited JSON.

This module owns process lifecycle only: policy, approvals and formatting live
in ``tool.py`` / ``schema.py``. The native layer re-checks the same policy, so a
compromised Python layer cannot widen the app allowlist.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

_DEFAULT_TIMEOUT = 30.0
_START_TIMEOUT = 10.0
_MAX_RESTARTS = 2


class DesktopError(RuntimeError):
    """The native layer could not be started or stopped responding."""


def _repo_root() -> Path | None:
    here = Path(__file__).resolve()
    # .../packages/backend/palimind/agents/tools/desktop/client.py
    for parent in here.parents:
        if (parent / "packages" / "desktop-native").is_dir():
            return parent
    return None


def resolve_binary(explicit: str | None = None) -> Path | None:
    """Locate ``palimind-desktop``.

    Order: explicit argument, ``PALIMIND_DESKTOP_BIN``, the bundled resource
    path, the development Cargo target directories, then ``PATH``.
    """

    candidates: list[Path] = []
    for value in (explicit, os.environ.get("PALIMIND_DESKTOP_BIN")):
        if value:
            candidates.append(Path(value).expanduser())

    root = _repo_root()
    if root is not None:
        candidates.extend(
            [
                root / "apps" / "desktop" / "src-tauri" / "binaries" / "palimind-desktop",
                root / "packages" / "desktop-native" / "target" / "release" / "palimind-desktop",
                root / "packages" / "desktop-native" / "target" / "debug" / "palimind-desktop",
            ]
        )

    cargo_target = os.environ.get("CARGO_TARGET_DIR")
    if cargo_target:
        for profile in ("release", "debug"):
            candidates.append(Path(cargo_target) / profile / "palimind-desktop")
    home = Path.home()
    for profile in ("release", "debug"):
        candidates.append(
            home / ".local" / "tauri-libs" / "cargo-target" / profile / "palimind-desktop"
        )

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    found = shutil.which("palimind-desktop")
    return Path(found) if found else None


def _policy_env(allowed_apps: tuple[str, ...] | None = None) -> dict[str, str]:
    from palimind import settings

    env = dict(os.environ)
    env.setdefault("PALIMIND_DESKTOP_ENABLE", "true" if settings.DESKTOP_ENABLE else "false")
    env.setdefault("PALIMIND_DESKTOP_INPUT_BACKEND", settings.DESKTOP_INPUT_BACKEND)
    env.setdefault("PALIMIND_DESKTOP_SCREENSHOT", settings.DESKTOP_SCREENSHOT)
    env.setdefault("PALIMIND_DESKTOP_MAX_NODES", str(settings.DESKTOP_MAX_NODES))
    env.setdefault("PALIMIND_DESKTOP_MAX_DEPTH", str(settings.DESKTOP_MAX_DEPTH))
    env.setdefault("PALIMIND_DESKTOP_ACTION_RATE", str(settings.DESKTOP_ACTION_RATE))
    env.setdefault(
        "PALIMIND_DESKTOP_ARTIFACT_RETENTION_H",
        str(settings.DESKTOP_ARTIFACT_RETENTION_H),
    )
    effective = list(allowed_apps or settings.DESKTOP_ALLOWED_APPS)
    if effective:
        env["PALIMIND_DESKTOP_ALLOWED_APPS"] = ",".join(effective)
    if settings.DESKTOP_BLOCKED_APPS and "PALIMIND_DESKTOP_BLOCKED_APPS" not in env:
        env["PALIMIND_DESKTOP_BLOCKED_APPS"] = ",".join(settings.DESKTOP_BLOCKED_APPS)
    if settings.DESKTOP_ALLOW_ALL:
        env["PALIMIND_DESKTOP_ALLOW_ALL"] = "1"
    return env


class DesktopClient:
    def __init__(
        self,
        binary: str | Path | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        allowed_apps: tuple[str, ...] | None = None,
    ):
        self._explicit_binary = str(binary) if binary else None
        self._timeout = timeout
        # A non-empty per-agent list is the effective native allowlist for this
        # daemon. Protected/blocked apps still win inside the native policy.
        self._allowed_apps = allowed_apps
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.Lock()
        self._request_id = 0
        self._reader: threading.Thread | None = None
        self._restarts = 0

    # ── lifecycle ────────────────────────────────────────────────────────

    @property
    def binary(self) -> Path | None:
        return resolve_binary(self._explicit_binary)

    def _start(self) -> None:
        binary = self.binary
        if binary is None:
            raise DesktopError(
                "palimind-desktop was not found. Build it with "
                "`make desktop-native`, or set PALIMIND_DESKTOP_BIN."
            )
        self._process = subprocess.Popen(
            [str(binary), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=_policy_env(self._allowed_apps),
        )
        self._reader = threading.Thread(
            target=self._read_responses,
            args=(self._process,),
            name="palimind-desktop-reader",
            daemon=True,
        )
        self._reader.start()

    def _read_responses(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._responses.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _ensure_running(self) -> None:
        if self._alive():
            return
        if self._restarts >= _MAX_RESTARTS:
            raise DesktopError("palimind-desktop exited repeatedly; not restarting")
        self._restarts += 1
        self._start()

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    # ── RPC ──────────────────────────────────────────────────────────────

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_running()
            process = self._process
            assert process is not None and process.stdin is not None
            self._request_id += 1
            request_id = self._request_id
            payload = {"id": request_id, "method": method, "params": params or {}}
            try:
                process.stdin.write(json.dumps(payload) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.close()
                raise DesktopError(f"palimind-desktop closed its input: {exc}") from exc

            # Drop stale responses from a previous, killed process before
            # waiting for ours. Responses carry ids; matching is exact.
            deadline = timeout if timeout is not None else self._timeout
            while True:
                try:
                    response = self._responses.get(timeout=deadline)
                except queue.Empty as exc:
                    self.close()
                    raise DesktopError(
                        f"palimind-desktop did not answer '{method}' within {deadline:.0f}s"
                    ) from exc
                if response.get("id") == request_id:
                    self._restarts = 0
                    return response
                # A timed-out request's late answer: ignore and keep waiting.

    def status(self) -> dict[str, Any]:
        return self.call("status", timeout=10)

    def apps(self, kind: str = "windows", app: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"kind": kind}
        if app:
            params["app"] = app
        return self.call("apps", params)

    def snapshot(self, **kwargs: Any) -> dict[str, Any]:
        timeout_ms = int(kwargs.get("timeout_ms") or 0)
        return self.call(
            "snapshot",
            {k: v for k, v in kwargs.items() if v is not None},
            timeout=max(30.0, timeout_ms / 1000.0 + 10.0) if timeout_ms else 30.0,
        )

    def find(self, **kwargs: Any) -> dict[str, Any]:
        return self.call("find", {k: v for k, v in kwargs.items() if v is not None})

    def wait(self, **kwargs: Any) -> dict[str, Any]:
        timeout_ms = int(kwargs.get("timeout_ms") or 5_000)
        return self.call(
            "wait",
            {k: v for k, v in kwargs.items() if v is not None},
            timeout=max(10.0, timeout_ms / 1000.0 + 5.0),
        )

    def act(self, **kwargs: Any) -> dict[str, Any]:
        clean = {k: v for k, v in kwargs.items() if v is not None}
        timeout_ms = int(clean.get("timeout_ms") or 0)
        return self.call(
            "act",
            clean,
            timeout=max(15.0, timeout_ms / 1000.0 + 10.0) if timeout_ms else 20.0,
        )

    def screenshot(self, **kwargs: Any) -> dict[str, Any]:
        return self.call("screenshot", {k: v for k, v in kwargs.items() if v is not None})

    def stop(self) -> dict[str, Any]:
        return self.call("stop", timeout=10)

    def resume(self) -> dict[str, Any]:
        return self.call("resume", timeout=10)

    def audit(self, limit: int = 50) -> dict[str, Any]:
        return self.call("audit", {"limit": limit}, timeout=10)


_clients: dict[tuple[str, ...], DesktopClient] = {}
_client_lock = threading.Lock()


def get_client(allowed_apps: tuple[str, ...] | None = None) -> DesktopClient:
    """Return the daemon for one effective app allowlist.

    Agents with different ``desktop_allowed_apps`` get different daemons so the
    native policy sees exactly the same allowlist the Python gate enforced.
    """

    key = tuple(allowed_apps or ())
    with _client_lock:
        client = _clients.get(key)
        if client is None:
            client = DesktopClient(allowed_apps=allowed_apps)
            _clients[key] = client
            atexit.register(client.close)
        return client


def close_all() -> None:
    with _client_lock:
        for client in _clients.values():
            client.close()
        _clients.clear()
