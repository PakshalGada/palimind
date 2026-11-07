"""Tests for the thin web/mobile client served at /client."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_client_route_serves_mobile_html() -> None:
    from palimind.api_server import app

    response = TestClient(app).get("/client")
    assert response.status_code == 200
    html = response.text
    assert 'name="viewport"' in html
    assert "safe-area-inset" in html
    assert "/v1/chat/completions" in html
    assert "/v1/models" in html
    assert "palimind_token" in html
    assert response.headers.get("cache-control") == "no-store"
