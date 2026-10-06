"""Tests for multi-model comparison (Phase 3.4)."""

from __future__ import annotations

from palimind.llm.comparative_research import (
    analyze_comparison,
    parse_contradictions,
    split_claims,
)

SHARED = "Quantum computers use qubits that can exist in superposition states."
UNIQUE_A = "IBM plans to scale superconducting processors to thousands of qubits by 2033."
UNIQUE_B = "Google focuses on error-corrected logical qubits using surface codes."


def test_split_claims_filters_short_and_markup() -> None:
    text = "# Heading\n\n" + SHARED + "\n- short\n" + UNIQUE_A
    claims = split_claims(text)
    assert SHARED in claims
    assert UNIQUE_A in claims
    assert all(not c.startswith("#") for c in claims)


def test_analyze_comparison_consensus_and_unique() -> None:
    answers = {
        "model-a": f"{SHARED} {UNIQUE_A}",
        "model-b": f"{SHARED} {UNIQUE_B}",
    }
    result = analyze_comparison(answers)
    assert result["models"] == ["model-a", "model-b"]
    assert len(result["consensus"]) == 1
    assert set(result["consensus"][0]["models"]) == {"model-a", "model-b"}
    assert any(UNIQUE_A[:40] in u for u in result["unique"]["model-a"])
    assert any(UNIQUE_B[:40] in u for u in result["unique"]["model-b"])


def test_analyze_comparison_no_overlap() -> None:
    answers = {"a": UNIQUE_A, "b": UNIQUE_B}
    result = analyze_comparison(answers)
    assert result["consensus"] == []
    assert len(result["unique"]["a"]) == 1
    assert len(result["unique"]["b"]) == 1


def test_parse_contradictions() -> None:
    raw = '[{"claim_a": "X is up", "model_a": "a", "claim_b": "X is down", "model_b": "b", "explanation": "opposite"}]'
    out = parse_contradictions(raw)
    assert len(out) == 1
    assert out[0]["model_a"] == "a"
    assert parse_contradictions("not json") == []
