"""Tests for the local model capability registry."""

from __future__ import annotations

from palimind import model_capabilities as mc


def test_infers_vision_tools_and_context() -> None:
    caps = mc.infer_from_name("qwen2.5-vl:7b")
    assert caps.supports_vision
    assert caps.supports_tools
    assert caps.context_window >= 32768


def test_infers_reasoning_and_code() -> None:
    assert mc.infer_from_name("deepseek-r1:8b").supports_reasoning
    assert "code" in mc.infer_from_name("qwen2.5-coder:7b").capabilities


def test_infers_embedding_dimensions() -> None:
    caps = mc.infer_from_name("nomic-embed-text:latest")
    assert caps.is_embedding
    assert caps.embedding_dim == 768


def test_unknown_model_degrades_gracefully() -> None:
    caps = mc.infer_from_name("totally-unknown:1b")
    assert caps.model_id == "totally-unknown:1b"
    assert caps.source == "inferred"


def test_pick_model_requires_every_capability() -> None:
    candidates = ["nomic-embed-text", "llava:7b", "llama3.2-vision:11b", "qwen2.5:7b"]
    assert mc.pick_model(["vision"], candidates) == "llava:7b"
    assert mc.pick_model(["vision", "tools"], candidates) == "llama3.2-vision:11b"
    assert mc.pick_model(["embedding"], candidates) == "nomic-embed-text"
    assert mc.pick_model(["vision", "embedding"], candidates) is None


def test_ollama_show_refines_capabilities(monkeypatch) -> None:
    mc.clear_cache()
    monkeypatch.setattr(
        mc,
        "_ollama_show",
        lambda model, base: {
            "capabilities": ["completion", "tools", "vision"],
            "model_info": {"qwen2.context_length": 32768},
            "details": {
                "family": "qwen2",
                "parameter_size": "7B",
                "quantization_level": "Q4_K_M",
            },
        },
    )
    caps = mc.get_capabilities("custom-model", "http://localhost:11434")
    assert caps.source == "ollama"
    assert caps.supports_vision and caps.supports_tools
    assert caps.context_window == 32768
    assert caps.parameter_size == "7B"


def test_ollama_failure_keeps_inferred_capabilities(monkeypatch) -> None:
    mc.clear_cache()
    monkeypatch.setattr(mc, "_ollama_show", lambda model, base: None)
    caps = mc.get_capabilities("llava:7b", "http://localhost:11434")
    assert caps.source == "inferred"
    assert caps.supports_vision


def test_capabilities_endpoint(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server
    from palimind import model_capabilities as caps_mod

    monkeypatch.setattr(
        server,
        "_fetch_ollama_models_blocking",
        lambda url: [{"model_id": "llava:7b"}, {"model_id": "qwen2.5:7b"}],
    )
    monkeypatch.setattr(
        caps_mod,
        "get_capabilities",
        lambda model, base_url="", **kw: mc.infer_from_name(model),
    )
    client = TestClient(server.app)
    resp = client.get("/api/models/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    ids = {m["model_id"] for m in body["models"]}
    assert {"llava:7b", "qwen2.5:7b"} <= ids
