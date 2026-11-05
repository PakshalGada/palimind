"""Tests for local image generation and its API/tool surface."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from palimind import imagegen


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 30, 40)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _isolated_images(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(imagegen, "images_dir", lambda: tmp_path / "images")
    (tmp_path / "images").mkdir()
    yield


def test_availability_off_and_unknown() -> None:
    assert imagegen.availability("off")["available"] is False
    assert imagegen.availability("nope")["available"] is False


def test_availability_comfyui(monkeypatch) -> None:
    class _Resp:
        status_code = 200

    monkeypatch.setattr(imagegen, "IMAGE_BACKEND", "comfyui")
    monkeypatch.setattr(imagegen, "COMFYUI_URL", "http://127.0.0.1:8188")
    monkeypatch.setattr(imagegen.httpx, "get", lambda *a, **k: _Resp())
    status = imagegen.availability()
    assert status["available"] is True
    assert status["backend"] == "comfyui"


def test_availability_sdcpp(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "sd"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(imagegen, "SDCPP_BINARY", str(binary))
    monkeypatch.setattr(imagegen.shutil, "which", lambda _name: str(binary))
    status = imagegen.availability("sdcpp")
    assert status["available"] is True
    assert status["binary"] == str(binary)


def test_generate_image_requires_prompt() -> None:
    with pytest.raises(imagegen.ImageGenerationError, match="prompt"):
        imagegen.generate_image("   ")


def test_comfyui_generation_and_artifact_lifecycle(monkeypatch) -> None:
    png = _png()

    class _Resp:
        def __init__(self, *, body=None, content=b"", status=200):
            self._body = body or {}
            self.content = content
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

        def json(self):
            return self._body

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            assert url.endswith("/prompt")
            return _Resp(body={"prompt_id": "p1"})

        def get(self, url, params=None):
            if "/history/" in url:
                return _Resp(
                    body={
                        "p1": {
                            "outputs": {
                                "9": {
                                    "images": [
                                        {"filename": "x.png", "subfolder": "", "type": "output"}
                                    ]
                                }
                            }
                        }
                    }
                )
            if url.endswith("/view"):
                return _Resp(content=png)
            raise AssertionError(url)

    monkeypatch.setattr(imagegen, "IMAGE_BACKEND", "comfyui")
    monkeypatch.setattr(imagegen, "COMFYUI_CHECKPOINT", "model.safetensors")
    monkeypatch.setattr(imagegen, "IMAGE_TIMEOUT", 5.0)
    monkeypatch.setattr(imagegen.httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(imagegen.httpx, "Client", _Client)

    data, meta = imagegen.generate_image("a cat", width=64, height=64, steps=2)
    assert data == png
    assert meta["backend"] == "comfyui"
    assert meta["width"] == 64

    record = imagegen.save_image(data, meta)
    assert record["id"]
    assert imagegen.image_bytes(record["id"]) == png
    assert any(item["id"] == record["id"] for item in imagegen.list_images())
    assert imagegen.delete_image(record["id"]) is True
    assert imagegen.image_bytes(record["id"]) is None


def test_sdcpp_generation(monkeypatch, tmp_path: Path) -> None:
    png = _png()
    binary = tmp_path / "sd"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(imagegen, "SDCPP_BINARY", str(binary))
    monkeypatch.setattr(imagegen, "SDCPP_MODEL", "")
    monkeypatch.setattr(imagegen.shutil, "which", lambda _name: str(binary))
    monkeypatch.setattr(
        imagegen.httpx, "get", lambda *a, **k: type("R", (), {"status_code": 200})()
    )

    def fake_run(cmd, **_kwargs):
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_bytes(png)
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(imagegen.subprocess, "run", fake_run)
    data, meta = imagegen.generate_image("a dog", width=64, height=64, steps=2, backend="sdcpp")
    assert data == png
    assert meta["backend"] == "sdcpp"


def test_image_api_and_tool(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    png = _png()

    def fake_generate(prompt, **_kwargs):
        return png, {
            "prompt": prompt,
            "negative_prompt": "",
            "width": 64,
            "height": 64,
            "steps": 2,
            "seed": 1,
            "backend": "comfyui",
        }

    monkeypatch.setattr(imagegen, "generate_image", fake_generate)
    client = TestClient(server.app)
    created = client.post(
        "/api/images/generate", json={"prompt": "a cat", "width": 64, "height": 64}
    )
    assert created.status_code == 200
    image = created.json()["image"]
    assert image["url"] == f"/api/images/{image['id']}"

    served = client.get(f"/api/images/{image['id']}")
    assert served.status_code == 200
    assert served.content == png
    assert served.headers["content-type"] == "image/png"

    listed = client.get("/api/images").json()["images"]
    assert any(item["id"] == image["id"] for item in listed)
    assert client.delete(f"/api/images/{image['id']}").json()["status"] == "success"

    from palimind.llm.mixture_of_expert.tools import call_tool

    monkeypatch.setattr(
        imagegen,
        "generate_and_save",
        lambda prompt, **kwargs: {
            "id": "tool-image",
            "prompt": prompt,
            "width": 64,
            "height": 64,
            "backend": "comfyui",
            "seed": 1,
            "url": "/api/images/tool-image",
        },
    )
    out = call_tool("image_generate", prompt="a cat")
    assert "Generated image tool-image" in out
