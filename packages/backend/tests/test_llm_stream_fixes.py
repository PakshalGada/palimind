"""Regression tests for LLM streaming / MoE / deep-research / hwfit / audio /
hotkey / CLI bug fixes. No network, no Ollama, nothing written to ~/.palimind.
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from palimind.exceptions import ResponseError
from palimind.generative import responder
from palimind.llm import stream as llm_stream
from palimind.llm.deep_research import pipeline as dr_pipeline
from palimind.llm.mixture_of_expert import orchestrator
from palimind.llm.mixture_of_expert.hardware import estimate_model_vram
from palimind.llm.mixture_of_expert.llm import LLMError, _normalize_tool_calls, llm_chat_stream

# ── helpers ───────────────────────────────────────────────────────────────


def _patch_httpx_client(monkeypatch, handler) -> None:
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(responder.httpx, "Client", factory)


def _ndjson(lines: list[dict]) -> bytes:
    return b"".join(json.dumps(line).encode() + b"\n" for line in lines)


def _sse_events(chunks: list[str]) -> list[dict]:
    return [json.loads(c[len("data: ") :]) for c in chunks if c.startswith("data: ")]


# ── responder: Ollama thinking field, errors, num_ctx ─────────────────────


def test_responder_forwards_ollama_thinking_field(monkeypatch) -> None:
    body = _ndjson(
        [
            {"message": {"role": "assistant", "content": "", "thinking": "Let me "}},
            {"message": {"role": "assistant", "content": "", "thinking": "think."}},
            {"message": {"role": "assistant", "content": "Hi"}},
            {"message": {"role": "assistant", "content": ""}, "done": True},
        ]
    )
    _patch_httpx_client(monkeypatch, lambda req: httpx.Response(200, content=body))
    reasoning: list[str] = []
    tokens = list(
        responder.generate_response_stream(
            "q", "", [], "http://x", "qwen3:4b", "", is_chat_only=True,
            on_reasoning=reasoning.append,
        )
    )
    assert tokens == ["Hi"]
    assert "".join(reasoning) == "Let me think."


def test_responder_does_not_retry_after_reasoning_was_delivered(monkeypatch) -> None:
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            stream = httpx.ByteStream(
                _ndjson([{"message": {"content": "", "thinking": "partial"}}])
            )

            class Broken(httpx.SyncByteStream):
                def __iter__(self):
                    yield from stream
                    raise httpx.RemoteProtocolError("peer closed")

            return httpx.Response(200, stream=Broken())
        return httpx.Response(200, content=_ndjson([{"message": {"content": "x"}}]))

    _patch_httpx_client(monkeypatch, handler)
    monkeypatch.setattr(responder.time, "sleep", lambda s: None)
    reasoning: list[str] = []
    with pytest.raises(ResponseError):
        list(
            responder.generate_response_stream(
                "q", "", [], "http://x", "m", "", is_chat_only=True,
                on_reasoning=reasoning.append,
            )
        )
    # The reasoning was not replayed by a retry.
    assert reasoning == ["partial"]
    assert calls["n"] == 1


def test_responder_surfaces_model_not_found_detail(monkeypatch) -> None:
    _patch_httpx_client(
        monkeypatch,
        lambda req: httpx.Response(404, json={"error": "model 'nope' not found"}),
    )
    with pytest.raises(ResponseError) as exc:
        list(responder.generate_response_stream("q", "", [], "http://x", "nope", ""))
    assert "not found" in str(exc.value)
    assert "nope" in str(exc.value)


def test_effective_num_ctx_reserves_room_for_the_answer() -> None:
    # ~3000-token prompt: the window must leave room for a long reply instead
    # of prompt+512 (which makes Ollama shift out the prompt mid-answer).
    msgs = [{"role": "user", "content": "x" * 9000}]
    ctx = responder._effective_num_ctx(msgs, 16384)
    assert ctx >= 3000 + 4096
    assert ctx % 2048 == 0
    # Never exceeds the configured ceiling.
    assert responder._effective_num_ctx([{"content": "x" * 90000}], 16384) == 16384
    # Small prompt-length changes keep the same window (no model reload).
    a = responder._effective_num_ctx([{"content": "x" * 100}], 16384)
    b = responder._effective_num_ctx([{"content": "x" * 400}], 16384)
    assert a == b


# ── aiter_stream: off the event loop, closes on early exit ────────────────


def test_aiter_stream_does_not_block_event_loop_and_closes_source() -> None:
    closed = threading.Event()

    def slow_tokens():
        try:
            for i in range(50):
                time.sleep(0.05)
                yield str(i)
        finally:
            closed.set()

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        t = asyncio.create_task(ticker())
        got = []
        agen = responder.aiter_stream(slow_tokens())
        async for tok in agen:
            got.append(tok)
            if len(got) == 3:
                break
        await agen.aclose()
        t.cancel()
        return got, ticks

    got, ticks = asyncio.run(main())
    assert got == ["0", "1", "2"]
    assert ticks >= 5  # the loop kept running while tokens were produced
    assert closed.wait(2.0)  # source generator (HTTP stream) was closed


def test_aiter_stream_propagates_errors() -> None:
    def boom():
        yield "a"
        raise ResponseError("bad")

    async def main():
        out = []
        with pytest.raises(ResponseError):
            async for tok in responder.aiter_stream(boom()):
                out.append(tok)
        return out

    assert asyncio.run(main()) == ["a"]


# ── llm_mode_stream: thinking events ──────────────────────────────────────


def _run_plain_stream(monkeypatch, fake_stream) -> list[dict]:
    import palimind.config

    monkeypatch.setattr(palimind.config, "load_config", lambda root: {"num_ctx": 4096})
    monkeypatch.setattr(responder, "generate_response_stream", fake_stream)

    async def main():
        resp = await llm_stream.llm_mode_stream(
            "q", None, None, None, None, "http://x", "m", Path("/nonexistent"), "off"
        )
        return [c async for c in resp.body_iterator]

    return _sse_events(asyncio.run(main()))


def test_llm_mode_emits_reasoning_once_and_flushes_trailing(monkeypatch) -> None:
    def fake(**kw):
        cb = kw["on_reasoning"]
        cb("step 1. ")
        yield "Answer"
        cb("late thought")
        yield " done"
        cb("tail")

    events = _run_plain_stream(monkeypatch, fake)
    thinking = [e["text"] for e in events if e["type"] == "thinking"]
    # Frontend appends thinking events: every fragment exactly once.
    assert "".join(thinking) == "step 1. late thoughttail"
    assert [e["text"] for e in events if e["type"] == "token"] == ["Answer", " done"]
    assert events[-1]["type"] == "done"


def test_llm_mode_reasoning_only_output_is_not_dropped(monkeypatch) -> None:
    def fake(**kw):
        kw["on_reasoning"]("only thinking")
        return
        yield  # pragma: no cover

    events = _run_plain_stream(monkeypatch, fake)
    assert [e["text"] for e in events if e["type"] == "thinking"] == ["only thinking"]


# ── MoE / deep research stream: client disconnect cancels the pipeline ────


def test_moe_stream_disconnect_cancels_pipeline(monkeypatch) -> None:
    import palimind.llm.mixture_of_expert as moe_pkg

    state = {"cancelled": False}

    async def fake_pipeline(**kw):
        try:
            await kw["on_progress"]({"type": "planning", "text": "planning"})
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        return {}

    monkeypatch.setattr(moe_pkg, "run_moe_pipeline", fake_pipeline)

    async def main():
        resp = await llm_stream.moe_mode_stream(
            "q", None, None, None, None, "http://x", "m", Path("/nonexistent"), "off"
        )
        it = resp.body_iterator
        await it.__anext__()  # initial reasoning
        await it.__anext__()  # planning progress
        await it.aclose()  # client went away
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert state["cancelled"]


def test_deep_research_stream_emits_reviewable_plan(monkeypatch) -> None:
    import palimind.llm.deep_research as dr_pkg
    from palimind.research.plan_registry import resolve_plan

    plan = [
        {
            "subtopic_id": 1,
            "title": "Background",
            "research_question": "What is it?",
            "search_queries": ["what is it"],
        }
    ]

    async def fake_pipeline(**kw):
        reviewed = await kw["on_plan"](plan)
        assert reviewed and reviewed[0]["title"] == "Edited"
        return {
            "plan": reviewed,
            "outputs": [],
            "synthesis": "final report",
            "citations": None,
        }

    monkeypatch.setattr(dr_pkg, "run_deep_research_pipeline", fake_pipeline)

    async def main():
        resp = await llm_stream.deep_research_mode_stream(
            "topic", None, None, None, None, "http://x", "m", Path("/nonexistent"), "on"
        )
        it = resp.body_iterator
        first = await it.__anext__()
        assert json.loads(first[len("data: ") :])["type"] == "reasoning"
        # The stream pauses on the plan until the user approves it.
        plan_event = json.loads((await it.__anext__())[len("data: ") :])
        assert plan_event["type"] == "research_plan"
        assert plan_event["query"] == "topic"
        assert plan_event["plan"][0]["title"] == "Background"
        resolve_plan(plan_event["plan_id"], plan=[{**plan[0], "title": "Edited"}])
        return [chunk async for chunk in it]

    events = _sse_events(asyncio.run(main()))
    tokens = "".join(e.get("text", "") for e in events if e["type"] == "token")
    assert "final report" in tokens


# ── MoE orchestrator robustness ───────────────────────────────────────────


def _fake_llm_safe(responses: dict[str, str]):
    def fake(messages, model, url, *, error_prefix="[LLM error", **kw):
        return {"content": responses.get(error_prefix, ""), "tool_calls": [], "usage": {}}

    return fake


def test_moe_one_failing_worker_does_not_crash_pipeline(monkeypatch) -> None:
    plan = json.dumps(
        [
            {"agent_id": 1, "label": "A", "task": "t1", "tools": []},
            {"agent_id": 2, "label": "B", "task": "t2", "tools": []},
        ]
    )
    monkeypatch.setattr(
        orchestrator,
        "llm_chat_safe",
        _fake_llm_safe(
            {
                "[router error": '{"simple": false, "needs_code": true}',
                "[orchestrator error": plan,
                "[synthesis error": "final synthesis",
            }
        ),
    )
    monkeypatch.setattr(orchestrator, "MOE_VERIFY", False)
    monkeypatch.setattr(orchestrator, "MOE_MAX_CONCURRENCY", 2)

    def fake_run_agent(agent_id, *a, **kw):
        if agent_id == 2:
            raise AttributeError("'list' object has no attribute 'items'")
        return "agent one output"

    monkeypatch.setattr(orchestrator, "run_agent", fake_run_agent)
    events: list[dict] = []

    async def on_progress(ev):
        events.append(ev)

    result = asyncio.run(
        orchestrator.run_moe_pipeline(
            "please debug this python function for me and explain the algorithm",
            "http://x",
            "orch",
            "worker",
            num_workers=2,
            on_progress=on_progress,
        )
    )
    assert result["synthesis"] == "final synthesis"
    outputs = {o["agent_id"]: o["output"] for o in result["outputs"]}
    assert outputs[1] == "agent one output"
    assert "error" in outputs[2]
    # Every started agent is reported complete (no stuck "working" spinner).
    completes = {e["agent_id"] for e in events if e["type"] == "agent_complete"}
    assert completes == {1, 2}


def test_moe_failed_refine_keeps_good_synthesis(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "llm_chat_safe",
        _fake_llm_safe(
            {
                "[router error": '{"simple": false, "needs_code": true}',
                "[orchestrator error": json.dumps([{"agent_id": 1, "task": "t", "tools": []}]),
                "[verify error": '{"answers_query": false, "missing_facts": "x"}',
            }
        ),
    )
    calls = {"n": 0}
    base = orchestrator.llm_chat_safe

    def fake(messages, model, url, *, error_prefix="[LLM error", **kw):
        if error_prefix == "[synthesis error":
            calls["n"] += 1
            content = "good answer" if calls["n"] == 1 else "[synthesis error: LLM timed out]"
            return {"content": content, "tool_calls": [], "usage": {}}
        return base(messages, model, url, error_prefix=error_prefix, **kw)

    monkeypatch.setattr(orchestrator, "llm_chat_safe", fake)
    monkeypatch.setattr(orchestrator, "MOE_VERIFY", True)
    monkeypatch.setattr(orchestrator, "MOE_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(orchestrator, "run_agent", lambda *a, **kw: "out")
    result = asyncio.run(
        orchestrator.run_moe_pipeline(
            "please debug this python function for me and explain the algorithm",
            "http://x",
            "orch",
            "worker",
            num_workers=1,
        )
    )
    assert calls["n"] == 2
    assert result["synthesis"] == "good answer"


def test_moe_non_dict_verify_or_route_json_does_not_crash() -> None:
    assert orchestrator._needs_refinement(["not", "a", "dict"]) is False  # type: ignore[arg-type]
    assert dr_pipeline._needs_refinement("text") is False  # type: ignore[arg-type]


def test_route_query_tolerates_non_object_json(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator, "llm_chat_safe", _fake_llm_safe({"[router error": '"needs_web"'})
    )
    route = orchestrator.route_query("what is the latest news", "m", "http://x")
    assert route == orchestrator.heuristic_route("what is the latest news")


def test_model_is_loaded_matches_latest_tag(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: httpx.Response(200, json={"models": [{"model": "qwen3:latest"}]}),
    )
    assert orchestrator._model_is_loaded("http://x", "qwen3")
    assert not orchestrator._model_is_loaded("http://x", "qwen3:4b")


# ── deep research: failing agent isolated ─────────────────────────────────


def test_deep_research_failing_agent_isolated(monkeypatch) -> None:
    import palimind.core.web_search as web_search

    plan = json.dumps(
        [
            {"subtopic_id": 1, "title": "A", "research_question": "qa", "search_queries": []},
            {"subtopic_id": 2, "title": "B", "research_question": "qb", "search_queries": []},
        ]
    )
    monkeypatch.setattr(
        dr_pipeline,
        "llm_chat_safe",
        _fake_llm_safe(
            {"[research-planner error": plan, "[deep-synthesis error": "the report"}
        ),
    )
    monkeypatch.setattr(dr_pipeline, "DR_VERIFY", False)
    monkeypatch.setattr(web_search, "perform_web_search", lambda *a, **kw: "")

    def fake_run_agent(subtopic_id, *a, **kw):
        if subtopic_id == 1:
            raise RuntimeError("tool exploded")
        return "research b"

    monkeypatch.setattr(dr_pipeline, "run_agent", fake_run_agent)
    result = asyncio.run(
        dr_pipeline.run_deep_research_pipeline("topic", "http://x", "o", "w", num_subtopics=2)
    )
    assert result["synthesis"] == "the report"
    outputs = {o["subtopic_id"]: o["output"] for o in result["outputs"]}
    assert "tool exploded" in outputs[1]
    assert outputs[2] == "research b"


# ── MoE LLM client ────────────────────────────────────────────────────────


def test_llm_chat_stream_raises_on_in_band_error() -> None:
    body = _ndjson([{"error": "model runner has unexpectedly stopped"}])
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=body))
    with pytest.raises(LLMError, match="unexpectedly stopped"):
        list(llm_chat_stream([{"role": "user", "content": "hi"}], "m", "http://x",
                             transport=transport))


def test_normalize_tool_calls_non_dict_arguments() -> None:
    calls = _normalize_tool_calls(
        {"tool_calls": [{"function": {"name": "web_search", "arguments": '["a", "b"]'}}]}
    )
    assert isinstance(calls[0]["arguments"], dict)


# ── hardware estimates / hwfit ────────────────────────────────────────────


def test_estimate_model_vram_handles_latest_and_effective_sizes() -> None:
    assert estimate_model_vram("nomic-embed-text:latest") == 256
    assert estimate_model_vram("llava:latest") == 4096
    assert estimate_model_vram("gemma4:e4b") == 4096
    assert estimate_model_vram("deepseek-r1:1.5b") == 1024
    assert estimate_model_vram("qwen2.5:14b-instruct-q4_K_M") == 8192


def test_rank_models_ignores_cpu_only_igpu() -> None:
    from palimind.hwfit.catalog import MODEL_CATALOG
    from palimind.hwfit.fit import rank_models
    from palimind.hwfit.hardware import GPUInfo, HardwareProfile

    hw = HardwareProfile(
        gpus=[GPUInfo(name="Intel UHD", vram_mb=2048, backend="cpu")], total_ram_mb=16384
    )
    ranked = rank_models(hw, MODEL_CATALOG, top=100)
    assert ranked
    assert all(r["fit"] in ("CPU_FALLBACK", "TOO_LARGE") for r in ranked)
    assert hw.to_dict()["best_vram_mb"] == 0


# ── audio ─────────────────────────────────────────────────────────────────


def _wav(samples: np.ndarray, rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())
    return buf.getvalue()


def test_stt_empty_wav_returns_empty_without_loading_model(monkeypatch) -> None:
    from palimind.audio import stt

    def no_model():
        raise AssertionError("model must not load for empty audio")

    monkeypatch.setattr(stt, "get_model", no_model)
    assert stt.transcribe_wav_bytes(b"") == ""
    assert stt.transcribe_wav_bytes(_wav(np.zeros(0), 48000)) == ""


def test_stt_decodes_and_resamples_to_16k_mono(monkeypatch) -> None:
    from palimind.audio import stt

    seen = {}

    class FakeModel:
        def transcribe(self, audio, beam_size=5):
            seen["audio"] = audio
            return [SimpleNamespace(text=" hello ")], None

    monkeypatch.setattr(stt, "get_model", lambda: FakeModel())
    stereo = np.full(48000 * 2, 16384)  # 1 s of 48 kHz stereo
    assert stt.transcribe_wav_bytes(_wav(stereo, 48000, channels=2)) == "hello"
    audio = seen["audio"]
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32
    assert audio.ndim == 1 and abs(audio.size - 16000) <= 1
    assert np.allclose(audio, 0.5, atol=1e-3)


def test_tts_interrupted_download_leaves_no_partial_file(monkeypatch, tmp_path) -> None:
    from palimind.audio import tts

    dest = tmp_path / "kokoro.onnx"

    def broken_retrieve(url, filename, reporthook=None):
        Path(filename).write_bytes(b"x" * 4096)
        raise OSError("connection reset")

    monkeypatch.setattr(tts.urllib.request, "urlretrieve", broken_retrieve)
    with pytest.raises(OSError):
        tts._download("http://example/x", dest, "voice model")
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


# ── hotkey ────────────────────────────────────────────────────────────────


def test_hotkey_combo_converted_to_pynput_syntax() -> None:
    from palimind.hotkey.manager import to_pynput_combo

    assert to_pynput_combo("ctrl+shift+e") == "<ctrl>+<shift>+e"
    assert to_pynput_combo("Alt+Shift+C") == "<alt>+<shift>+c"
    assert to_pynput_combo("<ctrl>+<alt>+h") == "<ctrl>+<alt>+h"
    assert to_pynput_combo("super+f5") == "<cmd>+<f5>"


def test_hotkey_trigger_with_empty_clipboard_does_not_stall(monkeypatch) -> None:
    from typer.testing import CliRunner

    import palimind.config
    from palimind.cli.commands import app
    from palimind.hotkey.manager import HotkeyManager

    monkeypatch.setattr(palimind.config, "load_config", lambda root: {})
    monkeypatch.setattr(HotkeyManager, "_capture", lambda self: None)
    start = time.monotonic()
    result = CliRunner().invoke(app, ["hotkey", "trigger"])
    assert time.monotonic() - start < 10
    assert result.exit_code == 1
    assert "Nothing captured" in result.output
