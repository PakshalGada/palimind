"""Prompt library storage and endpoints (reusable templates with variables)."""

from __future__ import annotations

import pytest

from palimind import prompts as prompt_store


@pytest.fixture(autouse=True)
def isolated_prompts(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_store, "PROMPTS_PATH", tmp_path / "prompts.json")
    yield


def test_add_and_list_prompt() -> None:
    result = prompt_store.add_prompt(
        {
            "name": "Paper Summary",
            "command": "paper summary!",
            "template": "Summarise {url} in three bullet points.",
        }
    )
    assert not isinstance(result, str), result
    assert result["command"] == "paper-summary"
    listed = prompt_store.list_prompts()
    assert [p["name"] for p in listed] == ["Paper Summary"]
    assert listed[0]["template"] == "Summarise {url} in three bullet points."


def test_rejects_builtin_and_duplicate_commands() -> None:
    assert "built-in" in prompt_store.add_prompt(
        {"name": "Doc", "command": "doc", "template": "x"}
    )
    first = prompt_store.add_prompt({"name": "A", "command": "alpha", "template": "x"})
    assert not isinstance(first, str)
    assert "already exists" in prompt_store.add_prompt(
        {"name": "B", "command": "alpha", "template": "y"}
    )
    assert "required" in prompt_store.add_prompt({"name": "C", "command": "gamma"})
    # Free text is slugified ("/bad name!" -> "/bad-name"), so only a slug
    # that is still invalid after normalization trips the validator.
    assert "command must" in prompt_store.validate_command("bad name!")
    assert prompt_store.normalize_command("bad name!") == "bad-name"


def test_update_and_delete_round_trip() -> None:
    created = prompt_store.add_prompt(
        {"name": "Weekly", "command": "weekly", "template": "Plan {week}."}
    )
    assert not isinstance(created, str)
    updated = prompt_store.update_prompt(
        created["id"], {"template": "Plan week {week} for {team}.", "name": "Weekly Plan"}
    )
    assert not isinstance(updated, str)
    assert updated["name"] == "Weekly Plan"
    assert updated["template"].endswith("for {team}.")
    # Renaming to a taken command is rejected.
    other = prompt_store.add_prompt({"name": "Other", "command": "other", "template": "x"})
    assert not isinstance(other, str)
    assert "already exists" in prompt_store.update_prompt(
        created["id"], {"command": "other"}
    )
    assert prompt_store.delete_prompt(created["id"])
    assert not prompt_store.delete_prompt(created["id"])
    assert [p["command"] for p in prompt_store.list_prompts()] == ["other"]


def test_endpoint_crud(monkeypatch) -> None:
    import asyncio

    from palimind.api_routers.routers.prompts import (
        create_prompt,
        get_prompts,
        patch_prompt,
        remove_prompt,
    )

    class FakeRequest:
        def __init__(self, data):
            self._data = data

        async def json(self):
            return self._data

    created = asyncio.run(
        create_prompt(FakeRequest({"name": "Churn Q", "command": "churnq", "template": "Ask {q}"}))
    )
    assert "error" not in created
    assert created["prompt"]["command"] == "churnq"
    assert asyncio.run(get_prompts())["prompts"][0]["name"] == "Churn Q"

    patched = asyncio.run(
        patch_prompt(created["prompt"]["id"], FakeRequest({"template": "Ask: {q}"}))
    )
    assert patched["prompt"]["template"] == "Ask: {q}"

    assert asyncio.run(remove_prompt(created["prompt"]["id"]))["status"] == "success"
    assert asyncio.run(get_prompts())["prompts"] == []
