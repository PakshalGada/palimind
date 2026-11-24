"""Chat critic and council endpoints."""

from __future__ import annotations


def test_critic_requires_text() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    response = client.post("/api/chat/critic", json={"text": "  "})
    assert response.status_code == 400


def test_critic_returns_markdown(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server
    import palimind.llm.mixture_of_expert.llm as llm

    monkeypatch.setattr(
        llm,
        "llm_chat_safe",
        lambda *args, **kwargs: {"content": "## Verdict\nGood, with one gap.\n## Revised answer\nFixed."},
    )
    client = TestClient(server.app)
    response = client.post(
        "/api/chat/critic",
        json={"text": "The answer says revenue grew.", "question": "What happened?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "## Verdict" in payload["critique"]
    assert payload["model"]


def test_council_returns_members_and_synthesis(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server
    import palimind.llm.mixture_of_expert.llm as llm

    calls: list[str] = []

    def fake_chat(messages, model, *args, **kwargs):
        calls.append(model)
        if "council synthesizer" in str(messages[0].get("content", "")).lower():
            return {"content": "Synthesized answer"}
        return {"content": f"Answer from {model}"}

    monkeypatch.setattr(llm, "llm_chat_safe", fake_chat)
    client = TestClient(server.app)
    response = client.post(
        "/api/chat/council",
        json={"text": "Should we launch in Q4?", "models": ["model-a", "model-b"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert [member["model"] for member in payload["members"]] == ["model-a", "model-b"]
    assert payload["synthesis"] == "Synthesized answer"
    assert "model-a" in calls and "model-b" in calls


def test_council_requires_query() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    response = client.post("/api/chat/council", json={"text": ""})
    assert response.status_code == 400
