"""Tests for the multi-agent orchestrator helpers."""

from __future__ import annotations

from palimind.agents import orchestrator as orch


def test_blackboard_post_and_render() -> None:
    board = orch.Blackboard()
    board.post(1, "Researcher", "found facts", task="research")
    board.post(2, "Analyst", "analysed", task="analyse")
    entries = board.entries()
    assert len(entries) == 2
    rendered = board.render()
    assert "Researcher" in rendered and "found facts" in rendered


def test_clamp_agent_count() -> None:
    assert orch.clamp_agent_count(0) >= 1
    assert orch.clamp_agent_count(100) <= orch.ORCHESTRATOR_MAX_AGENTS
    assert orch.clamp_agent_count(None) == min(
        orch.ORCHESTRATOR_DEFAULT_AGENTS, orch.ORCHESTRATOR_MAX_AGENTS
    )


def test_default_subtasks_respects_count() -> None:
    tasks = orch._default_subtasks("do the thing", 3)
    assert len(tasks) == 3
    assert all("do the thing" in t["task"] for t in tasks)


def test_parse_conflicts() -> None:
    raw = (
        '{"conflicts": [{"topic": "price", "agents": [1, 2], '
        '"positions": ["$5", "$7"], "resolution": "use $5"}]}'
    )
    conflicts = orch.parse_conflicts(raw)
    assert len(conflicts) == 1 and conflicts[0]["topic"] == "price"
    assert orch.parse_conflicts('{"conflicts": []}') == []
    assert orch.parse_conflicts("garbage") == []
    assert orch.parse_conflicts(f"```json\n{raw}\n```")[0]["resolution"] == "use $5"


def test_parse_judgement() -> None:
    raw = '{"scores": [{"agent_id": 1, "score": 9}], "winner": 1, "reason": "best"}'
    result = orch.parse_judgement(raw)
    assert result["winner"] == 1 and result["scores"][0]["score"] == 9
    assert orch.parse_judgement("nope") == {}


def test_build_prompts_include_task() -> None:
    outputs = [
        {"agent_id": 1, "label": "A", "output": "one"},
        {"agent_id": 2, "label": "B", "output": "two"},
    ]
    assert "TASK" in orch.build_conflict_prompt("the task", outputs)
    assert "CANDIDATES" in orch.build_judge_prompt("the task", outputs)
