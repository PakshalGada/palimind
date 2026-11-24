"""Prompt coach endpoint."""

from __future__ import annotations


def test_chat_coach_requires_text() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    response = client.post("/api/chat/coach", json={"text": "   "})
    assert response.status_code == 400


def test_chat_coach_returns_rewritten_prompt(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server
    import palimind.generative.responder as responder

    monkeypatch.setattr(
        responder,
        "generate_response_stream",
        lambda *args, **kwargs: iter(["Write a crisp launch plan for the pricing page."]),
    )
    client = TestClient(server.app)
    response = client.post("/api/chat/coach", json={"text": "pricing launch plan"})
    assert response.status_code == 200
    assert response.json()["prompt"].startswith("Write a crisp launch plan")
