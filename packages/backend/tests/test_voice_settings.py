"""Tests for the microphone STT model setting."""

from __future__ import annotations

import json
from pathlib import Path

import palimind.config as config
import palimind.settings as settings
from palimind.audio import stt


def test_resolve_model_name_precedence(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "global.json"
    monkeypatch.setattr(config, "GLOBAL_CONFIG_PATH", path)
    monkeypatch.setattr(settings, "STT_WHISPER_MODEL", "tiny.en")

    # No user setting → env/default.
    assert stt.resolve_model_name() == "tiny.en"

    # User setting wins over env.
    path.write_text(json.dumps({"stt_whisper_model": "small.en"}), "utf-8")
    assert stt.resolve_model_name() == "small.en"


def test_voice_settings_endpoint(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    path = tmp_path / "global.json"
    monkeypatch.setattr(server, "GLOBAL_CONFIG_PATH", path)
    monkeypatch.setattr(config, "GLOBAL_CONFIG_PATH", path)

    client = TestClient(server.app)

    body = client.get("/api/settings/voice").json()
    assert body["stt_whisper_model"]
    assert any(o["id"] == "base.en" for o in body["options"])

    saved = client.patch("/api/settings/voice", json={"stt_whisper_model": "small.en"}).json()
    assert saved["status"] == "success"
    assert json.loads(path.read_text("utf-8"))["stt_whisper_model"] == "small.en"
    assert client.get("/api/settings/voice").json()["stt_whisper_model"] == "small.en"


def test_voice_settings_requires_model() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    assert "error" in client.patch("/api/settings/voice", json={}).json()
