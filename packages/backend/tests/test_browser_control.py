"""Ownership rules for the shared agent browser."""

from __future__ import annotations

from palimind.agents.tools.browser import tool as browser


def setup_function() -> None:
    browser.release_control()


def teardown_function() -> None:
    browser.release_control()


def test_control_starts_with_the_agent() -> None:
    state = browser.control_state()
    assert state["owner"] == "agent"
    assert browser._ensure_agent_control() is None


def test_human_claim_blocks_mutating_agent_tools() -> None:
    browser.claim_control(agent_id="nova", takeover_id="take-1")
    assert browser.control_state()["owner"] == "human"
    blocked = browser.browser_click(1)
    assert blocked.startswith("Error: the user currently has the browser")
    assert browser.browser_open("https://example.com").startswith("Error: the user")
    # Read-only helpers are still allowed; they do not change the page.
    assert browser._ensure_agent_control() is not None


def test_pending_takeover_pauses_agent_mutations() -> None:
    browser.request_control(agent_id="nova", takeover_id="take-2")
    assert browser.control_state()["owner"] == "pending"
    assert browser.browser_click(1).startswith("Error: waiting for the user")


def test_release_returns_control_to_the_agent() -> None:
    browser.claim_control(agent_id="nova")
    browser.release_control()
    assert browser.control_state()["owner"] == "agent"
    assert browser._ensure_agent_control() is None


def test_unknown_human_action_is_rejected_without_starting_a_browser() -> None:
    result = browser.human_action("not-a-real-action", {})
    assert "unknown browser action" in result["error"]
