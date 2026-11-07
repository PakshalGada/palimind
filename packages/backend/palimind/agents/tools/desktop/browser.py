"""Chrome DevTools Protocol route for Chromium web content.

AT-SPI exposes Chromium's browser chrome reliably, but its web-content refs are
often tokenless and cannot be proven unique after a capture. The reference
project routes Chromium/Electron web content through CDP for exactly this
reason; Palimind uses the same split:

* AT-SPI: window, menu, dialog and page *observation* (roles, names, bounds).
* CDP: page *actions* (click, fill, evaluate) when the page target is
  available.

The CDP route is explicit, not a silent fallback: the tool layer says so and
the benchmark counts it as the browser/CDP route.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

CHROME_CANDIDATES = [
    Path.home() / ".cache" / "ms-playwright" / "chromium-1248" / "chrome-linux64" / "chrome",
    Path.home() / ".cache" / "ms-playwright" / "chromium-1200" / "chrome-linux64" / "chrome",
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/chromium-browser"),
]


class CDPError(RuntimeError):
    pass


def find_chrome() -> Path | None:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            import os

            if os.access(candidate, os.X_OK):
                return candidate
    return None


class BrowserCDP:
    """Minimal synchronous CDP client over a page target's WebSocket."""

    def __init__(self, port: int = 9222, host: str = "127.0.0.1", timeout: float = 10.0):
        self.port = port
        self.host = host
        self.timeout = timeout
        self._socket = None
        self._next_id = 0
        self._target: dict[str, Any] | None = None

    # ── discovery ────────────────────────────────────────────────────────

    def _endpoint(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    def targets(self) -> list[dict[str, Any]]:
        try:
            response = httpx.get(self._endpoint("/json/list"), timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            raise CDPError(f"cannot reach Chromium DevTools on port {self.port}: {exc}") from exc
        if response.status_code != 200:
            raise CDPError(f"DevTools list returned HTTP {response.status_code}")
        return response.json()

    def wait_ready(self, timeout: float = 15.0) -> dict[str, Any]:
        deadline = time.time() + timeout
        last: Exception | None = None
        while time.time() < deadline:
            try:
                targets = self.targets()
            except CDPError as exc:
                last = exc
                time.sleep(0.25)
                continue
            pages = [
                target
                for target in targets
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl")
            ]
            if pages:
                self._target = pages[0]
                return pages[0]
            time.sleep(0.25)
        raise CDPError(f"no page target appeared within {timeout:.0f}s: {last}")

    # ── connection ───────────────────────────────────────────────────────

    def connect(self) -> BrowserCDP:
        from websockets.sync.client import connect

        if self._target is None:
            self.wait_ready()
        assert self._target is not None
        url = str(self._target["webSocketDebuggerUrl"])
        self._socket = connect(
            url, max_size=16 * 1024 * 1024, open_timeout=self.timeout, legacy=True
        )
        return self

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._socket is None:
            self.connect()
        assert self._socket is not None
        self._next_id += 1
        request_id = self._next_id
        self._socket.send(
            json.dumps({"id": request_id, "method": method, "params": params or {}})
        )
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            raw = self._socket.recv(timeout=max(0.1, deadline - time.time()))
            message = json.loads(raw)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise CDPError(f"{method}: {message['error']}")
            return message.get("result")
        raise CDPError(f"{method}: no response within {self.timeout:.0f}s")

    # ── page operations ──────────────────────────────────────────────────

    def evaluate(self, expression: str) -> Any:
        result = self._call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
        if result is None:
            return None
        return result.get("result", {}).get("value")

    def title(self) -> str:
        return str(self.evaluate("document.title"))

    def text(self) -> str:
        return str(self.evaluate("document.body ? document.body.innerText : ''"))

    def click_text(self, text: str) -> dict[str, Any]:
        wanted = json.dumps(text)
        expression = f"""
        (() => {{
          const wanted = {wanted};
          const candidates = Array.from(document.querySelectorAll(
            'button, a, [role="button"], [role="link"], input[type="button"], input[type="submit"]'
          ));
          const el = candidates.find(node =>
            ((node.innerText || node.value || '').trim() === wanted) ||
            node.getAttribute('aria-label') === wanted
          );
          if (!el) return {{ok: false, reason: 'target not found'}};
          el.scrollIntoView({{block: 'center'}});
          el.click();
          return {{ok: true, tag: el.tagName.toLowerCase()}};
        }})()
        """
        result = self.evaluate(expression)
        if not isinstance(result, dict) or not result.get("ok"):
            raise CDPError(f"click {text!r} failed: {result}")
        return result

    def fill(self, target: str, text: str, selector: str | None = None) -> dict[str, Any]:
        wanted = json.dumps(selector or target)
        value = json.dumps(text)
        expression = f"""
        (() => {{
          const wanted = {wanted};
          const value = {value};
          const el = document.querySelector(wanted) || Array.from(
            document.querySelectorAll('input, textarea')
          ).find(node =>
            node.getAttribute('aria-label') === wanted ||
            node.getAttribute('placeholder') === wanted ||
            node.getAttribute('name') === wanted
          );
          if (!el) return {{ok: false, reason: 'field not found'}};
          el.focus();
          const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
          setter.call(el, value);
          el.dispatchEvent(new Event('input', {{bubbles: true}}));
          el.dispatchEvent(new Event('change', {{bubbles: true}}));
          return {{ok: true, value: el.value}};
        }})()
        """
        result = self.evaluate(expression)
        if not isinstance(result, dict) or not result.get("ok"):
            raise CDPError(f"fill {target!r} failed: {result}")
        return result

    def wait_text(self, text: str, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if text in self.text():
                return True
            time.sleep(0.1)
        return False

    def wait_ready_page(self, timeout: float = 5.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.evaluate("document.readyState")
            if state in ("interactive", "complete"):
                return
            time.sleep(0.1)
