"""Unit tests for model routing / availability fallback (no network)."""

from __future__ import annotations

from palimind.opencode import router


def _patch(monkeypatch, local: set[str], opencode: set[str] | None = None) -> None:
    monkeypatch.setattr(router, "fetch_ollama_model_ids", lambda url, timeout=8: set(local))
    monkeypatch.setattr(router, "opencode_model_ids", lambda: set(opencode or set()))


def test_resolve_model_keeps_installed_local_model(monkeypatch) -> None:
    _patch(monkeypatch, {"gemma4:e2b", "llama3:8b"})
    model, url, note = router.resolve_model(
        "gemma4:e2b", "http://localhost:11434", fallback_model="gemma4:e2b"
    )
    assert (model, url, note) == ("gemma4:e2b", "http://localhost:11434", "")


def test_resolve_model_falls_back_to_field_default(monkeypatch) -> None:
    _patch(monkeypatch, {"gemma4:e2b"})
    model, url, note = router.resolve_model(
        "deepseek-v4-flash", "http://localhost:11434", fallback_model="gemma4:e2b"
    )
    assert model == "gemma4:e2b"
    assert url == "http://localhost:11434"
    assert "deepseek-v4-flash" in note and "gemma4:e2b" in note


def test_resolve_model_falls_back_to_first_installed(monkeypatch) -> None:
    _patch(monkeypatch, {"zeta:1", "alpha:1"})
    model, _url, note = router.resolve_model("ghost", "http://localhost:11434")
    assert model == "alpha:1"
    assert "ghost" in note


def test_resolve_model_routes_opencode_model_to_proxy(monkeypatch) -> None:
    """With a valid key the model is served by OpenCode and must NOT fall back."""
    _patch(monkeypatch, {"gemma4:e2b"}, opencode={"deepseek-v4-flash"})
    model, url, note = router.resolve_model(
        "deepseek-v4-flash",
        "http://localhost:11434",
        fallback_model="gemma4:e2b",
    )
    assert model == "deepseek-v4-flash"
    assert url == router.PROXY_URL
    assert note == ""


def test_resolve_model_picks_local_when_opencode_preferred(monkeypatch) -> None:
    """A user may choose a local Ollama model even with a key configured."""
    _patch(monkeypatch, {"gemma4:e2b"}, opencode={"deepseek-v4-flash"})
    model, url, note = router.resolve_model("gemma4:e2b", "http://localhost:11434")
    assert (model, url, note) == ("gemma4:e2b", "http://localhost:11434", "")


def test_resolve_model_best_effort_when_check_fails(monkeypatch) -> None:
    def boom(url, timeout=8):
        raise RuntimeError("offline")

    monkeypatch.setattr(router, "fetch_ollama_model_ids", boom)
    monkeypatch.setattr(router, "opencode_model_ids", lambda: set())
    model, url, note = router.resolve_model("whatever", "http://localhost:11434")
    assert (model, url, note) == ("whatever", "http://localhost:11434", "")
