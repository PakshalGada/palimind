"""Agent @mention parsing used by the chat router."""

from __future__ import annotations

from palimind.api_server import _AGENT_MENTION_RE, _split_agent_mention


def _mention(text: str):
    return _AGENT_MENTION_RE.search(text)


def test_split_agent_mention_returns_responder_and_clean_input() -> None:
    name, text = _split_agent_mention("please ask @researcher about the report")
    assert name == "researcher"
    assert text == "please ask about the report"


def test_split_agent_mention_handles_no_mention() -> None:
    name, text = _split_agent_mention("write to a@b.com")
    assert name is None
    assert text == "write to a@b.com"


def test_mention_at_start_and_mid_sentence() -> None:
    assert _mention("@researcher find papers").group(2) == "researcher"
    match = _mention("please ask @researcher about the report")
    assert match is not None
    assert match.group(2) == "researcher"
    # Removing the match leaves clean agent input.
    stripped = (
        "please ask @researcher about the report"[: match.start()]
        + "please ask @researcher about the report"[match.end() :]
    ).strip()
    assert stripped == "please ask about the report"


def test_email_addresses_are_not_mentions() -> None:
    assert _mention("write to a@b.com") is None


def test_hyphens_and_underscores_are_part_of_the_name() -> None:
    assert _mention("@data_analyst-2 run").group(2) == "data_analyst-2"
