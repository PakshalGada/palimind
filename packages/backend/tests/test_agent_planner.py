"""Tests for agent planning mode (generate, approve, execute, rollback)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from palimind.agents import planner as pl


def test_templates_present() -> None:
    ids = {t["id"] for t in pl.list_templates()}
    assert {"code-change", "research-report", "data-analysis", "content-draft"}.issubset(ids)


def test_normalize_steps_drops_unknown_tools_and_bounds() -> None:
    steps = [
        {"title": "read", "tool": "read_file"},
        {"title": "bogus", "tool": "not_a_real_tool"},
        {"title": "note", "tool": ""},
    ]
    normalized = pl.normalize_steps(steps)
    assert [s["tool"] for s in normalized] == ["read_file", "", ""]
    assert [s["id"] for s in normalized] == [1, 2, 3]


def test_parse_plan_json_variants() -> None:
    raw = '[{"title": "a", "tool": "read_file"}]'
    assert len(pl.parse_plan_json(raw)) == 1
    assert len(pl.parse_plan_json(f"```json\n{raw}\n```")) == 1
    assert len(pl.parse_plan_json(f"prefix {raw} suffix")) == 1
    assert pl.parse_plan_json("no json") == []
    assert len(pl.parse_plan_json('{"steps": ' + raw + "}")) == 1


def test_build_from_template_and_persistence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pl, "PLANS_DIR", tmp_path / "plans")
    plan = pl.build_plan_from_template("code-change", "change the parser")
    assert plan["steps"] and plan["status"] == "pending"
    pl.save_plan(plan)
    assert pl.get_plan(plan["id"]) is not None
    assert any(p["id"] == plan["id"] for p in pl.list_plans())

    updated = pl.update_plan(plan["id"], {"status": "approved", "steps": [{"title": "only"}]})
    assert updated is not None and updated["status"] == "approved"
    assert len(updated["steps"]) == 1

    assert pl.delete_plan(plan["id"]) is True
    assert pl.get_plan(plan["id"]) is None


def test_generate_plan_falls_back_without_model(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pl, "PLANS_DIR", tmp_path)
    plan = pl.generate_plan("do a thing", "", "", available_tools=["web_search", "read_file"])
    titles = [s["title"] for s in plan["steps"]]
    assert any("Search" in t for t in titles)
    assert plan["steps"][-1]["title"].startswith("Verify")


def test_execute_plan_runs_tool_steps(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pl, "PLANS_DIR", tmp_path / "plans")
    plan = pl.new_plan("t", [{"title": "a", "tool": "read_file", "args": {"path": "x"}}])
    calls = []

    def fake_tool(name: str, **kwargs):
        calls.append((name, kwargs))
        return "ok"

    result = pl.execute_plan(plan, run_tool=fake_tool, auto_approve=True)
    assert result["status"] == "completed"
    assert calls == [("read_file", {"path": "x"})]
    assert result["steps"][0]["status"] == "done"


def test_execute_plan_rolls_back_on_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pl, "PLANS_DIR", tmp_path / "plans")
    target = tmp_path / "notes.txt"
    target.write_text("original", "utf-8")
    plan = pl.new_plan(
        "t",
        [{"title": "write", "tool": "write_file", "args": {"path": "notes.txt", "content": "new"}}],
    )

    def failing_tool(name: str, **kwargs):
        # Simulate a mutation that then fails.
        (tmp_path / "notes.txt").write_text(str(kwargs.get("content", "")), "utf-8")
        raise RuntimeError("boom")

    result = pl.execute_plan(
        plan, run_tool=failing_tool, working_root=tmp_path, rollback_on_failure=True
    )
    assert result["status"] == "rolled_back"
    assert target.read_text("utf-8") == "original"


def test_execute_plan_skips_unapproved_steps(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pl, "PLANS_DIR", tmp_path)
    plan = pl.new_plan("t", [{"title": "a", "tool": "read_file", "args": {}}])
    calls = []
    result = pl.execute_plan(plan, run_tool=lambda *a, **k: calls.append(1), auto_approve=False)
    assert result["steps"][0]["status"] == "skipped"
    assert calls == []


def test_plan_review_bridge(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pl, "PLANS_DIR", tmp_path)
    plan = pl.new_plan("t", [])
    pl.save_plan(plan)

    async def scenario() -> dict:
        async def resolver() -> None:
            await asyncio.sleep(0.05)
            pl.resolve_plan_review(plan["id"], True, steps=[{"title": "edited"}])

        asyncio.create_task(resolver())
        return await pl.wait_for_plan_review(plan["id"], timeout=2.0)

    decision = asyncio.run(scenario())
    assert decision["approved"] is True
    assert pl.get_plan(plan["id"])["steps"][0]["title"] == "edited"


def test_resolve_plan_review_no_waiter() -> None:
    assert pl.resolve_plan_review("missing", True) is False
