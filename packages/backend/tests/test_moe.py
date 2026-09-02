"""Unit tests for the Mixture-of-Experts pipeline improvements.

No network: LLM calls are mocked with httpx.MockTransport; concurrency
checks monkeypatch /api/ps.
"""

from __future__ import annotations

import json

import httpx

from palimind.llm.mixture_of_expert import orchestrator
from palimind.llm.mixture_of_expert.agents import (
    _budget_for_sub_task,
    _chat_messages,
    _compact_context,
    _estimated_tokens,
)
from palimind.llm.mixture_of_expert.llm import LLMError, llm_chat, llm_chat_safe
from palimind.llm.mixture_of_expert.planner import (
    build_agent_prompt,
    build_verify_prompt,
)

# ── context compaction ────────────────────────────────────────────────────


def test_compact_context_bounds_live_window() -> None:
    live: list[dict] = []
    for _ in range(8):
        live.append({"role": "assistant", "content": "a" * 400})
        live.append({"role": "user", "content": "b" * 400})
    notes = _compact_context(live, [], budget_tokens=300)
    assert _estimated_tokens([m.get("content", "") for m in live]) <= 300
    assert len(notes) >= 1
    assert all("- " in n for n in notes)


def test_compact_context_preserves_pairs() -> None:
    live = [
        {"role": "assistant", "content": "thinking"},
        {"role": "user", "content": "Tool 'x' returned: data"},
    ]
    notes = _compact_context(live, [], budget_tokens=1)
    assert live == []  # both halves of the pair are removed together
    assert notes == ["- thinking -> Tool 'x' returned: data"]


def test_chat_messages_inserts_working_notes() -> None:
    base = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    live = [{"role": "assistant", "content": "hi"}]
    msgs = _chat_messages(base, live, ["- old note"])
    assert msgs[2]["role"] == "system"
    assert "WORKING NOTES" in msgs[2]["content"]
    assert msgs[3:] == live


def test_chat_messages_omits_notes_when_empty() -> None:
    base = [{"role": "system", "content": "sys"}]
    msgs = _chat_messages(base, [], [])
    assert msgs == base


# ── adaptive budgets ──────────────────────────────────────────────────────


def test_budget_for_sub_task() -> None:
    assert _budget_for_sub_task({"tools": []}, 12) == 8
    assert _budget_for_sub_task({"tools": ["run_python"]}, 12) == 10
    assert _budget_for_sub_task({"tools": ["web_search", "fetch_url"]}, 12) == 10
    assert _budget_for_sub_task({"tools": ["web_search", "run_python"]}, 12) == 12
    assert _budget_for_sub_task({"tools": ["run_python"]}, 6) == 6


# ── verification helpers ──────────────────────────────────────────────────


def test_needs_refinement() -> None:
    assert orchestrator._needs_refinement({}) is False
    assert orchestrator._needs_refinement({"answers_query": True}) is False
    assert orchestrator._needs_refinement({"answers_query": False}) is True
    assert orchestrator._needs_refinement({"conflicts": "A says X, B says Y"}) is True
    assert orchestrator._needs_refinement({"missing_facts": "   "}) is False


def test_format_verify_feedback() -> None:
    fb = orchestrator._format_verify_feedback(
        {"conflicts": "A vs B", "missing_scope": "did not answer"}
    )
    assert "Conflicting or unsupported claims" in fb
    assert "A vs B" in fb
    assert "did not answer" in fb


def test_build_verify_prompt_and_agent_briefing() -> None:
    sub_task = {"agent_id": 1, "label": "L", "task": "t", "tools": [], "context": ""}
    prompt = build_agent_prompt(1, sub_task, "model", briefing="SHARED BRIEFING DATA")
    assert "SHARED WEB BRIEFING" in prompt
    assert "SHARED BRIEFING DATA" in prompt

    verify = build_verify_prompt("q", "draft", [{"agent_id": 1, "output": "out"}])
    assert "answers_query" in verify
    assert "missing_facts" in verify


# ── concurrency ───────────────────────────────────────────────────────────


def test_is_trivial_query() -> None:
    assert orchestrator._is_trivial_query("hello") is True
    assert orchestrator._is_trivial_query("") is True
    assert orchestrator._is_trivial_query("What is the capital of France?") is True
    # Web/code/doc hints must force the full pipeline even when short
    assert orchestrator._is_trivial_query("latest AI news") is False
    assert orchestrator._is_trivial_query("debug this python function") is False
    assert orchestrator._is_trivial_query("what's in my documents") is False
    # Long query without hints is not confidently trivial
    assert (
        orchestrator._is_trivial_query(
            "Explain the history of the Roman Empire, its rise, major emperors, "
            "and the eventual fall of the western empire in detail"
        )
        is False
    )


def test_is_simple_route() -> None:
    assert orchestrator._is_simple_route({"simple": True}) is True
    assert orchestrator._is_simple_route({"simple": False}) is False
    assert orchestrator._is_simple_route({"simple": True, "needs_web": True}) is False
    assert orchestrator._is_simple_route({"simple": True, "needs_code": True}) is False
    assert orchestrator._is_simple_route({"simple": True, "needs_docs": False}) is True


def test_agent_count_for_route() -> None:
    assert orchestrator._agent_count_for_route({"simple": True}, 4) == 1
    # simple + tool needs: not the direct path, but still a light 2-agent run
    assert orchestrator._agent_count_for_route({"simple": True, "needs_web": True}, 4) == 2
    assert orchestrator._agent_count_for_route({"simple": False}, 4) == 4


def test_default_plan_engineer_only_for_code() -> None:
    route = {"needs_web": False, "needs_docs": False, "needs_code": False}
    plan = orchestrator._default_plan("q", route, 4)
    labels = [a["label"] for a in plan]
    assert "Engineer" not in labels
    tools = [t for a in plan for t in a["tools"]]
    assert "run_python" not in tools
    assert "list_files" not in tools  # analyst reasons directly without docs

    route_code = {"needs_web": False, "needs_docs": False, "needs_code": True}
    plan_code = orchestrator._default_plan("q", route_code, 4)
    assert "Engineer" in [a["label"] for a in plan_code]

    route_docs = {"needs_web": False, "needs_docs": True, "needs_code": False}
    plan_docs = orchestrator._default_plan("q", route_docs, 4)
    analyst = next(a for a in plan_docs if a["label"] == "Analyst")
    assert analyst["tools"] == ["document_search"]


def test_max_concurrency_override(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "MOE_MAX_CONCURRENCY", 3)
    assert orchestrator._max_concurrency(4, "http://ollama:11434", "m") == 3


def test_max_concurrency_loaded_model_caps_at_two(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "MOE_MAX_CONCURRENCY", 0)
    monkeypatch.setattr(orchestrator, "_model_is_loaded", lambda url, model: True)
    assert orchestrator._max_concurrency(4, "http://ollama:11434", "m") == 2


def test_max_concurrency_unloaded_model_uses_ram_clamp(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "MOE_MAX_CONCURRENCY", 0)
    monkeypatch.setattr(orchestrator, "_model_is_loaded", lambda url, model: False)
    assert 1 <= orchestrator._max_concurrency(4, "http://ollama:11434", "m") <= 4


# ── llm_chat: num_ctx, usage, retries ─────────────────────────────────────


def test_llm_chat_sends_num_ctx_option() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "ok"}})

    transport = httpx.MockTransport(handler)
    llm_chat(
        [{"role": "user", "content": "hi"}],
        "m",
        "http://ollama:11434",
        num_ctx=2048,
        transport=transport,
    )
    assert captured["payload"]["options"]["num_ctx"] == 2048


def test_llm_chat_captures_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"content": "ok"},
                "prompt_eval_count": 10,
                "eval_count": 5,
            },
        )

    transport = httpx.MockTransport(handler)
    result = llm_chat(
        [{"role": "user", "content": "hi"}],
        "m",
        "http://ollama:11434",
        transport=transport,
    )
    assert result["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}


def test_llm_chat_safe_retries_transient_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(
            200,
            json={
                "message": {"content": "ok"},
                "prompt_eval_count": 7,
                "eval_count": 3,
            },
        )

    transport = httpx.MockTransport(handler)
    result = llm_chat_safe(
        [{"role": "user", "content": "hi"}],
        "m",
        "http://ollama:11434",
        retries=2,
        transport=transport,
    )
    assert len(calls) == 2
    assert result["content"] == "ok"
    assert result["usage"] == {"prompt_tokens": 7, "completion_tokens": 3}


def test_llm_chat_safe_gives_up_after_retries() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, text="busy")

    transport = httpx.MockTransport(handler)
    result = llm_chat_safe(
        [{"role": "user", "content": "hi"}],
        "m",
        "http://ollama:11434",
        retries=1,
        transport=transport,
    )
    assert len(calls) == 2  # 1 original + 1 retry
    assert result["content"].startswith("[LLM error")


def test_llm_chat_safe_no_retry_on_permanent_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, text="not-json")

    transport = httpx.MockTransport(handler)
    result = llm_chat_safe(
        [{"role": "user", "content": "hi"}],
        "m",
        "http://ollama:11434",
        retries=2,
        transport=transport,
    )
    assert len(calls) == 1  # JSON decode failure is permanent
    assert result["content"].startswith("[LLM error")


def test_llm_error_transient_flag() -> None:
    assert LLMError("timeout", transient=True).transient is True
    assert LLMError("bad json", transient=False).transient is False
