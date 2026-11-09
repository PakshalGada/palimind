"""CDP web-content route tests (integration, launches Chromium)."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import urllib.parse
from pathlib import Path

import pytest

from palimind.agents.tools.desktop.browser import (
    BrowserCDP,
    CDPError,
    discover_devtools_port,
    find_chrome,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.integration
def test_cdp_clicks_fills_and_reads_the_page(tmp_path: Path):
    chrome = find_chrome()
    if chrome is None:
        pytest.skip("Chromium is not installed")
    port = _free_port()
    profile = tmp_path / "chrome-profile"
    html = (
        "<title>CDP Test</title><h1 id=h>Hello</h1>"
        "<input aria-label='Name'>"
        "<button onclick=\"document.getElementById('h').textContent='Saved'\">Save</button>"
    )
    url = "data:text/html," + urllib.parse.quote(html)
    process = subprocess.Popen(
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
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = BrowserCDP(port=port)
    try:
        client.wait_ready(timeout=20)
        client.connect()
        client.wait_ready_page(timeout=10)
        # The target is listed before navigation finishes, so the title can be
        # empty for a moment after wait_ready returns.
        deadline = time.time() + 10
        while time.time() < deadline and client.title() != "CDP Test":
            time.sleep(0.1)
        assert client.title() == "CDP Test"
        assert "Hello" in client.text()
        client.click_text("Save")
        assert client.wait_text("Saved", timeout=5)
        client.fill("Name", "Ada")
        assert client.evaluate("document.querySelector('input').value") == "Ada"
    finally:
        client.close()
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)


def test_cdp_reports_a_missing_endpoint():
    port = _free_port()
    client = BrowserCDP(port=port, timeout=0.5)
    with pytest.raises(CDPError):
        client.wait_ready(timeout=0.6)


def test_discovery_reads_devtools_active_port(tmp_path: Path, monkeypatch):
    from palimind.agents.tools.desktop import browser

    active = tmp_path / "DevToolsActivePort"
    active.write_text("45678\n/devtools/browser/abc\n", encoding="utf-8")
    monkeypatch.setattr(browser, "_devtools_active_port_files", lambda: [active])
    monkeypatch.setattr(browser, "_port_from_cmdline", lambda: [])

    class Response:
        def __init__(self, status_code: int):
            self.status_code = status_code

    def fake_get(url: str, timeout: float):
        return Response(200 if ":45678/" in url else 404)

    monkeypatch.setattr(browser.httpx, "get", fake_get)
    assert discover_devtools_port(timeout=0.01) == 45678


def test_discovery_returns_none_when_nothing_answers(tmp_path: Path, monkeypatch):
    from palimind.agents.tools.desktop import browser

    monkeypatch.setattr(browser, "_devtools_active_port_files", lambda: [])
    monkeypatch.setattr(browser, "_port_from_cmdline", lambda: [])

    class Response:
        status_code = 404

    monkeypatch.setattr(browser.httpx, "get", lambda url, timeout: Response())
    assert discover_devtools_port(timeout=0.01) is None


def test_browser_tool_explains_a_missing_devtools_endpoint(monkeypatch):
    from palimind.agents.tools.desktop import browser, tool

    monkeypatch.setattr(tool.settings, "DESKTOP_ENABLE", True)
    monkeypatch.setattr(browser, "discover_devtools_port", lambda *args, **kwargs: None)
    out = tool.desktop_browser(action="status")
    assert "no Chromium DevTools endpoint" in out
    assert "--remote-debugging-port" in out


@pytest.mark.integration
def test_discovery_and_page_outline_with_an_ephemeral_port(tmp_path: Path, monkeypatch):
    import time

    from palimind.agents.tools.desktop import browser

    chrome = find_chrome()
    if chrome is None:
        pytest.skip("Chromium is not installed")
    profile = tmp_path / "profile"
    profile.mkdir()
    html = (
        "<title>Outline Test</title><h1>Hello</h1>"
        "<button onclick=\"document.body.dataset.clicked='1'\">Save</button>"
        "<input aria-label='Name'>"
    )
    url = "data:text/html," + urllib.parse.quote(html)
    process = subprocess.Popen(
        [
            str(chrome),
            "--headless=new",
            "--no-sandbox",
            "--no-first-run",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    active = profile / "DevToolsActivePort"
    client = None
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not active.is_file():
            time.sleep(0.1)
        assert active.is_file(), "Chromium did not write DevToolsActivePort"
        monkeypatch.setattr(browser, "_devtools_active_port_files", lambda: [active])
        monkeypatch.setattr(browser, "_port_from_cmdline", lambda: [])
        port = discover_devtools_port(timeout=1.0)
        assert port, "no reachable DevTools port"
        client = BrowserCDP(port=port)
        client.wait_ready(timeout=10)
        client.connect()
        client.wait_ready_page(timeout=10)
        assert client.title() == "Outline Test"
        outline = client.page_outline()
        names = {element.get("name") for element in outline}
        assert "Save" in names
        assert "Name" in names
        assert all("width" in element and "height" in element for element in outline)
    finally:
        if client is not None:
            client.close()
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)
