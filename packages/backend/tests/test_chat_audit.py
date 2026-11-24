"""Chat audit trail."""

from __future__ import annotations

from pathlib import Path


def test_chat_audit_records_and_reads_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    from fastapi.testclient import TestClient

    import palimind.api_server as server
    from palimind.chat_audit import append_chat_audit, read_chat_audit

    append_chat_audit("chat.test", session_id="s1", detail={"ok": True})
    events = read_chat_audit(limit=10, session_id="s1")
    assert events[0]["event"] == "chat.test"
    assert events[0]["detail"] == {"ok": True}

    client = TestClient(server.app)
    response = client.get("/api/chat/audit?session_id=s1&limit=10")
    assert response.status_code == 200
    assert response.json()["events"][0]["event"] == "chat.test"


def test_critic_writes_an_audit_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    from fastapi.testclient import TestClient

    import palimind.api_server as server
    import palimind.llm.mixture_of_expert.llm as llm

    monkeypatch.setattr(
        llm,
        "llm_chat_safe",
        lambda *args, **kwargs: {"content": "## Verdict\nFine."},
    )
    client = TestClient(server.app)
    critic = client.post("/api/chat/critic", json={"text": "Answer"})
    assert critic.status_code == 200
    audit = client.get("/api/chat/audit?limit=10")
    assert any(event["event"] == "chat.critic" for event in audit.json()["events"])
