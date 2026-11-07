"""Tests for the computer-use HTTP surface (screenshot crop, ask validation)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image


class _FakeClient:
    def __init__(self, path: Path):
        self.path = path

    def snapshot(self, **kwargs):
        return {
            "ok": True,
            "command": "snapshot",
            "data": {
                "snapshot": {
                    "snapshot_id": "s1",
                    "bounds_space": "screen",
                    "window": {"bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
                    "nodes": [
                        {
                            "ref": "@s1:e1",
                            "role": "button",
                            "name": "OK",
                            "bounds": [20.0, 10.0, 20.0, 20.0],
                        }
                    ],
                }
            },
        }

    def apps(self, kind="windows"):
        return {
            "ok": True,
            "command": "apps",
            "data": {
                "result": [
                    {
                        "id": "w-1-org-a11y-atspi-accessible-1",
                        "app_name": "gnome-calculator",
                        "title": "Calculator",
                        "pid": 4242,
                        "is_focused": True,
                        "visible": True,
                    },
                    {
                        "id": "w-1-org-a11y-atspi-accessible-2",
                        "app_name": "nautilus",
                        "title": "Home",
                        "pid": 4243,
                        "is_focused": False,
                        "visible": True,
                    },
                ]
            },
        }

    def screenshot(self, **kwargs):
        return {
            "ok": True,
            "command": "screenshot",
            "data": {
                "path": str(self.path),
                "format": "png",
                "width": 100,
                "height": 100,
                "scale_factor": 1.0,
                "screenshot_id": "shot-test",
            },
        }


@pytest.fixture()
def client(monkeypatch):
    from palimind import settings

    monkeypatch.setattr(settings, "DESKTOP_ENABLE", True)
    from palimind.api_server import app

    return TestClient(app)


def test_region_screenshot_is_cropped_and_returned_as_preview(client, monkeypatch, tmp_path):
    from palimind.agents.tools.desktop import client as desktop_client

    source = tmp_path / "shot.png"
    image = Image.new("RGB", (100, 100), (255, 0, 0))
    for x in range(20, 40):
        for y in range(10, 30):
            image.putpixel((x, y), (0, 0, 255))
    image.save(source)

    monkeypatch.setattr(desktop_client, "get_client", lambda *a, **k: _FakeClient(source))
    response = client.post(
        "/api/desktop/screenshot",
        json={
            "screen": 0,
            "region": {"x": 20, "y": 10, "width": 20, "height": 20},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["image"].startswith("data:image/png;base64,")
    region_path = Path(body["data"]["region_path"])
    assert region_path.exists()
    with Image.open(region_path) as crop:
        assert crop.size == (20, 20)
        assert crop.getpixel((0, 0)) == (0, 0, 255)


def test_annotated_region_reports_ref_boxes_aligned_to_the_crop(client, monkeypatch, tmp_path):
    from palimind.agents.tools.desktop import client as desktop_client

    source = tmp_path / "shot.png"
    Image.new("RGB", (100, 100), (255, 255, 255)).save(source)
    monkeypatch.setattr(desktop_client, "get_client", lambda *a, **k: _FakeClient(source))
    response = client.post(
        "/api/desktop/screenshot",
        json={
            "screen": 0,
            "app": "demo",
            "annotate": True,
            "region": {"x": 20, "y": 10, "width": 20, "height": 20},
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["annotations"] == [
        {
            "ref": "@s1:e1",
            "role": "button",
            "name": "OK",
            "bounds": [20.0, 10.0, 20.0, 20.0],
            "bounds_space": "screen",
            "box": [0, 0, 20, 20],
        }
    ]
    assert data["path"].endswith("-annotated.png")


def test_ocr_boxes_are_returned_with_ocr_labels(client, monkeypatch, tmp_path):
    from palimind.agents.tools.desktop import annotation
    from palimind.agents.tools.desktop import client as desktop_client

    source = tmp_path / "shot.png"
    Image.new("RGB", (100, 100), (255, 255, 255)).save(source)
    monkeypatch.setattr(desktop_client, "get_client", lambda *a, **k: _FakeClient(source))
    monkeypatch.setattr(
        annotation,
        "ocr_boxes",
        lambda *a, **k: [
            {
                "ref": "ocr:0",
                "kind": "ocr",
                "text": "OK",
                "confidence": 0.9,
                "image_box": [0, 0, 10, 10],
                "bounds": [20.0, 10.0, 10.0, 10.0],
                "stable": False,
            }
        ],
    )
    response = client.post(
        "/api/desktop/screenshot",
        json={
            "screen": 0,
            "ocr": True,
            "region": {"x": 20, "y": 10, "width": 20, "height": 20},
        },
    )
    assert response.status_code == 200, response.text
    boxes = response.json()["data"]["ocr_boxes"]
    assert boxes[0]["ref"] == "ocr:0"
    assert boxes[0]["stable"] is False


def test_ask_requires_an_input(client):
    response = client.post("/api/desktop/ask", json={})
    assert response.status_code == 400
    assert "input" in response.json()["error"]


def test_ask_streams_from_an_agent_with_desktop_access(client, monkeypatch):
    from palimind.agents import registry, service

    class Definition:
        id = "desktop-copilot"
        enabled = True
        desktop_access = True

    class Registry:
        def get_by_id(self, agent_id):
            return None

        def enabled_agents(self):
            return [Definition()]

    async def fake_stream(definition, prompt, **kwargs):
        yield {"type": "agent:token", "text": "It says "}
        yield {"type": "agent:completed", "output": "It says 42."}

    monkeypatch.setattr(registry, "get_registry", lambda: Registry())
    monkeypatch.setattr(service, "stream_agent", fake_stream)

    response = client.post("/api/desktop/ask", json={"input": "what is on screen?"})
    assert response.status_code == 200, response.text
    assert "agent:token" in response.text
    assert "It says 42." in response.text
    assert '"type": "done"' in response.text


def test_apps_lists_every_window_for_the_popup(client, monkeypatch, tmp_path):
    from palimind.agents.tools.desktop import client as desktop_client

    source = tmp_path / "shot.png"
    Image.new("RGB", (10, 10), (255, 255, 255)).save(source)
    monkeypatch.setattr(desktop_client, "get_client", lambda *a, **k: _FakeClient(source))

    response = client.get("/api/desktop/apps?kind=windows")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert [item["app_name"] for item in body["items"]] == ["gnome-calculator", "nautilus"]
    assert body["items"][0]["is_focused"] is True


def test_ask_without_agents_uses_a_transient_any_app_copilot(client, monkeypatch):
    from palimind.agents import registry, service

    captured = {}

    class EmptyRegistry:
        def get_by_id(self, agent_id):
            return None

        def enabled_agents(self):
            return []

    async def fake_stream(definition, prompt, **kwargs):
        captured["definition"] = definition
        captured["prompt"] = prompt
        captured["interactive"] = kwargs.get("interactive")
        yield {"type": "agent:completed", "output": "ok"}

    monkeypatch.setattr(registry, "get_registry", lambda: EmptyRegistry())
    monkeypatch.setattr(service, "stream_agent", fake_stream)

    response = client.post(
        "/api/desktop/ask",
        json={
            "input": "what is open?",
            "mode": "ask",
            "app": "gnome-calculator",
            "window_id": "w-1",
        },
    )
    assert response.status_code == 200, response.text
    definition = captured["definition"]
    assert definition.desktop_access is True
    assert definition.desktop_control is True
    assert definition.tool_pack == "desktop"
    assert captured["interactive"] is False
    assert "gnome-calculator" in captured["prompt"]
    assert "w-1" in captured["prompt"]


def test_ask_uses_the_popup_model_override(client, monkeypatch):
    from palimind.agents import registry, service

    captured = {}

    class EmptyRegistry:
        def get_by_id(self, agent_id):
            return None

        def enabled_agents(self):
            return []

    async def fake_stream(definition, prompt, **kwargs):
        captured["definition"] = definition
        yield {"type": "agent:completed", "output": "ok"}

    monkeypatch.setattr(registry, "get_registry", lambda: EmptyRegistry())
    monkeypatch.setattr(service, "stream_agent", fake_stream)

    response = client.post(
        "/api/desktop/ask",
        json={"input": "what is open?", "model": "qwen2.5:7b"},
    )
    assert response.status_code == 200, response.text
    assert captured["definition"].model == "qwen2.5:7b"


def test_act_mode_streams_with_approvals_enabled(client, monkeypatch):
    from palimind.agents import registry, service

    captured = {}

    class EmptyRegistry:
        def get_by_id(self, agent_id):
            return None

        def enabled_agents(self):
            return []

    async def fake_stream(definition, prompt, **kwargs):
        captured["interactive"] = kwargs.get("interactive")
        yield {"type": "agent:completed", "output": "done"}

    monkeypatch.setattr(registry, "get_registry", lambda: EmptyRegistry())
    monkeypatch.setattr(service, "stream_agent", fake_stream)
    # The ephemeral definition is constructed inside the router; the approval
    # channel is the interactive flag, which is what the popup relies on.
    response = client.post(
        "/api/desktop/ask",
        json={"input": "open the menu", "mode": "act"},
    )
    assert response.status_code == 200, response.text
    assert captured["interactive"] is True


def test_health_reports_default_allow(client, monkeypatch, tmp_path):
    from palimind.agents.tools.desktop import client as desktop_client

    class StatusClient(_FakeClient):
        def status(self):
            return {
                "ok": True,
                "data": {
                    "session_type": "wayland",
                    "permissions": {"accessibility": {"state": "granted"}},
                    "policy": {"enabled": True, "stopped": False},
                },
            }

    source = tmp_path / "shot.png"
    Image.new("RGB", (10, 10), (255, 255, 255)).save(source)
    monkeypatch.setattr(desktop_client, "get_client", lambda *a, **k: StatusClient(source))
    body = client.get("/api/desktop/health").json()
    assert body["ok"] is True
    assert body["ready"] is True
    assert body["default_allow"] is True


def test_screenshot_is_refused_when_computer_use_is_disabled(client, monkeypatch):
    from palimind import settings

    monkeypatch.setattr(settings, "DESKTOP_ENABLE", False)
    response = client.post("/api/desktop/screenshot", json={"screen": 0})
    assert response.status_code == 403
