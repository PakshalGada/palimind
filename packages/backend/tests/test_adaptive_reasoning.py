"""Tests for adaptive reasoning effort allocation."""

from __future__ import annotations

from palimind.agents import adaptive_reasoning as ar


def test_effort_levels_are_ordered() -> None:
    levels = [p["level"] for p in ar.list_effort_levels()]
    assert levels == ["minimal", "standard", "high", "max"]
    # Profiles get monotonically more expensive.
    iterations = [ar.effort_profile(lv)["iterations"] for lv in levels]
    assert iterations == sorted(iterations)
    assert ar.effort_profile("max")["iterations"] > ar.effort_profile("minimal")["iterations"]


def test_heuristic_classifies_simple_and_complex() -> None:
    simple = ar.heuristic_complexity("hi")
    assert simple["level"] == "minimal"
    complex_task = ar.heuristic_complexity(
        "Research the latest 2026 literature and compare trade-offs, then design a "
        "step-by-step migration plan and implement the code, debug it and run tests."
    )
    assert complex_task["level"] in ("high", "max")
    assert complex_task["score"] > simple["score"]


def test_next_and_previous_level_clamp() -> None:
    assert ar.next_level("minimal") == "standard"
    assert ar.next_level("max") == "max"
    assert ar.previous_level("minimal") == "minimal"


def test_apply_effort_respects_agent_ceilings() -> None:
    applied = ar.apply_effort("max", max_iterations=5, context_budget=3000)
    assert applied["iterations"] == 5
    assert applied["context_budget"] == 3000
    # Without ceilings the profile target is used.
    target = ar.apply_effort("max")
    assert target["iterations"] == ar.effort_profile("max")["iterations"]


def test_resolve_effort_manual_skips_classifier() -> None:
    resolved = ar.resolve_effort("anything", "high", "model", "http://x")
    assert resolved["level"] == "high"
    assert resolved["source"] == "manual"


def test_resolve_effort_auto_without_model_uses_heuristic() -> None:
    resolved = ar.resolve_effort("hi", "auto", "", "")
    assert resolved["level"] == "minimal"
    assert resolved["source"] == "heuristic"


def test_resolve_effort_disabled(monkeypatch) -> None:
    monkeypatch.setattr(ar, "ADAPTIVE_REASONING", False)
    resolved = ar.resolve_effort("complex task", "auto", "", "")
    assert resolved["level"] == "standard"
    assert resolved["source"] == "disabled"


def test_should_escalate_signals(monkeypatch) -> None:
    monkeypatch.setattr(ar, "ADAPTIVE_ESCALATE_ON_STUCK", True)
    monkeypatch.setattr(ar, "ADAPTIVE_REASONING", True)
    assert ar.should_escalate(repeated_tool=True)
    assert ar.should_escalate(answered=False)
    assert ar.should_escalate(iteration=9, max_iterations=10)
    assert not ar.should_escalate(iteration=1, max_iterations=10)


def test_escalate_effort_reports_transition() -> None:
    escalated = ar.escalate_effort("standard", reason="stuck")
    assert escalated["level"] == "high"
    assert escalated["escalated"] is True
    assert ar.escalate_effort("max")["escalated"] is False


def test_token_budget_and_indicator() -> None:
    assert ar.token_budget("max") > ar.token_budget("minimal")
    assert ar.effort_indicator("minimal") == "○"
    assert ar.effort_indicator("unknown") == ar.effort_profile("standard")["indicator"]
