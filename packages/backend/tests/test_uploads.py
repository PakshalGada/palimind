"""Tests for local chat attachments (store + resolution)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from palimind import uploads


@pytest.fixture(autouse=True)
def _isolated_uploads(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(uploads, "uploads_dir", lambda: tmp_path / "uploads")
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    yield


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_store_get_list_delete_text() -> None:
    meta = uploads.save_upload("notes.txt", _b64(b"hello attachment"), "text/plain")
    assert meta["kind"] == "text"
    assert meta["size"] == len(b"hello attachment")
    assert meta["id"] == meta["sha256"]

    fetched = uploads.get_upload(meta["id"])
    assert fetched is not None and fetched["name"] == "notes.txt"
    assert any(item["id"] == meta["id"] for item in uploads.list_uploads())
    assert uploads.delete_upload(meta["id"]) is True
    assert uploads.get_upload(meta["id"]) is None


def test_same_bytes_are_deduplicated() -> None:
    first = uploads.save_upload("a.txt", _b64(b"same"), "text/plain")
    second = uploads.save_upload("a.txt", _b64(b"same"), "text/plain")
    assert first["id"] == second["id"]


def test_invalid_base64_and_empty_are_rejected() -> None:
    with pytest.raises(ValueError, match="base64"):
        uploads.save_upload("x.txt", "not base64!!", "text/plain")
    with pytest.raises(ValueError, match="empty"):
        uploads.save_upload("x.txt", "", "text/plain")


def test_oversize_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(uploads, "UPLOAD_MAX_MB", 1)
    with pytest.raises(ValueError, match="too large"):
        uploads.save_upload("big.bin", _b64(b"x" * (1024 * 1024 + 1)), "application/octet-stream")


def test_resolve_text_and_image_attachments(tmp_path: Path) -> None:
    image = b"\x89PNG\r\n\x1a\nfake"
    img_meta = uploads.save_upload("pic.png", _b64(image), "image/png")
    txt_meta = uploads.save_upload("doc.md", _b64(b"# Title\nBody"), "text/markdown")
    resolved = uploads.resolve_attachments([img_meta["id"], txt_meta["id"]])
    assert len(resolved["image_paths"]) == 1
    assert Path(resolved["image_paths"][0]).is_file()
    assert any("Body" in block for block in resolved["text_blocks"])
    context = uploads.build_attachment_context(resolved)
    assert "[ATTACHMENTS]" in context and "Body" in context


def test_missing_attachment_becomes_a_note() -> None:
    resolved = uploads.resolve_attachments("does-not-exist")
    assert resolved["image_paths"] == []
    assert resolved["notes"]
    assert "not found" in resolved["notes"][0]


def test_upload_endpoints(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    resp = client.post(
        "/api/uploads",
        json={"name": "hello.txt", "mime": "text/plain", "data": _b64(b"hi")},
    )
    assert resp.status_code == 200
    upload = resp.json()["upload"]
    assert upload["kind"] == "text"

    listed = client.get("/api/uploads").json()["uploads"]
    assert any(item["id"] == upload["id"] for item in listed)

    got = client.get(f"/api/uploads/{upload['id']}")
    assert got.status_code == 200 and got.json()["upload"]["id"] == upload["id"]

    deleted = client.delete(f"/api/uploads/{upload['id']}")
    assert deleted.json()["status"] == "success"
