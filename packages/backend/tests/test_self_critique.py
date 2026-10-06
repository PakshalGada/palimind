"""Tests for structured self-critique / verification."""

from __future__ import annotations

from palimind.agents import self_critique as sc


def test_detect_task_type() -> None:
    assert sc.detect_task_type("refactor this function and fix the bug") == "code"
    assert sc.detect_task_type("research the literature and cite sources") == "research"
    assert sc.detect_task_type("calculate the average of this csv dataset") == "data"
    assert sc.detect_task_type("write a blog post about coffee") == "writing"
    assert sc.detect_task_type("what is the capital of France") == "general"


def test_build_checklist_nonempty_for_all_types() -> None:
    for task_type in sc.TASK_TYPES:
        checklist = sc.build_checklist(task_type)
        assert checklist and all(isinstance(c, str) for c in checklist)


def test_parse_verification_variants() -> None:
    raw = '{"passed": true, "confidence": 0.9, "checks": {"1": "pass"}, "issues": []}'
    parsed = sc.parse_verification(raw)
    assert parsed is not None and parsed["passed"] is True and parsed["confidence"] == 0.9

    fenced = f"```json\n{raw}\n```"
    assert sc.parse_verification(fenced) is not None

    embedded = f"Here you go: {raw} thanks"
    assert sc.parse_verification(embedded) is not None

    assert sc.parse_verification("not json at all") is None
    assert sc.parse_verification("") is None


def test_parse_verification_clamps_confidence() -> None:
    parsed = sc.parse_verification('{"confidence": 5, "passed": true}')
    assert parsed is not None and parsed["confidence"] == 1.0


def test_needs_retry_and_human_review(monkeypatch) -> None:
    monkeypatch.setattr(sc, "SELF_CRITIQUE_CONFIDENCE_THRESHOLD", 0.6)
    assert sc.needs_retry({"passed": False, "confidence": 0.9}) is True
    assert sc.needs_retry({"passed": True, "confidence": 0.5}) is True
    assert sc.needs_retry({"passed": True, "confidence": 0.8}) is False
    assert sc.needs_human_review({"confidence": 0.2}) is True
    assert sc.needs_human_review({"confidence": 0.9}) is False


def test_heuristic_report_flags_empty_and_errors() -> None:
    empty = sc.heuristic_report("", sc.build_checklist("general"))
    assert empty["confidence"] == 0.0 and empty["passed"] is False
    errored = sc.heuristic_report("[Agent run error] boom", sc.build_checklist("general"))
    assert errored["issues"]
    ok = sc.heuristic_report("A complete and reasonably long answer " * 3, [])
    assert ok["passed"] is True


def test_verify_output_without_model_uses_heuristic() -> None:
    report = sc.verify_output("task", "a decent answer", "", "")
    assert report["source"] == "heuristic"
    assert "checklist" in report and report["task_type"] == "general"


def test_build_retry_prompt_includes_issues() -> None:
    prompt = sc.build_retry_prompt(
        "do the thing",
        "draft",
        {"issues": ["missing X"], "suggestions": ["add Y"]},
    )
    assert "missing X" in prompt and "add Y" in prompt and "do the thing" in prompt


def test_format_report() -> None:
    text = sc.format_report({"passed": False, "confidence": 0.42, "issues": ["bad"]})
    assert "needs attention" in text and "42%" in text
