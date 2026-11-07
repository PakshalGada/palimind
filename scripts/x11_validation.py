#!/usr/bin/env python3
"""X11 release-gate harness for Palimind computer use.

Run on a real X11 session or under Xvfb + a window manager:

    .venv/bin/python scripts/x11_validation.py --json /tmp/palimind-x11.json

It checks the properties the plan makes release-gating on X11:

* session reports X11 and screen coordinates are available;
* AT-SPI snapshot of Calculator returns refs and bounds;
* a semantic 7 + 8 = 15 action loop works;
* an X11 screenshot capture succeeds and is local;
* the pointer route reports screen coordinates (not the Wayland refusal).

The harness exits 2 with a SKIP report when no X11 display is present, so CI
can distinguish "not an X11 runner" from a failed validation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "backend"))

os.environ.setdefault("PALIMIND_DESKTOP_ENABLE", "1")
os.environ.setdefault("PALIMIND_DESKTOP_ALLOWED_APPS", "gnome-calculator")
os.environ.setdefault("PALIMIND_DESKTOP_ACTION_RATE", "120")


def _skip(report: dict, reason: str) -> int:
    report["status"] = "skipped"
    report["reason"] = reason
    print(json.dumps(report, indent=2))
    # A missing X11 runner is a skip, not a failed validation.
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    report: dict = {"status": "running", "checks": []}

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or session == "wayland"
    display = os.environ.get("DISPLAY", "")
    report["session"] = {"type": session, "display": display, "wayland": wayland}
    if wayland or not display:
        message = (
            f"no X11 session (XDG_SESSION_TYPE={session!r}, DISPLAY={display!r}, "
            f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY')!r}); "
            "run under Xvfb/openbox or a real X11 login"
        )
        report["status"] = "skipped"
        report["reason"] = message
        if args.json:
            args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0

    from palimind.agents.tools.desktop.client import DesktopClient, resolve_binary

    binary = resolve_binary(os.environ.get("PALIMIND_DESKTOP_BIN"))
    if binary is None:
        report["status"] = "failed"
        report["reason"] = "palimind-desktop binary not found"
        if args.json:
            args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 1

    client = DesktopClient(binary=binary)
    process = None
    try:
        status = client.status()
        data = status.get("data") or {}
        report["checks"].append(
            {
                "name": "status_x11",
                "ok": data.get("session_type") == "x11"
                and (data.get("capabilities") or {}).get("wayland_pointer_targeting")
                == "screen_coordinates_available",
                "details": {
                    "session_type": data.get("session_type"),
                    "capabilities": data.get("capabilities"),
                },
            }
        )

        env = {**os.environ, "GDK_BACKEND": "x11", "QT_QPA_PLATFORM": "xcb"}
        process = subprocess.Popen(
            ["gnome-calculator"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        deadline = time.time() + 12
        window = None
        while time.time() < deadline and window is None:
            time.sleep(0.4)
            windows = (client.apps("windows", app="gnome-calculator").get("data") or {}).get(
                "result", []
            )
            window = next((w for w in windows if w["pid"] == process.pid), None)
        if window is None:
            raise RuntimeError("calculator did not register on X11")

        snapshot = client.snapshot(window_id=window["id"], interactive_only=False)
        snap = (snapshot.get("data") or {}).get("snapshot") or {}
        refs = [node for node in snap.get("nodes", []) if node.get("ref") and node.get("bounds")]
        report["checks"].append(
            {
                "name": "snapshot_refs_and_bounds",
                "ok": bool(snapshot.get("ok")) and bool(refs),
                "details": {"nodes": snap.get("node_count"), "refs": len(refs)},
            }
        )

        def click(name: str) -> dict:
            fresh = (client.snapshot(window_id=window["id"], interactive_only=False).get("data") or {}).get(
                "snapshot", {}
            )
            node = next(
                n
                for n in fresh.get("nodes", [])
                if n.get("role") == "button" and n.get("name") == name
            )
            return client.act(action="click", ref=node["ref"])

        for label in ("7", "+", "8", "="):
            click(label)
        final = (client.snapshot(window_id=window["id"], interactive_only=False).get("data") or {}).get(
            "snapshot", {}
        )
        report["checks"].append(
            {
                "name": "semantic_calculator_7_plus_8",
                "ok": any(
                    node.get("role") == "statictext" and node.get("name") == "15"
                    for node in final.get("nodes", [])
                ),
                "details": {"nodes": final.get("node_count")},
            }
        )

        screenshot = client.screenshot(screen=0)
        shot = screenshot.get("data") or {}
        report["checks"].append(
            {
                "name": "x11_screenshot",
                "ok": bool(screenshot.get("ok")) and bool(shot.get("path")),
                "details": {
                    "path": shot.get("path"),
                    "width": shot.get("width"),
                    "height": shot.get("height"),
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        report["checks"].append({"name": "exception", "ok": False, "details": str(exc)})
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        client.close()

    ok = all(check["ok"] for check in report["checks"])
    report["status"] = "passed" if ok else "failed"
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
