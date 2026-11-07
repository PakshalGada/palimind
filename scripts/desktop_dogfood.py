#!/usr/bin/env python3
"""Palimind computer-use dogfood benchmark (Linux).

Runs 20 tasks across calculator, text entry/editor, file manager, browser and
settings, recording success and screenshot count. The acceptance target from
the plan is >=80% success with zero screenshots on accessibility-capable apps.

Run from the repository root:

    .venv/bin/python scripts/desktop_dogfood.py --json /tmp/dogfood.json

The benchmark assumes a graphical session and the release `palimind-desktop`
binary. It creates its own app processes and cleans them up. Existing app
instances are terminated at start unless --keep-existing is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "backend"))

os.environ.setdefault("PALIMIND_DESKTOP_ENABLE", "1")
os.environ.setdefault("PALIMIND_DESKTOP_ALLOW_ALL", "1")
os.environ.setdefault("PALIMIND_DESKTOP_ACTION_RATE", "200")
os.environ.pop("PALIMIND_DESKTOP_ALLOWED_APPS", None)

CHROME_CANDIDATES = [
    Path.home() / ".cache" / "ms-playwright" / "chromium-1248" / "chrome-linux64" / "chrome",
    Path.home() / ".cache" / "ms-playwright" / "chromium-1200" / "chrome-linux64" / "chrome",
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
]


@dataclass
class TaskResult:
    id: str
    category: str
    name: str
    ok: bool
    duration_ms: int
    error: str = ""
    notes: str = ""


@dataclass
class Benchmark:
    client: object
    keep_existing: bool = False
    results: list[TaskResult] = field(default_factory=list)
    screenshots: int = 0
    snapshots: int = 0
    processes: list[subprocess.Popen] = field(default_factory=list)
    windows: dict[str, dict] = field(default_factory=dict)
    cache: dict[str, dict] = field(default_factory=dict)
    cdp_port: int = 0
    cdp: object | None = None

    # ── lifecycle ────────────────────────────────────────────────────────

    def find_binary(self) -> Path:
        from palimind.agents.tools.desktop.client import resolve_binary

        binary = resolve_binary(os.environ.get("PALIMIND_DESKTOP_BIN"))
        if binary is None:
            raise SystemExit(
                "palimind-desktop not found; run `make desktop-bundle` or set PALIMIND_DESKTOP_BIN"
            )
        os.environ["PALIMIND_DESKTOP_BIN"] = str(binary)
        return binary

    def stop_existing(self) -> None:
        if self.keep_existing:
            return
        for pattern in (
            "^/usr/bin/gnome-calculator$",
            "^/usr/bin/gedit$",
            "^/usr/bin/nautilus$",
            "^/usr/bin/gnome-control-center",
        ):
            subprocess.run(["pkill", "-9", "-f", pattern], check=False)
        # Chromium instances created by this benchmark use a temp profile; a
        # stale one from a previous run is safe to stop as well.
        subprocess.run(
            ["pkill", "-9", "-f", "chrome-linux64/chrome.*--user-data-dir=/tmp/palimind-dogfood"],
            check=False,
        )

    def spawn(self, cmd: list[str], env: dict[str, str] | None = None) -> subprocess.Popen:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, **(env or {})},
        )
        self.processes.append(process)
        return process

    def cleanup(self) -> None:
        if self.cdp is not None:
            try:
                self.cdp.close()
            except Exception:
                pass
        for process in self.processes:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    # ── observation / action helpers ─────────────────────────────────────

    def wait_window(
        self,
        app_substr: str,
        *,
        title_contains: str | None = None,
        pid: int | None = None,
        timeout: float = 12.0,
    ) -> dict:
        deadline = time.time() + timeout
        last = []
        while time.time() < deadline:
            windows = (self.client.apps("windows").get("data") or {}).get("result", [])
            last = windows
            for window in windows:
                if app_substr.lower() not in window["app_name"].lower():
                    continue
                if pid is not None and window["pid"] != pid:
                    continue
                if title_contains and title_contains.lower() not in window["title"].lower():
                    continue
                return window
            time.sleep(0.4)
        raise RuntimeError(f"no {app_substr!r} window (last windows: {[(w['app_name'], w['title']) for w in last[:6]]})")

    def snapshot(self, app: str | None = None, window: dict | None = None, **kwargs) -> dict:
        params = {
            "app": app,
            "window_id": window["id"] if window else None,
            "interactive_only": False,
            "max_depth": 50,
            "timeout_ms": kwargs.pop("timeout_ms", 30_000),
            **kwargs,
        }
        params = {key: value for key, value in params.items() if value is not None}
        self.snapshots += 1
        envelope = self.client.snapshot(**params)
        if not envelope.get("ok"):
            raise RuntimeError(f"snapshot failed: {envelope.get('error')}")
        return (envelope.get("data") or {}).get("snapshot") or {}

    def cached_snapshot(self, key: str, app: str | None = None, window: dict | None = None, **kwargs) -> dict:
        if key not in self.cache:
            self.cache[key] = self.snapshot(app=app, window=window, **kwargs)
        return self.cache[key]

    def node(self, snapshot: dict, role: str, name: str | None = None) -> dict:
        for node in snapshot.get("nodes") or []:
            if node.get("role") != role:
                continue
            if name is None or node.get("name") == name:
                return node
        raise AssertionError(f"no {role} {name!r} in {[(n.get('role'), n.get('name')) for n in snapshot.get('nodes', [])][:20]}")

    def click(self, snapshot: dict, role: str, name: str | None = None) -> None:
        target = self.node(snapshot, role, name)
        if not target.get("ref"):
            raise AssertionError(f"{role} {name!r} has no ref")
        envelope = self.client.act(action="click", ref=target["ref"])
        if not envelope.get("ok"):
            raise RuntimeError(f"click failed: {envelope.get('error')}")

    def act(self, action: str, **kwargs) -> dict:
        envelope = self.client.act(action=action, **kwargs)
        if not envelope.get("ok"):
            raise RuntimeError(f"{action} failed: {envelope.get('error')}")
        return envelope

    def install_screenshot_counter(self) -> None:
        original = self.client.screenshot

        def counted(*args, **kwargs):
            self.screenshots += 1
            return original(*args, **kwargs)

        self.client.screenshot = counted

    # ── task runner ──────────────────────────────────────────────────────

    def task(self, task_id: str, category: str, name: str, fn) -> None:
        started = time.perf_counter()
        try:
            fn()
            self.results.append(
                TaskResult(task_id, category, name, True, int((time.perf_counter() - started) * 1000))
            )
        except Exception as exc:  # noqa: BLE001 - benchmark records failures
            self.results.append(
                TaskResult(
                    task_id,
                    category,
                    name,
                    False,
                    int((time.perf_counter() - started) * 1000),
                    error=str(exc)[:500],
                )
            )


# ── categories ───────────────────────────────────────────────────────────


def setup_calculator(bench: Benchmark) -> dict:
    process = bench.spawn(["gnome-calculator"])
    window = bench.wait_window("gnome-calculator", pid=process.pid, timeout=10)
    bench.windows["calculator"] = window
    return window


def calculator_tasks(bench: Benchmark) -> None:
    def fresh_window() -> dict:
        # Calculator keeps a scrollable history; restarting gives each task a
        # clean display and keeps the observation deterministic.
        previous = bench.windows.get("calculator")
        if previous:
            subprocess.run(["kill", "-9", str(previous["pid"])], check=False)
            time.sleep(0.6)
        process = bench.spawn(["gnome-calculator"])
        window = bench.wait_window("gnome-calculator", pid=process.pid, timeout=10)
        bench.windows["calculator"] = window
        return window

    def run(buttons: list[str], expected: str):
        window = fresh_window()
        snapshot = bench.snapshot(window=window)
        clear = next(
            (node for node in snapshot["nodes"] if node.get("role") == "button" and str(node.get("name", "")).startswith("Clear Display")),
            None,
        )
        if clear:
            bench.act("click", ref=clear["ref"])
            time.sleep(0.2)
        for label in buttons:
            current = bench.snapshot(window=window)
            bench.click(current, "button", label)
            time.sleep(0.15)
        for _ in range(15):
            time.sleep(0.12)
            final = bench.snapshot(window=window)
            if any(
                node.get("role") == "statictext" and node.get("name") == expected
                for node in final.get("nodes", [])
            ):
                return
        raise AssertionError(
            f"expected display {expected!r}; got "
            f"{[(n.get('role'), n.get('name')) for n in final.get('nodes', []) if n.get('role') == 'statictext'][:6]}"
        )

    bench.task("calc-1", "calculator", "7 + 8 = 15", lambda: run(["7", "+", "8", "="], "15"))
    bench.task("calc-2", "calculator", "9 × 6 = 54", lambda: run(["9", "×", "6", "="], "54"))
    bench.task("calc-3", "calculator", "42 ÷ 7 = 6", lambda: run(["4", "2", "÷", "7", "="], "6"))
    bench.task("calc-4", "calculator", "12 + 30 = 42", lambda: run(["1", "2", "+", "3", "0", "="], "42"))


def setup_gedit(bench: Benchmark) -> dict:
    process = bench.spawn(["gedit", "--new-window"])
    window = bench.wait_window("gedit", pid=process.pid, timeout=10)
    bench.windows["gedit"] = window
    return window


def setup_entry(bench: Benchmark) -> dict:
    process = bench.spawn(["zenity", "--entry", "--title=Palimind Dogfood Editor", "--text=Type here"])
    window = bench.wait_window("zenity", pid=process.pid, title_contains="Palimind Dogfood", timeout=10)
    bench.windows["entry"] = window
    return window


def editor_tasks(bench: Benchmark) -> None:
    gedit = bench.windows["gedit"]
    entry = bench.windows["entry"]

    def gedit_observe() -> None:
        snapshot = bench.snapshot(window=gedit)
        textfields = [node for node in snapshot["nodes"] if node.get("role") == "textfield"]
        assert textfields, "gedit has no editable text field"
        assert any(node.get("role") == "button" and node.get("name") == "Save" for node in snapshot["nodes"])

    def entry_type() -> None:
        snapshot = bench.snapshot(window=entry)
        field = bench.node(snapshot, "textfield", "Type here")
        bench.act("type", ref=field["ref"], text="hello dogfood")
        time.sleep(0.2)
        after = bench.snapshot(window=entry)
        value = bench.node(after, "textfield", "Type here").get("value")
        assert value == "hello dogfood", f"entry value {value!r}"

    def entry_set_and_clear() -> None:
        snapshot = bench.snapshot(window=entry)
        field = bench.node(snapshot, "textfield", "Type here")
        bench.act("set_value", ref=field["ref"], value="The quick brown fox")
        time.sleep(0.2)
        after = bench.snapshot(window=entry)
        assert bench.node(after, "textfield", "Type here").get("value") == "The quick brown fox"
        field = bench.node(after, "textfield", "Type here")
        bench.act("clear", ref=field["ref"])
        time.sleep(0.2)
        cleared = bench.snapshot(window=entry)
        assert not bench.node(cleared, "textfield", "Type here").get("value")

    bench.task("editor-1", "editor", "gedit exposes an editable document", gedit_observe)
    bench.task("editor-2", "editor", "text entry accepts typing", entry_type)
    bench.task("editor-3", "editor", "text entry accepts set_value", lambda: entry_set_and_clear())
    bench.task("editor-4", "editor", "text entry clear removes the value", lambda: _entry_assert_empty(bench, entry))


def _entry_assert_empty(bench: Benchmark, window: dict) -> None:
    snapshot = bench.snapshot(window=window)
    assert not bench.node(snapshot, "textfield", "Type here").get("value"), "entry is not empty"


def setup_nautilus(bench: Benchmark) -> dict:
    process = bench.spawn(["nautilus"])
    window = bench.wait_window("nautilus", pid=process.pid, timeout=12)
    bench.windows["nautilus"] = window
    return window


def nautilus_tasks(bench: Benchmark) -> None:
    window = bench.windows["nautilus"]

    def observe() -> None:
        snapshot = bench.snapshot(window=window)
        assert snapshot["node_count"] > 50
        names = {node.get("name") for node in snapshot["nodes"]}
        assert names & {"Show list", "Show grid"}, "view control missing"
        assert any(name in names for name in ("Documents", "Downloads", "Home")), "no file entries"

    def switch_view() -> None:
        snapshot = bench.snapshot(window=window)
        names = {node.get("name") for node in snapshot["nodes"]}
        if "Show list" in names:
            bench.click(snapshot, "button", "Show list")
            expected, label = "Show grid", "list"
        elif "Show grid" in names:
            bench.click(snapshot, "button", "Show grid")
            expected, label = "Show list", "grid"
        else:
            raise AssertionError("no view control")
        time.sleep(0.4)
        after = bench.snapshot(window=window)
        assert any(
            node.get("role") == "button" and node.get("name") == expected
            for node in after["nodes"]
        ), f"{label} view did not switch"

    def open_search() -> None:
        snapshot = bench.snapshot(window=window)
        bench.click(snapshot, "switch", "Search")
        deadline = time.time() + 3
        while time.time() < deadline:
            time.sleep(0.2)
            after = bench.snapshot(window=window)
            if any(node.get("role") == "textfield" for node in after["nodes"]):
                return
        raise AssertionError("search field missing")

    def close_search() -> None:
        snapshot = bench.snapshot(window=window)
        switches = [node for node in snapshot["nodes"] if node.get("role") == "switch" and node.get("name") == "Search"]
        assert switches, "search switch missing"
        bench.act("click", ref=switches[0]["ref"])
        time.sleep(0.4)
        after = bench.snapshot(window=window)
        # The search field is removed when search is closed. A stale hidden
        # field is acceptable only if it is not visible.
        visible_fields = [
            node for node in after["nodes"] if node.get("role") == "textfield" and "hidden" not in node.get("states", [])
        ]
        assert not visible_fields, "search field still visible"

    bench.task("files-1", "file manager", "Home lists files and view controls", observe)
    bench.task("files-2", "file manager", "switch from grid to list view", switch_view)
    bench.task("files-3", "file manager", "open file search", open_search)
    bench.task("files-4", "file manager", "close file search", close_search)


def setup_settings(bench: Benchmark) -> dict:
    process = bench.spawn(["gnome-control-center", "mouse"])
    window = bench.wait_window("gnome-control-center", pid=process.pid, timeout=12)
    bench.windows["settings"] = window
    return window


def _wait_no_textfield(bench: Benchmark, window: dict, timeout: float = 3.0) -> None:
    # Search closes with a short compositor animation; let it finish before the
    # next action or the window still reports a blocking modal surface.
    time.sleep(0.6)
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = bench.snapshot(window=window)
        if not any(node.get("role") == "textfield" for node in snapshot["nodes"]):
            return
        time.sleep(0.15)
    raise AssertionError("search field did not close")


def settings_tasks(bench: Benchmark) -> None:
    def fresh_window() -> dict:
        # The search surface is a modal in this GNOME version; a fresh process
        # per task avoids one task's modal state leaking into the next.
        previous = bench.windows.get("settings")
        if previous:
            subprocess.run(["kill", "-9", str(previous["pid"])], check=False)
            time.sleep(0.6)
        process = bench.spawn(["gnome-control-center", "mouse"])
        window = bench.wait_window("gnome-control-center", pid=process.pid, timeout=12)
        bench.windows["settings"] = window
        return window

    def observe() -> None:
        window = fresh_window()
        snapshot = bench.snapshot(window=window)
        assert any(
            node.get("role") == "statictext" and node.get("name") == "Mouse & Touchpad"
            for node in snapshot["nodes"]
        )

    def search() -> None:
        window = fresh_window()
        snapshot = bench.snapshot(window=window)
        bench.click(snapshot, "switch", "Search")
        time.sleep(0.5)
        after = bench.snapshot(window=window)
        assert any(node.get("role") == "textfield" for node in after["nodes"])

    def menu() -> None:
        window = fresh_window()
        snapshot = bench.snapshot(window=window)
        bench.click(snapshot, "switch", "Primary Menu")
        time.sleep(0.5)
        after = bench.snapshot(window=window)
        assert any(node.get("name") == "All Settings" for node in after["nodes"])

    def test_switch() -> None:
        window = fresh_window()
        snapshot = bench.snapshot(window=window)
        before = bench.node(snapshot, "switch", "Test Your Settings")
        was_checked = "checked" in before.get("states", [])
        bench.act("click", ref=before["ref"])
        time.sleep(0.5)
        after = bench.snapshot(window=window)
        now = bench.node(after, "switch", "Test Your Settings")
        assert ("checked" in now.get("states", [])) != was_checked

    bench.task("settings-1", "settings", "Mouse panel exposes its title", observe)
    bench.task("settings-2", "settings", "open settings search", search)
    bench.task("settings-3", "settings", "open the primary menu", menu)
    bench.task("settings-4", "settings", "toggle Test Your Settings", test_switch)

def chrome_binary() -> Path | None:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return Path(shutil.which("google-chrome") or shutil.which("chromium") or "").resolve() if shutil.which("google-chrome") or shutil.which("chromium") else None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def setup_browser(bench: Benchmark) -> dict | None:
    chrome = chrome_binary()
    if chrome is None:
        return None
    from palimind.agents.tools.desktop.browser import BrowserCDP

    profile = "/tmp/palimind-dogfood-chrome"
    shutil.rmtree(profile, ignore_errors=True)
    port = _free_port()
    html = (
        "<title>Palimind Dogfood Benchmark</title><h1 id=h>Hello</h1>"
        "<label for=i>Name</label><input id=i aria-label='Name'>"
        "<button id=save onclick=\"document.getElementById('h').textContent='Saved'\">Save</button>"
        "<a href='#' id=go onclick=\"document.getElementById('h').textContent='Gone';return false\">Go</a>"
    )
    import urllib.parse

    url = "data:text/html," + urllib.parse.quote(html)
    process = bench.spawn(
        [
            str(chrome),
            "--force-renderer-accessibility",
            "--no-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--new-window",
            url,
        ]
    )
    window = bench.wait_window("chrome", pid=process.pid, title_contains="Palimind Dogfood", timeout=15)
    bench.windows["browser"] = window
    bench.cdp_port = port
    cdp = BrowserCDP(port=port)
    cdp.wait_ready(timeout=20)
    cdp.connect()
    cdp.wait_ready_page(timeout=10)
    bench.cdp = cdp
    return window


def browser_tasks(bench: Benchmark) -> None:
    window = bench.windows.get("browser")
    if window is None:
        for index in range(1, 5):
            bench.task(f"browser-{index}", "browser", "browser unavailable", lambda: (_ for _ in ()).throw(RuntimeError("no Chromium binary")))
        return

    def snapshot() -> dict:
        # Chromium is the slowest app to prove; one snapshot serves the
        # observation tasks and a fresh one is taken after an action.
        return bench.cached_snapshot("browser", window=window, timeout_ms=60_000)

    def title() -> None:
        snap = snapshot()
        assert "Palimind Dogfood" in str(snap.get("window", {}).get("title"))

    def content() -> None:
        snap = snapshot()
        names = {node.get("name") for node in snap["nodes"]}
        assert "Hello" in names
        assert "Save" in names

    def controls() -> None:
        snap = snapshot()
        assert any(node.get("role") == "textfield" and node.get("name") == "Name" for node in snap["nodes"])
        assert any(node.get("role") == "link" and node.get("name") == "Go" for node in snap["nodes"])

    def click_save() -> None:
        # Chromium web-content refs are not uniquely provable through AT-SPI;
        # use the documented CDP route for the page action, then verify both the
        # page text and the accessibility heading.
        cdp = bench.cdp
        if cdp is None:
            raise RuntimeError("CDP route is unavailable")
        cdp.click_text("Save")
        assert cdp.wait_text("Saved", timeout=5), "page text did not update"
        after = bench.snapshot(window=window, timeout_ms=60_000)
        names = {node.get("name") for node in after["nodes"]}
        assert "Saved" in names, "accessibility heading did not update"

    bench.task("browser-1", "browser", "read page title", title)
    bench.task("browser-2", "browser", "read page heading and Save button", content)
    bench.task("browser-3", "browser", "read Name field and Go link", controls)
    bench.task("browser-4", "browser", "click Save and verify page update", click_save)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="write the report JSON here")
    parser.add_argument("--keep-existing", action="store_true", help="do not stop existing app instances")
    args = parser.parse_args()

    from palimind.agents.tools.desktop.client import DesktopClient

    bench = Benchmark(client=DesktopClient(), keep_existing=args.keep_existing)
    bench.find_binary()
    bench.install_screenshot_counter()
    bench.stop_existing()

    try:
        setup_calculator(bench)
        setup_gedit(bench)
        setup_entry(bench)
        setup_nautilus(bench)
        setup_settings(bench)
        setup_browser(bench)

        calculator_tasks(bench)
        editor_tasks(bench)
        nautilus_tasks(bench)
        settings_tasks(bench)
        browser_tasks(bench)
    finally:
        bench.cleanup()
        bench.client.close()

    passed = sum(1 for result in bench.results if result.ok)
    total = len(bench.results)
    rate = passed / total if total else 0.0
    report = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "success_rate": round(rate, 3),
        "screenshots": bench.screenshots,
        "snapshots": bench.snapshots,
        "target": {"success_rate": 0.8, "screenshots": 0},
        "tasks": [asdict(result) for result in bench.results],
    }
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"{'id':<12} {'category':<14} {'ok':<4} {'ms':>7}  name")
    for result in bench.results:
        print(
            f"{result.id:<12} {result.category:<14} {result.ok!s:<4} "
            f"{result.duration_ms:>7}  {result.name}"
        )
        if not result.ok:
            print(f"{'':<12} {'':<14} {'':<4} {'':>7}  └─ {result.error}")
    print(
        f"\n{passed}/{total} tasks passed ({rate:.0%}), "
        f"screenshots={bench.screenshots}, snapshots={bench.snapshots}"
    )
    ok = rate >= 0.8 and bench.screenshots == 0
    print("ACCEPTANCE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
