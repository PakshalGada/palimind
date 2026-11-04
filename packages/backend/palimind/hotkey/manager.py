"""Global hotkey capture for ``pm hotkey``.

This module is intentionally small and optional: ``pynput`` is only imported
when a listener is actually started, so ``pm`` works without the ``[hotkey]``
extra. Captured text is sent to the authenticated local API.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HotkeyConfig:
    hotkey_combo: str = "ctrl+shift+e"
    api_base_url: str = "http://127.0.0.1:8000"
    field_path: str | None = None
    timeout_s: float = 10.0


@dataclass
class CaptureEvent:
    selected_field: SimpleNamespace
    selected_text: str
    response: dict[str, Any] = field(default_factory=dict)


def _api_token() -> str:
    try:
        from palimind.security.tokens import get_api_token

        return get_api_token()
    except Exception:
        return ""


def _request(
    url: str, *, method: str = "GET", payload: dict | None = None, timeout: float = 10.0
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    token = _api_token()
    if token:
        req.add_header("X-Palimind-Token", token)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


_KEY_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "option": "alt",
    "opt": "alt",
    "win": "cmd",
    "windows": "cmd",
    "super": "cmd",
    "meta": "cmd",
    "command": "cmd",
    "return": "enter",
    "escape": "esc",
}


def to_pynput_combo(combo: str) -> str:
    """Convert ``ctrl+shift+e`` into pynput's ``<ctrl>+<shift>+e`` syntax.

    ``pynput.keyboard.GlobalHotKeys`` only accepts named keys wrapped in angle
    brackets; the CLI's documented format (and its default) raised
    ``ValueError: ctrl`` so the listener never started.
    """
    parts = []
    for raw in combo.split("+"):
        key = raw.strip().lower()
        if not key:
            continue
        if len(key) > 1 and not (key.startswith("<") and key.endswith(">")):
            key = f"<{_KEY_ALIASES.get(key, key)}>"
        parts.append(key)
    return "+".join(parts)


class HotkeyManager:
    """Listen for a global shortcut and capture the current clipboard text."""

    def __init__(self, config: HotkeyConfig | None = None) -> None:
        self.config = config or HotkeyConfig()
        self.event_callback: Callable[[CaptureEvent], None] | None = None
        self._listener: Any = None
        self._lock = threading.Lock()

    # ── capture ────────────────────────────────────────────────────────
    def _capture(self) -> CaptureEvent | None:
        try:
            import pyperclip
        except ImportError as exc:  # pragma: no cover - depends on extra
            raise ImportError("pyperclip is required for hotkey capture") from exc

        text = str(pyperclip.paste() or "").strip()
        if not text:
            logger.warning("Hotkey pressed but the clipboard is empty")
            return None

        fields_payload = _request(
            f"{self.config.api_base_url.rstrip('/')}/api/fields", timeout=self.config.timeout_s
        )
        fields = fields_payload.get("fields") or []
        active = fields_payload.get("active_field")
        path = self.config.field_path or active or (fields[0] if fields else "")
        if not path:
            logger.warning("No Palimind field is configured")
            return None

        response = _request(
            f"{self.config.api_base_url.rstrip('/')}/api/select",
            method="POST",
            payload={"path": path, "text": text},
            timeout=self.config.timeout_s,
        )
        event = CaptureEvent(
            selected_field=SimpleNamespace(name=str(path).rstrip("/").split("/")[-1], path=path),
            selected_text=text,
            response=response,
        )
        callback = self.event_callback
        if callback is not None:
            try:
                callback(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Hotkey callback failed: %s", exc)
        return event

    def _safe_capture(self) -> None:
        try:
            self._capture()
        except Exception as exc:  # noqa: BLE001 - background thread: log, don't crash
            logger.warning("Hotkey capture failed: %s", exc)

    def _on_hotkey_pressed(self, sync: bool = False) -> CaptureEvent | None:
        if sync:
            return self._capture()
        threading.Thread(target=self._safe_capture, daemon=True).start()
        return None

    # ── lifecycle ──────────────────────────────────────────────────────
    def start(self, callback: Callable[[CaptureEvent], None] | None = None) -> None:
        try:
            from pynput import keyboard
        except ImportError as exc:  # pragma: no cover - depends on extra
            raise ImportError(
                "pynput is required for the global hotkey listener; install with "
                "'pip install -e \".[hotkey]\"'"
            ) from exc

        if callback is not None:
            self.event_callback = callback
        with self._lock:
            if self._listener is not None:
                return
            self._listener = keyboard.GlobalHotKeys(
                {to_pynput_combo(self.config.hotkey_combo): self._on_hotkey_pressed}
            )
            self._listener.start()

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            self._listener = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass


__all__ = ["CaptureEvent", "HotkeyConfig", "HotkeyManager", "to_pynput_combo"]
