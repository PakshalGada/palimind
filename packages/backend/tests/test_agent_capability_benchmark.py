"""CI wrapper for the repeatable agent capability benchmark."""

from __future__ import annotations

from palimind.agents.capability_benchmark import run_benchmark


def test_scripted_capability_benchmark_meets_target() -> None:
    report = run_benchmark("scripted")
    payload = report.to_dict()
    assert payload["total"] >= 5
    assert payload["score"] >= payload["target"], payload
    failed = [item for item in payload["scenarios"] if not item["passed"]]
    assert not failed, failed


def test_benchmark_report_is_json_serializable() -> None:
    import json

    report = run_benchmark("scripted")
    encoded = json.dumps(report.to_dict())
    assert '"research_citations"' in encoded
    assert '"ui_followup_flow"' in encoded


def test_head_to_head_comparison_payload(monkeypatch) -> None:
    from palimind.agents import capability_benchmark as cb

    def fake_run(mode, model, url, only=None):
        passed = model != "baseline-model"
        result = cb.ScenarioResult(
            id="research_citations",
            category="research",
            name="research",
            passed=passed,
            checks={"ok": passed},
        )
        return cb.BenchmarkReport(
            mode=mode,
            model=model,
            elapsed_s=0.01,
            target=0.8,
            results=[result],
        )

    monkeypatch.setattr(cb, "run_benchmark", fake_run)
    payload = cb.run_comparison("local-model", "http://local", "baseline-model", "http://baseline")
    assert payload["kind"] == "head_to_head"
    assert payload["local_score"] == 1.0
    assert payload["baseline_score"] == 0.0
    assert payload["winner"] == "local"
    assert payload["scenarios"][0]["winner"] == "local"
