"""Native Playwright browser tools.

A single long-lived Chromium session is owned by a dedicated worker thread
because Playwright's sync API is bound to the thread that created it, while
the tool layer executes each call on a short-lived sandbox thread. Every
browser_* function submits a command to the worker and waits for the result.

Safety:
  - only http(s) URLs are accepted;
  - private / loopback / link-local / reserved addresses are refused (SSRF);
  - optional domain allow/deny lists via settings;
  - interaction tools are tier 2 and may require human approval.
"""

from __future__ import annotations

import ipaddress
import queue
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


_MSG_NO_PLAYWRIGHT = (
    "Error: Playwright is not installed. Install it with "
    "`pip install playwright && playwright install chromium` to use the "
    "browser tools."
)

_ALLOW_SCHEMES = {"http", "https"}
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "169.254.169.254"}

# JS that tags interactive elements with stable refs and returns a summary.
_SNAPSHOT_JS = """
() => {
  const sel = 'a, button, input, textarea, select, [role=button], [role=link], [role=tab], [contenteditable=true]';
  const els = Array.from(document.querySelectorAll(sel)).slice(0, 200);
  return els.map((el, i) => {
    el.setAttribute('data-pm-ref', String(i));
    const label = (el.innerText || el.value || el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') || el.name || '').trim().replace(/\\s+/g, ' ').slice(0, 90);
    return {
      ref: i,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      text: label,
      href: el.href || '',
    };
  });
}
"""


# ── URL safety ────────────────────────────────────────────────────────────


def _domain_matches(host: str, domains: list[str]) -> bool:
    h = host.lower().rstrip(".")
    return any(h == d or h.endswith("." + d) for d in domains)


def _check_url(url: str) -> str | None:
    """Return an error string if *url* must not be visited, else None."""
    from palimind.settings import (
        BROWSER_ALLOWED_DOMAINS,
        BROWSER_BLOCKED_DOMAINS,
    )

    try:
        parsed = urlparse(str(url))
    except Exception:
        return "invalid URL"
    if parsed.scheme not in _ALLOW_SCHEMES:
        return "only http(s) URLs are allowed"
    host = parsed.hostname or ""
    if not host:
        return "URL has no host"
    if host.lower() in _BLOCKED_HOSTS:
        return f"host '{host}' is blocked"
    if BROWSER_ALLOWED_DOMAINS and not _domain_matches(host, BROWSER_ALLOWED_DOMAINS):
        return f"domain '{host}' is not in the browser allowlist"
    if BROWSER_BLOCKED_DOMAINS and _domain_matches(host, BROWSER_BLOCKED_DOMAINS):
        return f"domain '{host}' is blocked"

    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        return f"could not resolve host '{host}': {e}"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not ip.is_global or ip.is_multicast:
            return f"address for '{host}' is not public (SSRF refused)"
    return None


# ── browser worker thread ─────────────────────────────────────────────────


class _BrowserWorker:
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._start_error: Exception | None = None
        self._page: Any = None
        self._browser: Any = None
        self._thread = threading.Thread(target=self._run, name="palimind-browser", daemon=True)
        self._thread.start()

    # runs on the worker thread
    def _run(self) -> None:
        from palimind.settings import BROWSER_HEADLESS

        try:
            with sync_playwright() as p:
                self._browser = p.chromium.launch(headless=BROWSER_HEADLESS)
                context = self._browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120 Safari/537.36 PaliMind"
                    ),
                )
                self._page = context.new_page()
                self._ready.set()
                while True:
                    item = self._q.get()
                    if item is None:
                        break
                    fn, args, box, ev = item
                    try:
                        box["value"] = fn(*args)
                    except Exception as e:  # noqa: BLE001 - surfaced to caller
                        box["error"] = e
                    finally:
                        ev.set()
                try:
                    self._browser.close()
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001 - launch/install failure
            self._start_error = e
            self._ready.set()

    # called from tool (sandbox) threads
    def call(self, fn: Any, *args: Any, timeout: float = 90.0) -> Any:
        if self._start_error is not None:
            raise self._start_error
        if not self._ready.wait(timeout=30):
            raise TimeoutError("browser did not start in time")
        if self._start_error is not None:
            raise self._start_error
        box: dict[str, Any] = {}
        ev = threading.Event()
        self._q.put((fn, args, box, ev))
        if not ev.wait(timeout):
            raise TimeoutError("browser command timed out")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def stop(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=10)

    # ── operations (execute on the worker thread) ──────────────────────
    def op_goto(self, url: str, wait_until: str) -> dict[str, Any]:
        from palimind.settings import BROWSER_TIMEOUT_MS

        resp = self._page.goto(url, wait_until=wait_until, timeout=BROWSER_TIMEOUT_MS)
        return {
            "title": self._page.title(),
            "url": self._page.url,
            "status": resp.status if resp else None,
        }

    def op_snapshot(self) -> list[dict[str, Any]]:
        return self._page.evaluate(_SNAPSHOT_JS) or []

    def op_click(self, ref: int) -> None:
        self._page.locator(f'[data-pm-ref="{ref}"]').first.click(timeout=15000)

    def op_type(self, ref: int, text: str, submit: bool) -> None:
        loc = self._page.locator(f'[data-pm-ref="{ref}"]').first
        loc.fill(str(text), timeout=15000)
        if submit:
            loc.press("Enter", timeout=15000)

    def op_press(self, key: str) -> None:
        self._page.keyboard.press(str(key))

    def op_scroll(self, direction: str, amount: int) -> None:
        dy = int(amount) * 600 * (-1 if direction == "up" else 1)
        self._page.mouse.wheel(0, dy)

    def op_back(self) -> dict[str, Any]:
        self._page.go_back(timeout=15000)
        return {"title": self._page.title(), "url": self._page.url}

    def op_forward(self) -> dict[str, Any]:
        self._page.go_forward(timeout=15000)
        return {"title": self._page.title(), "url": self._page.url}

    def op_extract(self, max_chars: int) -> str:
        return (self._page.inner_text("body") or "")[:max_chars]

    def op_screenshot(self, path: str) -> str:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=path, full_page=False)
        return path

    def op_screenshot_bytes(self) -> bytes:
        return self._page.screenshot(full_page=False)

    def op_tabs(self) -> list[dict[str, Any]]:
        return [{"index": i, "url": pg.url} for i, pg in enumerate(self._page.context.pages)]


_worker_lock = threading.Lock()
_worker: _BrowserWorker | None = None


def _get_worker() -> _BrowserWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = _BrowserWorker()
        return _worker


# ── formatting helpers ────────────────────────────────────────────────────


def _format_snapshot(items: list[dict[str, Any]], max_chars: int = 6000) -> str:
    if not items:
        return "(no interactive elements found)"
    lines: list[str] = []
    for it in items:
        label = it.get("text") or it.get("href") or ""
        extra = f" → {it['href']}" if it.get("href") else ""
        lines.append(f"[{it['ref']}] <{it['tag']}> {label}{extra}")
    out = "\n".join(lines)
    return out[:max_chars]


def _run(fn_name: str, *args: Any, timeout: float = 90.0) -> str:
    """Run a worker op and return its result as text ("ok" when None)."""
    if not _PLAYWRIGHT_AVAILABLE:
        return _MSG_NO_PLAYWRIGHT
    try:
        worker = _get_worker()
        result = worker.call(getattr(worker, fn_name), *args, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - tools must never crash the loop
        return f"Error: browser command failed: {e}"
    if result is None:
        return "ok"
    return result if isinstance(result, str) else str(result)


# ── tools ─────────────────────────────────────────────────────────────────


def browser_open(url: str, wait_until: str = "domcontentloaded") -> str:
    """Navigate to *url* and return the title, final URL and a numbered list
    of interactive elements that can be clicked/typed into by ref."""
    err = _check_url(url)
    if err:
        return f"Error: {err}"
    if wait_until not in ("load", "domcontentloaded", "networkidle", "commit"):
        wait_until = "domcontentloaded"
    if not _PLAYWRIGHT_AVAILABLE:
        return _MSG_NO_PLAYWRIGHT
    try:
        worker = _get_worker()
        info = worker.call(worker.op_goto, str(url), wait_until)
        items = worker.call(worker.op_snapshot)
    except Exception as e:  # noqa: BLE001
        return f"Error: could not open {url}: {e}"
    head = f"Title: {info.get('title', '')}\nURL: {info.get('url', url)}\n"
    if info.get("status"):
        head += f"Status: {info['status']}\n"
    return f"{head}\nInteractive elements:\n{_format_snapshot(items)}"


def browser_snapshot() -> str:
    """Return the current page's interactive elements (with refs) and URL."""
    if not _PLAYWRIGHT_AVAILABLE:
        return _MSG_NO_PLAYWRIGHT
    try:
        worker = _get_worker()
        items = worker.call(worker.op_snapshot)
    except Exception as e:  # noqa: BLE001
        return f"Error: snapshot failed: {e}"
    return _format_snapshot(items)


def browser_click(ref: int) -> str:
    """Click the interactive element previously tagged with *ref*."""
    try:
        ref_i = int(ref)
    except (TypeError, ValueError):
        return "Error: ref must be an integer"
    out = _run("op_click", ref_i)
    return out if out.startswith("Error") else f"Clicked [{ref_i}]."


def browser_type(ref: int, text: str, submit: bool = False) -> str:
    """Type *text* into the element tagged with *ref* (optionally submit)."""
    if not _PLAYWRIGHT_AVAILABLE:
        return _MSG_NO_PLAYWRIGHT
    try:
        ref_i = int(ref)
    except (TypeError, ValueError):
        return "Error: ref must be an integer"
    out = _run("op_type", ref_i, str(text), bool(submit))
    if out.startswith("Error"):
        return out
    return f"Typed into [{ref_i}]." + (" Submitted." if submit else "")


def browser_press(key: str) -> str:
    """Press a keyboard key (e.g. 'Enter', 'Escape', 'Tab')."""
    out = _run("op_press", str(key))
    return f"Pressed {key}." if not out.startswith("Error") else out


def browser_scroll(direction: str = "down", amount: int = 1) -> str:
    """Scroll the page up or down by *amount* viewport heights."""
    d = "up" if str(direction).lower() == "up" else "down"
    out = _run("op_scroll", d, max(1, int(amount or 1)))
    return f"Scrolled {d}." if not out.startswith("Error") else out


def browser_back() -> str:
    """Navigate back in history."""
    return _nav("op_back")


def browser_forward() -> str:
    """Navigate forward in history."""
    return _nav("op_forward")


def _nav(op: str) -> str:
    if not _PLAYWRIGHT_AVAILABLE:
        return _MSG_NO_PLAYWRIGHT
    try:
        worker = _get_worker()
        info = worker.call(getattr(worker, op))
    except Exception as e:  # noqa: BLE001
        return f"Error: navigation failed: {e}"
    return f"Title: {info.get('title', '')}\nURL: {info.get('url', '')}"


def browser_extract(max_chars: int = 8000) -> str:
    """Return the visible text of the current page (truncated)."""
    if not _PLAYWRIGHT_AVAILABLE:
        return _MSG_NO_PLAYWRIGHT
    try:
        worker = _get_worker()
        text = worker.call(worker.op_extract, int(max_chars))
    except Exception as e:  # noqa: BLE001
        return f"Error: extract failed: {e}"
    return text or "(page has no visible text)"


def browser_screenshot() -> str:
    """Capture a screenshot into the workspace and return its path."""
    if not _PLAYWRIGHT_AVAILABLE:
        return _MSG_NO_PLAYWRIGHT
    from palimind.llm.mixture_of_expert.tools import _get_context

    root = _get_context().get("root")
    base = Path(root) / ".palimind" / "browser" if root else Path.home() / ".palimind" / "browser"
    path = str(base / f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png")
    try:
        worker = _get_worker()
        saved = worker.call(worker.op_screenshot, path)
    except Exception as e:  # noqa: BLE001
        return f"Error: screenshot failed: {e}"
    return f"Screenshot saved to: {saved}"


def browser_tabs() -> str:
    """List the open tabs (index + URL)."""
    return _run("op_tabs")


def browser_close() -> str:
    """Close the browser session and free resources."""
    global _worker
    with _worker_lock:
        worker = _worker
        _worker = None
    if worker is None:
        return "No browser session is open."
    try:
        worker.stop()
    except Exception as e:  # noqa: BLE001
        return f"Error: failed to close browser: {e}"
    return "Browser session closed."


def screenshot_png() -> bytes | None:
    """Return a PNG of the current page for the live view, or None when no
    browser session is open. Never starts a browser."""
    if not _PLAYWRIGHT_AVAILABLE:
        return None
    with _worker_lock:
        worker = _worker
    if worker is None:
        return None
    try:
        png = worker.call(worker.op_screenshot_bytes, timeout=15)
    except Exception:  # noqa: BLE001 - live view is best-effort
        return None
    return png if isinstance(png, bytes) else None


TOOLS: dict[str, dict[str, Any]] = {
    "browser_open": {
        "fn": browser_open,
        "description": (
            "Open an http(s) URL in a headless browser. Returns the page title, "
            "final URL and a numbered list of interactive elements (refs) for "
            "browser_click / browser_type."
        ),
        "parameters": {
            "url": "The full http(s) URL to open",
            "wait_until": "Optional: load | domcontentloaded | networkidle | commit",
        },
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 90,
    },
    "browser_snapshot": {
        "fn": browser_snapshot,
        "description": "List the current page's interactive elements with their refs.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "browser_click": {
        "fn": browser_click,
        "description": "Click the interactive element identified by its ref.",
        "parameters": {"ref": "The integer ref from browser_open / browser_snapshot"},
        "tier": 2,
        "requires_approval": True,
        "timeout_s": 45,
    },
    "browser_type": {
        "fn": browser_type,
        "description": "Type text into the element identified by its ref.",
        "parameters": {
            "ref": "The integer ref of the input element",
            "text": "The text to type",
            "submit": "Optional: press Enter after typing (true/false)",
        },
        "tier": 2,
        "requires_approval": True,
        "timeout_s": 45,
    },
    "browser_press": {
        "fn": browser_press,
        "description": "Press a keyboard key, e.g. Enter, Tab, Escape.",
        "parameters": {"key": "Key name"},
        "tier": 2,
        "requires_approval": True,
        "timeout_s": 30,
    },
    "browser_scroll": {
        "fn": browser_scroll,
        "description": "Scroll the page up or down.",
        "parameters": {
            "direction": "Optional: 'down' (default) or 'up'",
            "amount": "Optional: number of viewport heights (default 1)",
        },
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "browser_back": {
        "fn": browser_back,
        "description": "Go back in browser history.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "browser_forward": {
        "fn": browser_forward,
        "description": "Go forward in browser history.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "browser_extract": {
        "fn": browser_extract,
        "description": "Return the visible text of the current page.",
        "parameters": {"max_chars": "Optional: maximum characters (default 8000)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "browser_screenshot": {
        "fn": browser_screenshot,
        "description": "Capture a screenshot into the workspace and return its path.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "browser_tabs": {
        "fn": browser_tabs,
        "description": "List open browser tabs.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "browser_close": {
        "fn": browser_close,
        "description": "Close the browser session.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 20,
    },
}
