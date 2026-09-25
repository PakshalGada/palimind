"""Unit tests for the native browser tools.

No browser is launched and no network is used: URL safety, snapshot
formatting and registry wiring are all exercised directly.
"""

from __future__ import annotations

import palimind.settings as settings
from palimind.agents.tools.browser import tool as bt
from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, _register_plugin_tools


def test_check_url_rejects_non_http_schemes() -> None:
    assert bt._check_url("ftp://example.com") is not None
    assert bt._check_url("javascript:alert(1)") is not None
    assert bt._check_url("file:///etc/passwd") is not None


def test_check_url_rejects_local_and_private_hosts() -> None:
    for url in (
        "http://localhost/x",
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254",
        "http://[::1]/",
    ):
        assert bt._check_url(url) is not None, url


def test_check_url_allows_public_ip() -> None:
    # IP literal → resolution needs no network and is globally routable.
    assert bt._check_url("http://93.184.216.34/") is None


def test_check_url_respects_blocked_domains(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_BLOCKED_DOMAINS", ["93.184.216.34"])
    assert bt._check_url("http://93.184.216.34/") is not None


def test_check_url_respects_allowlist(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_ALLOWED_DOMAINS", ["example.com"])
    # An IP not covered by the allowlist is refused.
    assert bt._check_url("http://93.184.216.34/") is not None


def test_browser_open_refuses_private_url_without_playwright() -> None:
    out = bt.browser_open("http://127.0.0.1/")
    assert out.startswith("Error")


def test_browser_click_rejects_non_integer_ref() -> None:
    assert "ref must be an integer" in bt.browser_click("nope")  # type: ignore[arg-type]


def test_format_snapshot_numbers_refs() -> None:
    out = bt._format_snapshot(
        [{"ref": 0, "tag": "a", "text": "Sign in", "href": "https://example.com/login"}]
    )
    assert "[0]" in out
    assert "Sign in" in out
    assert "https://example.com/login" in out


def test_browser_tools_registered_with_tiers() -> None:
    _register_plugin_tools()
    for name in (
        "browser_open",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_press",
        "browser_scroll",
        "browser_extract",
        "browser_screenshot",
        "browser_close",
    ):
        assert name in TOOL_REGISTRY, f"{name} not registered"
    assert TOOL_REGISTRY["browser_open"]["meta"]["tier"] == 1
    assert TOOL_REGISTRY["browser_click"]["meta"]["tier"] == 2
    assert TOOL_REGISTRY["browser_click"]["meta"]["requires_approval"] is True
    assert TOOL_REGISTRY["browser_open"]["meta"]["requires_approval"] is False
    assert TOOL_REGISTRY["browser_open"]["timeout_s"] >= 30
