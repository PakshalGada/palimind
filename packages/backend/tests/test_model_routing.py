"""Tests for capability-aware model routing."""

from __future__ import annotations

from palimind.agents.model_routing import infer_needs, route_model


def test_routing_off_keeps_requested_model() -> None:
    route = route_model("do anything", "qwen3.5:4b", routing_mode="off")
    assert route.model == "qwen3.5:4b"
    assert route.unchanged is True


def test_task_requirements_detect_tools_vision_code_and_complexity() -> None:
    needs = infer_needs(
        "Fix the Python bug and compare the results",
        tools=["read_file", "search_replace"],
        attachments=["screenshot.png"],
        complexity="high",
    )
    assert needs.tools
    assert needs.vision
    assert needs.code
    assert needs.reasoning
    assert needs.complexity == "high"


def test_vision_task_routes_to_a_vision_capable_model() -> None:
    route = route_model(
        "describe this screenshot",
        "qwen3.5:4b",
        candidates=["qwen2.5-vl:7b"],
        attachments=["screen.png"],
        tools=["read_file"],
    )
    assert route.model == "qwen2.5-vl:7b"
    assert route.unchanged is False
    assert "capability" in route.reason


def test_hard_task_on_small_local_model_uses_configured_frontier() -> None:
    route = route_model(
        "Investigate and compare these research reports end to end",
        "qwen3.5:4b",
        candidates=["qwen3.5:4b"],
        complexity="high",
        frontier_models=["grok-4"],
        hosted_models={"grok-4"},
        tools=["web_search"],
    )
    assert route.model == "grok-4"
    assert route.provider == "hosted"
    assert route.unchanged is False


def test_reasoning_capable_local_model_is_preferred_before_hosted() -> None:
    route = route_model(
        "Analyse and compare the reports carefully",
        "gemma:2b",
        candidates=["gemma:2b", "deepseek-r1:7b"],
        complexity="high",
        hosted_models={"grok-4"},
        tools=["web_search"],
    )
    assert route.model == "deepseek-r1:7b"
    assert route.provider == "local"


def test_frontier_mode_can_use_hosted_candidates_without_explicit_list() -> None:
    route = route_model(
        "Analyse this deeply",
        "gemma:2b",
        candidates=["gemma:2b"],
        complexity="max",
        hosted_models={"gpt-frontier"},
        routing_mode="frontier",
        tools=["web_search"],
    )
    assert route.model == "gpt-frontier"
    assert route.provider == "hosted"


def test_no_candidate_keeps_requested_model() -> None:
    route = route_model(
        "describe this screenshot",
        "gemma:2b",
        candidates=["gemma:2b"],
        attachments=["screen.png"],
    )
    assert route.model == "gemma:2b"
    assert "no candidate" in route.reason
