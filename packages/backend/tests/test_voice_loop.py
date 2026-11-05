"""Tests for the live voice loop (VAD -> STT -> chat tokens -> TTS)."""

from __future__ import annotations

import base64
import io
import json
import threading
import wave
from pathlib import Path

import pytest

from palimind.api_routers.routers import voice


def _wav(amplitude: int = 1200, seconds: float = 0.12) -> bytes:
    rate = 16000
    frames = int(rate * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(
            b"".join(int(amplitude).to_bytes(2, "little", signed=True) for _ in range(frames))
        )
    return buf.getvalue()


def _events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[5:].strip()))
    return out


@pytest.fixture(autouse=True)
def _isolated_chat(monkeypatch, tmp_path: Path):
    import palimind.api_server as server

    monkeypatch.setattr(server, "_chat_root", lambda _scope: tmp_path)
    monkeypatch.setattr(server, "_resolve_chat_session", _fake_resolve_session)
    yield


async def _fake_resolve_session(_root, session_id):
    return session_id or "voice-session"


def test_transcribe_answer_and_audio(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    async def fake_answer(transcript, history=None, session_id=""):
        assert transcript == "hello"
        yield "Hi "
        yield "there."

    monkeypatch.setattr(voice, "transcribe_wav_bytes", lambda _wav: "hello")
    monkeypatch.setattr(voice, "_stream_answer", fake_answer)
    monkeypatch.setattr(voice, "text_to_speech_bytes", lambda text, _voice: b"RIFFfake-audio")

    client = TestClient(server.app)
    response = client.post("/api/voice/chat?stream_id=v1", content=_wav())
    assert response.status_code == 200
    events = _events(response.text)
    types = [e["type"] for e in events]
    assert types[:3] == ["stream", "vad", "transcript"]
    assert "token" in types and "audio" in types and types[-1] == "done"
    transcript = next(e for e in events if e["type"] == "transcript")
    assert transcript["text"] == "hello"
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert tokens == "Hi there."
    audio = next(e for e in events if e["type"] == "audio")
    assert base64.b64decode(audio["audio"]) == b"RIFFfake-audio"
    assert audio["mime"] == "audio/wav"


def test_vad_skips_silence_without_transcribing(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    called = {"transcribe": False}

    def fail_transcribe(_wav):
        called["transcribe"] = True
        raise AssertionError("transcription must not run for silence")

    monkeypatch.setattr(voice, "transcribe_wav_bytes", fail_transcribe)
    client = TestClient(server.app)
    response = client.post("/api/voice/chat?stream_id=v2", content=_wav(amplitude=0))
    events = _events(response.text)
    assert events[1] == {
        "type": "vad",
        "speech": False,
        "stream_id": "v2",
    }
    assert events[-1]["type"] == "done"
    assert events[-1]["reason"] == "silence"
    assert called["transcribe"] is False


def test_stop_marks_stream_for_barge_in(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    cancel = voice._register_stream("barge")
    try:
        client = TestClient(server.app)
        response = client.post("/api/voice/chat/stop?stream_id=barge")
        assert response.json()["status"] == "stopping"
        assert cancel.is_set() is True
    finally:
        voice._unregister_stream("barge")


def test_pre_cancelled_stream_emits_cancelled(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(voice, "_register_stream", lambda _sid: cancel)
    monkeypatch.setattr(voice, "transcribe_wav_bytes", lambda _wav: "hello")
    client = TestClient(server.app)
    response = client.post("/api/voice/chat?stream_id=v3", content=_wav())
    events = _events(response.text)
    types = [e["type"] for e in events]
    assert "cancelled" in types
    assert events[-1]["reason"] == "cancelled"
