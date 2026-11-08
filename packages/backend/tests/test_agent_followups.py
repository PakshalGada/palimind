"""Tests for follow-up suggestions, usage events and model escalation."""

from __future__ import annotations

from palimind.agents import pricing, suggestions


def test_parse_suggestions_accepts_object_array_and_fence() -> None:
    assert suggestions.parse_suggestions('{"suggestions": ["A", "B"]}') == ["A", "B"]
    assert suggestions.parse_suggestions('["One", {"text": "Two"}]') == ["One", "Two"]
    fenced = '```json\n{"suggestions": ["Fenced"]}\n```'
    assert suggestions.parse_suggestions(fenced) == ["Fenced"]
    assert suggestions.parse_suggestions("not json") == []


def test_heuristic_suggestions_follow_the_tools_used() -> None:
    web = suggestions.heuristic_suggestions("research", "answer", ["web_search", "fetch_url"])
    assert any("sources" in item.lower() for item in web)
    code = suggestions.heuristic_suggestions("fix", "answer", ["write_file"])
    assert any("changed" in item.lower() for item in code)
    data = suggestions.heuristic_suggestions("chart", "answer", ["csv_query"])
    assert any("chart" in item.lower() for item in data)


def test_generate_suggestions_uses_model_then_falls_back(monkeypatch) -> None:
    from palimind.llm.mixture_of_expert import llm as llm_mod

    seen: list[str] = []

    def fake_chat(_messages, model, _url, **kwargs):
        seen.append(model)
        return {
            "content": '{"suggestions": ["Check the primary source", "Compare the numbers", "Write a brief"]}',
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
        }

    monkeypatch.setattr(llm_mod, "llm_chat_safe", fake_chat)
    usage: list[dict] = []
    out = suggestions.generate_suggestions(
        "Compare the reports",
        "The reports disagree on revenue.",
        "light-model",
        "http://localhost:11434",
        tool_names=["web_search"],
        usage_cb=usage.append,
    )
    assert out[0] == "Check the primary source"
    assert seen == ["light-model"]
    assert usage == [{"prompt_tokens": 12, "completion_tokens": 8}]

    def broken_chat(*_args, **_kwargs):
        raise RuntimeError("model offline")

    monkeypatch.setattr(llm_mod, "llm_chat_safe", broken_chat)
    fallback = suggestions.generate_suggestions(
        "Compare the reports",
        "The reports disagree on revenue.",
        "light-model",
        "http://localhost:11434",
        tool_names=["web_search"],
    )
    assert fallback == suggestions.heuristic_suggestions(
        "Compare the reports", "The reports disagree on revenue.", ["web_search"]
    )


def test_generate_suggestions_never_calls_the_model_without_an_answer(monkeypatch) -> None:
    from palimind.llm.mixture_of_expert import llm as llm_mod

    called: list[int] = []

    def fake_chat(*_args, **_kwargs):
        called.append(1)
        return {"content": "[]", "usage": {}}

    monkeypatch.setattr(llm_mod, "llm_chat_safe", fake_chat)
    out = suggestions.generate_suggestions("task", "", "model", "url")
    assert out
    assert called == []


def test_usage_and_cost_are_normalized(monkeypatch) -> None:
    monkeypatch.setattr(pricing, "COST_INPUT_PER_MTOK", 2.0)
    monkeypatch.setattr(pricing, "COST_OUTPUT_PER_MTOK", 8.0)
    payload = pricing.usage_payload({"prompt_tokens": 1_000_000, "completion_tokens": 500_000})
    assert payload["prompt_tokens"] == 1_000_000
    assert payload["completion_tokens"] == 500_000
    assert payload["estimated_cost_usd"] == 6.0
    assert pricing.usage_payload(None)["estimated_cost_usd"] == 0.0


def test_record_run_persists_suggestions_and_usage_stages(monkeypatch) -> None:
    from palimind.agents import runtime
    from palimind.storage import state_store

    stored: list[dict] = []

    def fake_append(agent_id, run_id, entry, limit):
        stored.append({"agent_id": agent_id, "run_id": run_id, "entry": entry, "limit": limit})

    monkeypatch.setattr(state_store, "append_run", fake_append)
    runtime.record_run(
        "agent-1",
        "run-1",
        "input",
        "output",
        "success",
        1.0,
        suggestions=["What changed?", "Add a test."],
        usage_stages={
            "agent": {"prompt_tokens": 100, "completion_tokens": 50},
            "followups": {"prompt_tokens": 7, "completion_tokens": 3},
        },
    )
    entry = stored[0]["entry"]
    assert entry["suggestions"] == ["What changed?", "Add a test."]
    assert entry["usage_stages"]["agent"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert entry["usage_stages"]["followups"] == {"prompt_tokens": 7, "completion_tokens": 3}


def test_starter_prompts_follow_the_agent_brief() -> None:
    from types import SimpleNamespace

    from palimind.agents.suggestions import starter_prompts

    prompts = starter_prompts(
        SimpleNamespace(
            display_name="Scout",
            name="scout",
            goal="Track competitor releases every morning.",
            title="",
            description="",
            skills=["competitor-watch"],
            tool_pack="research",
        )
    )
    assert 1 <= len(prompts) <= 4
    joined = " ".join(prompts).lower()
    assert "competitor" in joined
    assert all("…" not in prompt or prompt.endswith("…") for prompt in prompts)

    generic = starter_prompts(
        SimpleNamespace(
            display_name="",
            name="helper",
            goal="",
            title="",
            description="",
            skills=[],
            tool_pack="auto",
        )
    )
    assert 1 <= len(generic) <= 4
    assert all(isinstance(prompt, str) and prompt for prompt in generic)


def test_record_run_persists_the_plan(monkeypatch) -> None:
    from palimind.agents import runtime
    from palimind.storage import state_store

    stored: list[dict] = []

    def fake_append(agent_id, run_id, entry, limit):
        stored.append({"entry": entry})

    monkeypatch.setattr(state_store, "append_run", fake_append)
    runtime.record_run(
        "agent-1",
        "run-plan",
        "input",
        "output",
        "success",
        1.0,
        plan=[
            {"label": "Find sources", "status": "completed"},
            {"label": "Write the brief", "status": "completed"},
        ],
    )
    assert stored[0]["entry"]["plan"] == [
        {"label": "Find sources", "status": "completed"},
        {"label": "Write the brief", "status": "completed"},
    ]
