"""Computer-use driver boundary.

The Linux AT-SPI client is one implementation.  A macOS/Windows driver can be
added behind this interface without changing the tool schemas or policy.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DesktopDriver(Protocol):
    backend: str

    def status(self) -> dict[str, Any]: ...

    def list_apps(self) -> list[dict[str, Any]]: ...

    def snapshot(self, app: str = "", window_id: str = "", **kwargs: Any) -> dict[str, Any]: ...

    def act(self, action: str, **kwargs: Any) -> dict[str, Any]: ...

    def screenshot(self, path: str = "") -> dict[str, Any]: ...

    def release_input(self) -> None: ...


class NativeDesktopDriver:
    """Adapter over the existing ``palimind-desktop`` client."""

    backend = "linux-atspi"

    def __init__(self) -> None:
        from .client import get_client

        self.client = get_client()

    def status(self) -> dict[str, Any]:
        return {"backend": self.backend, "available": True}

    def list_apps(self) -> list[dict[str, Any]]:
        result = self.client.apps()
        apps = result.get("apps") if isinstance(result, dict) else result
        return list(apps or [])

    def snapshot(self, app: str = "", window_id: str = "", **kwargs: Any) -> dict[str, Any]:
        return self.client.snapshot(app=app, window_id=window_id, **kwargs)

    def act(self, action: str, **kwargs: Any) -> dict[str, Any]:
        return self.client.act(action=action, **kwargs)

    def screenshot(self, path: str = "") -> dict[str, Any]:
        return self.client.screenshot(path=path) if path else self.client.screenshot()

    def release_input(self) -> None:
        self.client.stop()


_driver: DesktopDriver | None = None


def get_driver() -> DesktopDriver:
    global _driver
    if _driver is None:
        _driver = NativeDesktopDriver()
    return _driver


def set_driver(driver: DesktopDriver | None) -> None:
    """Test seam: install a fake driver."""
    global _driver
    _driver = driver
