"""CDP web-content route tests (integration, launches Chromium)."""

from __future__ import annotations

import shutil
import socket
import subprocess
import urllib.parse
from pathlib import Path

import pytest

from palimind.agents.tools.desktop.browser import BrowserCDP, CDPError, find_chrome


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
        target = client.wait_ready(timeout=20)
        assert "CDP Test" in str(target.get("title"))
        client.connect()
        client.wait_ready_page(timeout=10)
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
