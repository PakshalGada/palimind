"""Chat export bundle endpoint."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path


def test_chat_bundle_contains_transcript_artifacts_and_sources(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    response = client.post(
        "/api/chat/export-bundle",
        json={
            "title": "Q3 review",
            "messages": [
                {"role": "user", "content": "Build the Q3 review"},
                {"role": "assistant", "content": "Here is the deck"},
            ],
            "artifacts": [
                {
                    "title": "Q3 review deck",
                    "type": "slide-outline",
                    "content": "# Revenue\n- Growth: 18%\n[chart: bar] Revenue ($M) | Q1: 4.2 | Q2: 5.1",
                },
                {"title": "notes", "type": "markdown", "content": "# Notes"},
            ],
            "sources": [
                {"title": "Q3 report", "url": "https://example.com/q3", "kind": "web"},
            ],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-palimind-filename"] == "Q3_review-bundle.zip"

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert "transcript.md" in names
    assert "sources.md" in names
    assert "sources.json" in names
    assert "manifest.json" in names
    assert "artifacts/Q3_review_deck.md" in names
    assert "artifacts/notes.md" in names

    transcript = archive.read("transcript.md").decode()
    assert "# Q3 review" in transcript
    assert "## You" in transcript
    assert "Build the Q3 review" in transcript

    sources = json.loads(archive.read("sources.json"))
    assert sources[0]["url"] == "https://example.com/q3"

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["message_count"] == 2
    assert manifest["artifact_count"] == 2


def test_chat_bundle_requires_content(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    response = client.post("/api/chat/export-bundle", json={"title": "Empty"})
    assert response.status_code == 400
