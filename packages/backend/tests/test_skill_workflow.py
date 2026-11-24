"""Skill builder, recommendations, workspace skills and run history."""

from __future__ import annotations

import json
from pathlib import Path


def test_recommendations_rank_relevant_skills() -> None:
    from palimind.agents.skills import recommend_skills

    skills = recommend_skills("make a chart from this csv data")
    ids = [skill["id"] for skill in skills]
    assert "chart-builder" in ids
    assert ids[0] in {"chart-builder", "dashboard-builder", "data-audit"}


def test_workspace_skill_install_and_uninstall(tmp_path: Path) -> None:
    from palimind.agents.skills import get_skill, install_skill, list_skills, uninstall_skill

    workspace = tmp_path / "project"
    skill = {
        "id": "workspace-skill",
        "name": "Workspace skill",
        "description": "A project-local skill",
        "category": "custom",
        "command": "/workspace-skill",
        "tools": [],
        "compose": ["chart-builder"],
        "instructions": "Use the project conventions.",
    }
    install_skill(skill, workspace_root=workspace, overwrite=True)
    listed = {item["id"]: item for item in list_skills(workspace)}
    assert listed["workspace-skill"]["source"] == "workspace"
    assert listed["workspace-skill"]["compose"] == ["chart-builder"]
    assert get_skill("workspace-skill", workspace) is not None
    assert uninstall_skill("workspace-skill", workspace) is True
    assert get_skill("workspace-skill", workspace) is None


def test_skill_builder_drafts_and_installs(monkeypatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server
    import palimind.llm.mixture_of_expert.llm as llm

    draft = {
        "id": "invoice-review",
        "name": "Invoice review",
        "description": "Extract totals and flag mismatches.",
        "category": "finance",
        "command": "/invoice-review",
        "tools": [],
        "compose": [],
        "instructions": "Extract vendor, date, total and tax. Flag totals that do not reconcile.",
    }
    monkeypatch.setattr(llm, "llm_chat_safe", lambda *args, **kwargs: {"content": json.dumps(draft)})
    workspace = tmp_path / "project"
    client = TestClient(server.app)
    response = client.post(
        "/api/agents/skills/build",
        json={
            "prompt": "A skill that reviews invoices",
            "install": True,
            "workspace_root": str(workspace),
            "overwrite": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["skill"]["id"] == "invoice-review"
    assert payload["skill"]["source"] == "workspace"
    listed = client.get(f"/api/agents/skills?workspace_root={workspace}")
    assert "invoice-review" in [item["id"] for item in listed.json()["skills"]]


def test_skill_history_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    record = client.post(
        "/api/agents/skills/history",
        json={"skill_id": "chart-builder", "command": "/chart", "query": "sales.csv"},
    )
    assert record.status_code == 200
    assert record.json()["run"]["skill_id"] == "chart-builder"
    history = client.get("/api/agents/skills/history?limit=10")
    assert history.status_code == 200
    assert history.json()["runs"][0]["command"] == "/chart"
