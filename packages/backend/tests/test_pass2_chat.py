"""Pass-2 chat regressions: Stop persistence, session event, global config, MoE HW check."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import palimind.api_server as server
import palimind.config as config
from palimind.hwfit.hardware import GPUInfo, HardwareProfile
from palimind.memory import session_store as ss


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(config, "GLOBAL_CONFIG_PATH", tmp_path / "global.json")
    monkeypatch.setattr(server, "GLOBAL_CONFIG_PATH", tmp_path / "global.json")
    r = tmp_path / "kb"
    r.mkdir()
    ss._STOPPED_TURNS.clear()
    return r


def _session(root: Path) -> str:
    return ss.load_sessions(root)["active_session_id"]


def _messages(root: Path, sid: str) -> list[dict]:
    return (ss.load_session_by_id(root, sid) or {}).get("messages", [])


def _events(chunks: list[str]) -> list[dict]:
    out = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data:"):
                out.append(json.loads(line[5:]))
    return out


# ── session_store: stopped turn saved exactly once ───────────────────────


def test_persist_stopped_turn_suppresses_late_generator_append(root: Path) -> None:
    sid = _session(root)
    ss.append_message_to_session(root, sid, "user", "hi")
    assert ss.persist_stopped_turn(root, sid, "partial") is True
    # The generator's finally runs later with (possibly longer) text.
    ss.append_message_to_session(root, sid, "system", "partial and more")
    msgs = _messages(root, sid)
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "hi"), ("system", "partial")]

    # The next turn is unaffected.
    ss.append_message_to_session(root, sid, "user", "again")
    ss.append_message_to_session(root, sid, "system", "full answer")
    assert [m["content"] for m in _messages(root, sid)][-2:] == ["again", "full answer"]


def test_persist_stopped_turn_no_duplicate_when_answer_already_saved(root: Path) -> None:
    sid = _session(root)
    ss.append_message_to_session(root, sid, "user", "hi")
    ss.append_message_to_session(root, sid, "system", "complete")
    assert ss.persist_stopped_turn(root, sid, "complete") is False
    assert [m["content"] for m in _messages(root, sid)] == ["hi", "complete"]


def test_persist_stopped_turn_empty_text_still_suppresses(root: Path) -> None:
    sid = _session(root)
    ss.append_message_to_session(root, sid, "user", "hi")
    assert ss.persist_stopped_turn(root, sid, "") is False
    ss.append_message_to_session(root, sid, "system", "tokens nobody saw")
    assert [m["content"] for m in _messages(root, sid)] == ["hi"]


# ── chat stream wrapper + stop endpoint (real llm_mode_stream) ───────────


def _patch_llm(monkeypatch, gate: asyncio.Event, tokens: list[str], after: list[str]):
    import palimind.generative.responder as responder
    import palimind.llm.stream as llm_stream

    async def fake_aiter(_stream):
        for t in tokens:
            yield t
        await gate.wait()
        for t in after:
            yield t

    async def no_memory(*_a, **_k):
        return None

    monkeypatch.setattr(responder, "generate_response_stream", lambda **_k: iter(()))
    monkeypatch.setattr(responder, "aiter_stream", fake_aiter)
    monkeypatch.setattr(llm_stream, "background_update_memory", no_memory)


def test_stop_persists_partial_once_and_session_event_first(root: Path, monkeypatch) -> None:
    async def run() -> None:
        gate = asyncio.Event()
        _patch_llm(monkeypatch, gate, ["Hel", "lo"], [" world"])
        sid = _session(root)
        entry = server._register_chat_stream("client-1")
        entry.bind(root, sid)
        resp = await server.llm_mode_stream(
            "hi", sid, [], None, None, "http://x", "m", root, "false"
        )
        it = server._tracked_chat_sse(entry, resp.body_iterator)

        first = _events([await it.__anext__()])[0]
        assert first == {"type": "session", "id": sid, "stream_id": "client-1"}
        seen = [await it.__anext__() for _ in range(3)]  # reasoning, Hel, lo
        assert [e.get("text") for e in _events(seen)][1:] == ["Hel", "lo"]

        result = await server.chat_stop("client-1")
        assert result == {"status": "stopped", "persisted": True, "session_id": sid}
        # Saved synchronously, before the generator notices anything.
        assert [m["content"] for m in _messages(root, sid)] == ["hi", "Hello"]
        # Idempotent.
        assert (await server.chat_stop("client-1"))["persisted"] is False

        gate.set()
        rest = [c async for c in it]  # wrapper stops and closes the generator
        assert rest == []
        assert "client-1" not in server._CHAT_STREAMS
        assert [m["content"] for m in _messages(root, sid)] == ["hi", "Hello"]

    asyncio.run(run())


def test_stop_then_abandoned_generator_finally_does_not_duplicate(root: Path, monkeypatch) -> None:
    """Client disconnect path: the generator's finally runs via aclose()."""

    async def run() -> None:
        gate = asyncio.Event()
        _patch_llm(monkeypatch, gate, ["A", "B"], [])
        sid = _session(root)
        entry = server._register_chat_stream(None)
        entry.bind(root, sid)
        resp = await server.llm_mode_stream(
            "q", sid, [], None, None, "http://x", "m", root, "false"
        )
        inner = resp.body_iterator
        it = server._tracked_chat_sse(entry, inner)
        for _ in range(4):
            await it.__anext__()
        await server.chat_stop(entry.stream_id)
        await it.aclose()
        await inner.aclose()  # what the asyncgen finalizer does on disconnect
        msgs = _messages(root, sid)
        assert [(m["role"], m["content"]) for m in msgs] == [("user", "q"), ("system", "AB")]

    asyncio.run(run())


def test_stop_unknown_stream() -> None:
    assert asyncio.run(server.chat_stop("nope")) == {
        "status": "not_found",
        "persisted": False,
        "session_id": None,
    }


def test_stream_entry_mirrors_frontend_answer_rules() -> None:
    entry = server._ChatStreamEntry(stream_id="x")
    for ev in (
        {"type": "sources", "sources": ["a.md"]},
        {"type": "token", "text": "one "},
        {"type": "token", "text": "two"},
        {"type": "answer_final", "text": "one two [1]"},
        {"type": "citation_map", "text": "one two [1].", "citations": []},
    ):
        entry.observe(f"data: {json.dumps(ev)}\n\n")
    assert entry.text == "one two [1]."
    assert entry.sources == ["a.md"]
    assert entry.citations == {"text": "one two [1].", "citations": []}
    entry.observe('data: {"type": "agent:token", "reset": true}\n\n')
    assert entry.text == ""
    entry.observe('data: {"type": "done"}\n\n')
    assert entry.finished is True


def test_chat_route_emits_session_event_for_new_chat(root: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.generative.responder as responder
    import palimind.llm.stream as llm_stream
    import palimind.memory.hierarchical as hierarchical
    import palimind.opencode.router as router

    async def fake_aiter(_stream):
        yield "ok"

    async def no_memory(*_a, **_k):
        return None

    def fake_memory(r, session_id, *_a, **_k):
        return {
            "active_sess_id": session_id or ss.load_sessions(r)["active_session_id"],
            "short_term": [],
            "mid_term_summary": None,
            "long_term_episodes": [],
        }

    monkeypatch.setattr(server, "_chat_root", lambda scope: root)
    monkeypatch.setattr(hierarchical, "get_hierarchical_memory", fake_memory)
    monkeypatch.setattr(router, "resolve_model", lambda m, u, fallback_model=None: (m, u, ""))
    monkeypatch.setattr(responder, "generate_response_stream", lambda **_k: iter(()))
    monkeypatch.setattr(responder, "aiter_stream", fake_aiter)
    monkeypatch.setattr(llm_stream, "background_update_memory", no_memory)

    client = TestClient(server.app)
    with client.stream(
        "GET", "/api/chat", params={"q": "hello", "scope": "chat", "stream_id": "s-1"}
    ) as r:
        body = "".join(r.iter_text())
    events = _events([body])
    sid = _session(root)
    assert events[0] == {"type": "session", "id": sid, "stream_id": "s-1"}
    assert events[-1]["type"] == "done"
    assert [m["content"] for m in _messages(root, sid)] == ["hello", "ok"]
    assert "s-1" not in server._CHAT_STREAMS


# ── global config: atomic writes ─────────────────────────────────────────


def test_write_global_config_is_atomic(root: Path, monkeypatch) -> None:
    path = server.GLOBAL_CONFIG_PATH
    server._write_global_config({"chat_model": "a"})
    assert json.loads(path.read_text("utf-8")) == {"chat_model": "a"}

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(server._os, "replace", boom)
    with pytest.raises(OSError):
        server._write_global_config({"chat_model": "b"})
    assert json.loads(path.read_text("utf-8")) == {"chat_model": "a"}
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_server_global_config_path_matches_config_module() -> None:
    # The server must write the same file load_global_config() reads.
    import importlib

    fresh = importlib.import_module("palimind.config")
    assert server._palimind_config is fresh


# ── MoE hardware check ignores CPU-backend GPUs ──────────────────────────


def test_moe_hardware_check_ignores_cpu_backend_gpus(monkeypatch) -> None:
    import palimind.hwfit.hardware as hardware
    import palimind.llm.mixture_of_expert as moe

    hw = HardwareProfile(
        gpus=[GPUInfo("Intel iGPU", 16000, "cpu"), GPUInfo("RTX", 8000, "cuda")],
        total_ram_mb=32000,
    )
    seen: dict = {}
    real = moe.estimate_hardware_requirements

    def fake_estimate(orch, worker, num_workers, gpu_vram_mb, system_ram_mb):
        seen["vram"] = gpu_vram_mb
        return real(
            orch,
            worker,
            num_workers=num_workers,
            gpu_vram_mb=gpu_vram_mb,
            system_ram_mb=system_ram_mb,
        )

    monkeypatch.setattr(hardware, "detect_hardware", lambda: hw)
    monkeypatch.setattr(server.state, "active_field", None)
    monkeypatch.setattr(moe, "estimate_hardware_requirements", fake_estimate)
    out = asyncio.run(server.moe_hardware_check())
    assert seen["vram"] == 8000
    assert out["gpu_vram_mb"] == 8000
