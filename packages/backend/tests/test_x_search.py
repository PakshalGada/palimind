"""Tests for X/Twitter social search analysis (Phase 3.2)."""

from __future__ import annotations

from palimind.agents.tools.x_search import (
    analyze_sentiment,
    detect_trends,
    format_x_report,
    summarize_sentiment,
)


def test_analyze_sentiment() -> None:
    assert (
        analyze_sentiment("This is great and excellent news, a real breakthrough")["label"]
        == "positive"
    )
    assert (
        analyze_sentiment("Terrible crash and a total failure, very risky")["label"] == "negative"
    )
    assert analyze_sentiment("The meeting is scheduled for Tuesday afternoon")["label"] == "neutral"


def test_analyze_sentiment_negation() -> None:
    result = analyze_sentiment("This is not good at all")
    assert result["negative"] >= 1


def test_detect_trends() -> None:
    posts = [
        {"text": "Bullish on $NVDA #AI #semiconductors"},
        {"text": "More #AI momentum and $NVDA gains"},
    ]
    trends = detect_trends(posts)
    assert ("ai", 2) in trends["hashtags"]
    assert ("NVDA", 2) in trends["cashtags"]
    assert "bullish" in trends["keywords"]


def test_summarize_sentiment() -> None:
    posts = [
        {"text": "great growth and strong gains"},
        {"text": "excellent breakthrough"},
    ]
    summary = summarize_sentiment(posts)
    assert summary["label"] == "positive"
    assert summary["positive"] == 2


def test_format_x_report_citations() -> None:
    result = {
        "query": "AI",
        "count": 1,
        "sentiment": {"label": "positive", "score": 0.5},
        "trends": {"hashtags": [("ai", 1)], "cashtags": [], "keywords": ["momentum"]},
        "posts": [
            {
                "author": "trader",
                "url": "https://x.com/trader/status/1",
                "text": "Bullish on AI",
                "sentiment": {"label": "positive"},
            }
        ],
    }
    report = format_x_report(result)
    assert "Post [1]" in report
    assert "https://x.com/trader/status/1" in report
    assert "@trader" in report


def test_posts_from_x_api_maps_users_and_metrics() -> None:
    from palimind.agents.tools.x_search import posts_from_x_api

    posts = posts_from_x_api(
        {
            "data": [
                {
                    "id": "123",
                    "author_id": "u1",
                    "text": "Bullish on $NVDA",
                    "created_at": "2026-11-06T10:00:00Z",
                    "public_metrics": {"like_count": 4},
                }
            ],
            "includes": {"users": [{"id": "u1", "username": "trader"}]},
        }
    )
    assert posts[0]["url"] == "https://x.com/trader/status/123"
    assert posts[0]["author"] == "trader"
    assert posts[0]["metrics"]["like_count"] == 4


def test_x_search_uses_api_before_web_index(monkeypatch) -> None:
    from palimind.agents.tools import x_search as xs

    monkeypatch.setattr(
        xs,
        "_x_api_search",
        lambda _query, _n: [
            {
                "text": "great growth",
                "snippet": "",
                "url": "https://x.com/trader/status/1",
                "author": "trader",
            }
        ],
    )
    result = xs.x_search("AI", max_results=2)
    assert result["source"] == "x_api"
    assert result["count"] == 1
    assert "Source: x_api" in xs.format_x_report(result)


def test_x_search_falls_back_to_web_index(monkeypatch) -> None:
    from palimind.agents.tools import x_search as xs

    monkeypatch.setattr(xs, "_x_api_search", lambda _query, _n: [])
    monkeypatch.setattr(
        xs,
        "_ddg_site_search",
        lambda _query, _site, _n: [
            {
                "text": "indexed post",
                "snippet": "snippet",
                "url": "https://x.com/user/status/2",
                "author": "user",
            }
        ],
    )
    result = xs.x_search("AI", max_results=2)
    assert result["source"] == "web_index"
    assert result["count"] >= 1
