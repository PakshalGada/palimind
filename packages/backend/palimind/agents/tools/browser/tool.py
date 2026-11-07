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
import os
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

        profile = "".join(
            c for c in os.environ.get("PALIMIND_BROWSER_PROFILE", "shared") if c.isalnum() or c in "-_"
        ) or "shared"
        user_data = Path.home() / ".palimind" / "browser" / "profiles" / profile
        user_data.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    str(user_data),
                    headless=BROWSER_HEADLESS,
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120 Safari/537.36 PaliMind"
                    ),
                )
                self._browser = context
                pages = context.pages
                self._page = pages[0] if pages else context.new_page()
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
                    context.close()
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
    def _guard(self) -> None:
        """Refuse to expose a page that ended up on a blocked address.

        Only the requested URL is vetted up front; HTTP redirects, page
        scripts (``location = 'http://127.0.0.1:…'``), clicks and history
        navigation can all land the session on a loopback/private host.
        """
        url = str(self._page.url or "")
        if not url or url.startswith(("about:", "data:")):
            return
        err = _check_url(url)
        if err:
            try:
                self._page.goto("about:blank")
            except Exception:  # noqa: BLE001 - best effort reset
                pass
            raise PermissionError(f"navigation to {url} refused: {err}")

    def op_goto(self, url: str, wait_until: str) -> dict[str, Any]:
        from palimind.settings import BROWSER_TIMEOUT_MS

        resp = self._page.goto(url, wait_until=wait_until, timeout=BROWSER_TIMEOUT_MS)
        self._guard()
        return {
            "title": self._page.title(),
            "url": self._page.url,
            "status": resp.status if resp else None,
        }

    def op_snapshot(self) -> list[dict[str, Any]]:
        self._guard()
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
        self._guard()
        return {"title": self._page.title(), "url": self._page.url}

    def op_forward(self) -> dict[str, Any]:
        self._page.go_forward(timeout=15000)
        self._guard()
        return {"title": self._page.title(), "url": self._page.url}

    def op_extract(self, max_chars: int) -> str:
        self._guard()
        return (self._page.inner_text("body") or "")[:max_chars]

    def op_screenshot(self, path: str) -> str:
        self._guard()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=path, full_page=False)
        return path

    def op_screenshot_bytes(self) -> bytes:
        return self._page.screenshot(full_page=False)

    def op_screenshot_jpeg(self, quality: int = 70) -> bytes:
        return self._page.screenshot(
            type="jpeg",
            quality=max(20, min(int(quality or 70), 90)),
            full_page=False,
            animations="disabled",
        )

    def op_click_xy(self, x: float, y: float) -> None:
        self._page.mouse.click(float(x), float(y))

    def op_move(self, x: float, y: float) -> None:
        self._page.mouse.move(float(x), float(y))

    def op_wheel(self, dx: float, dy: float) -> None:
        self._page.mouse.wheel(float(dx), float(dy))

    def op_key(self, key: str, text: str = "") -> None:
        if text:
            self._page.keyboard.insert_text(str(text))
        else:
            self._page.keyboard.press(str(key))

    def op_insert_text(self, text: str) -> None:
        self._page.keyboard.insert_text(str(text))

    def op_reload(self) -> dict[str, Any]:
        self._page.reload(wait_until="domcontentloaded", timeout=30000)
        self._guard()
        return {"title": self._page.title(), "url": self._page.url}

    def op_viewport(self) -> dict[str, Any]:
        size = self._page.viewport_size or {"width": 1280, "height": 800}
        return {"width": int(size["width"]), "height": int(size["height"])}

    def op_state(self) -> dict[str, Any]:
        history = self._page.evaluate("() => ({ back: history.length > 1 })")
        return {
            "title": self._page.title(),
            "url": self._page.url,
            "can_go_back": bool(history.get("back")),
            "can_go_forward": True,
            "viewport": self.op_viewport(),
        }

    def op_tabs(self) -> list[dict[str, Any]]:
        return [
            {
                "index": i,
                "url": pg.url,
                "title": pg.title(),
                "active": pg is self._page,
            }
            for i, pg in enumerate(self._page.context.pages)
        ]

    def op_new_tab(self, url: str) -> dict[str, Any]:
        page = self._page.context.new_page()
        if url:
            page.goto(url, wait_until="domcontentloaded")
        self._page = page
        return {"index": len(self._page.context.pages) - 1, "url": page.url}

    def op_select_tab(self, index: int) -> dict[str, Any]:
        pages = self._page.context.pages
        if index < 0 or index >= len(pages):
            raise IndexError("tab index out of range")
        self._page = pages[index]
        return {"index": index, "url": self._page.url, "title": self._page.title()}

    def op_close_tab(self, index: int) -> dict[str, Any]:
        pages = self._page.context.pages
        if index < 0 or index >= len(pages):
            raise IndexError("tab index out of range")
        page = pages[index]
        page.close()
        self._page = self._page.context.pages[0]
        return {"closed": index, "url": self._page.url}


_worker_lock = threading.Lock()
_worker: _BrowserWorker | None = None


# ── ownership / human takeover ────────────────────────────────────────────
#
# One shared browser session can be driven by an agent or by the user. The
# lock is deliberately in-memory: it describes who is holding the queue right
# now, not durable state. Takeover rows in SQLite record the handoff for the
# UI and survive a restart, but a restarted browser starts under agent control.

_control_lock = threading.Lock()
_control: dict[str, str] = {"owner": "agent", "agent_id": "", "takeover_id": ""}


def control_state() -> dict[str, str]:
    with _control_lock:
        return dict(_control)


def claim_control(*, agent_id: str = "", takeover_id: str = "") -> dict[str, str]:
    """Give the user control of the live browser."""
    with _control_lock:
        _control.update({"owner": "human", "agent_id": agent_id, "takeover_id": takeover_id})
        return dict(_control)


def request_control(*, agent_id: str = "", takeover_id: str = "") -> dict[str, str]:
    """Pause agent mutations while a takeover request is pending."""
    with _control_lock:
        _control.update({"owner": "pending", "agent_id": agent_id, "takeover_id": takeover_id})
        return dict(_control)


def release_control() -> dict[str, str]:
    """Return control to the agent after the user finishes a handoff."""
    with _control_lock:
        _control.update({"owner": "agent", "agent_id": "", "takeover_id": ""})
        return dict(_control)


def _ensure_agent_control() -> str | None:
    with _control_lock:
        owner = _control.get("owner")
        if owner == "human":
            return "Error: the user currently has the browser. Wait for them to hand it back."
        if owner == "pending":
            return "Error: waiting for the user to take over the browser."
    return None


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
    blocked = _ensure_agent_control()
    if blocked:
        return blocked
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
    blocked = _ensure_agent_control()
    if blocked:
        return blocked
    try:
        ref_i = int(ref)
    except (TypeError, ValueError):
        return "Error: ref must be an integer"
    out = _run("op_click", ref_i)
    return out if out.startswith("Error") else f"Clicked [{ref_i}]."


def browser_type(ref: int, text: str, submit: bool = False) -> str:
    """Type *text* into the element tagged with *ref* (optionally submit)."""
    blocked = _ensure_agent_control()
    if blocked:
        return blocked
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
    blocked = _ensure_agent_control()
    if blocked:
        return blocked
    out = _run("op_press", str(key))
    return f"Pressed {key}." if not out.startswith("Error") else out


def browser_scroll(direction: str = "down", amount: int = 1) -> str:
    """Scroll the page up or down by *amount* viewport heights."""
    blocked = _ensure_agent_control()
    if blocked:
        return blocked
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
    blocked = _ensure_agent_control()
    if blocked:
        return blocked
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


def browser_new_tab(url: str = "") -> str:
    """Open a new managed tab and return its index."""
    blocked = _ensure_agent_control()
    if blocked:
        return blocked
    if url:
        err = _check_url(url)
        if err:
            return f"Error: {err}"
    return _run("op_new_tab", str(url))


def browser_select_tab(index: int) -> str:
    """Select a managed tab by index."""
    blocked = _ensure_agent_control()
    if blocked:
        return blocked
    return _run("op_select_tab", int(index))


def browser_close_tab(index: int) -> str:
    """Close a managed tab by index."""
    blocked = _ensure_agent_control()
    if blocked:
        return blocked
    return _run("op_close_tab", int(index))


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


def live_frame_jpeg(quality: int = 70) -> bytes | None:
    """Return the current page as a JPEG for the embedded browser dock."""
    if not _PLAYWRIGHT_AVAILABLE:
        return None
    with _worker_lock:
        worker = _worker
    if worker is None:
        return None
    try:
        return worker.call(worker.op_screenshot_jpeg, int(quality), timeout=20)
    except Exception:  # noqa: BLE001
        return None


def live_state() -> dict[str, Any]:
    """Current browser state for the dock. Best-effort; never starts a browser."""
    state = control_state()
    if not _PLAYWRIGHT_AVAILABLE:
        return {"open": False, **state, "tabs": [], "error": "Playwright is not installed"}
    with _worker_lock:
        worker = _worker
    if worker is None:
        return {"open": False, **state, "tabs": [], "error": None}
    try:
        info = worker.call(worker.op_state, timeout=10)
        tabs = worker.call(worker.op_tabs, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {"open": True, **state, "tabs": [], "error": str(exc)}
    return {
        "open": True,
        **state,
        "title": info.get("title", ""),
        "url": info.get("url", ""),
        "can_go_back": info.get("can_go_back", False),
        "can_go_forward": info.get("can_go_forward", False),
        "viewport": info.get("viewport") or {"width": 1280, "height": 800},
        "tabs": tabs if isinstance(tabs, list) else [],
        "error": None,
    }


def human_action(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply a user action to the shared browser and return the latest state.

    Only the UI calls this. Agent tools still go through the normal tool layer;
    while the user owns the browser those mutations return a clear error.
    """
    body = payload or {}
    action = str(action or "").strip()
    allowed = {
        "goto",
        "back",
        "forward",
        "reload",
        "click",
        "move",
        "wheel",
        "scroll",
        "key",
        "type",
        "new_tab",
        "select_tab",
        "close_tab",
    }
    if action not in allowed:
        return {"error": f"unknown browser action: {action}"}
    if not _PLAYWRIGHT_AVAILABLE:
        return {"error": "Playwright is not installed"}
    try:
        worker = _get_worker()
        if action == "goto":
            url = str(body.get("url") or "").strip()
            err = _check_url(url)
            if err:
                return {"error": err}
            worker.call(worker.op_goto, url, "domcontentloaded")
        elif action == "back":
            worker.call(worker.op_back)
        elif action == "forward":
            worker.call(worker.op_forward)
        elif action == "reload":
            worker.call(worker.op_reload)
        elif action == "click":
            worker.call(worker.op_click_xy, float(body.get("x", 0)), float(body.get("y", 0)))
        elif action == "move":
            worker.call(worker.op_move, float(body.get("x", 0)), float(body.get("y", 0)))
        elif action == "wheel":
            worker.call(worker.op_wheel, float(body.get("dx", 0)), float(body.get("dy", 0)))
        elif action == "scroll":
            worker.call(worker.op_wheel, 0.0, float(body.get("dy", 0)))
        elif action == "key":
            key = str(body.get("key") or "")
            text = str(body.get("text") or "")
            worker.call(worker.op_key, key, text)
        elif action == "type":
            worker.call(worker.op_insert_text, str(body.get("text") or ""))
        elif action == "new_tab":
            url = str(body.get("url") or "")
            if url:
                err = _check_url(url)
                if err:
                    return {"error": err}
            worker.call(worker.op_new_tab, url)
        elif action == "select_tab":
            worker.call(worker.op_select_tab, int(body.get("index", 0)))
        elif action == "close_tab":
            worker.call(worker.op_close_tab, int(body.get("index", 0)))
        else:
            return {"error": f"unknown browser action: {action}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return live_state()



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
    "browser_new_tab": {
        "fn": browser_new_tab,
        "description": "Open a new managed browser tab.",
        "parameters": {"url": "Optional http(s) URL"},
        "tier": 2,
        "requires_approval": True,
        "timeout_s": 60,
    },
    "browser_select_tab": {
        "fn": browser_select_tab,
        "description": "Select a managed browser tab by index.",
        "parameters": {"index": {"type": "integer"}},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 20,
    },
    "browser_close_tab": {
        "fn": browser_close_tab,
        "description": "Close a managed browser tab by index.",
        "parameters": {"index": {"type": "integer"}},
        "tier": 2,
        "requires_approval": True,
        "timeout_s": 20,
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
