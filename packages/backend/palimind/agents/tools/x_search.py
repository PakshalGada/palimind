"""X/Twitter social search with sentiment and trend analysis (Phase 3.2).

Direct X/Twitter scraping is unreliable and often blocked, so this tool uses
DuckDuckGo's index restricted to ``x.com`` / ``twitter.com`` (and a Scrapling
fetch when a post page is reachable). Sentiment and trend extraction are
deterministic and unit-testable; no external NLP dependency is required.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_POSITIVE = {
    "good",
    "great",
    "excellent",
    "amazing",
    "awesome",
    "love",
    "loved",
    "best",
    "bullish",
    "win",
    "winning",
    "growth",
    "growing",
    "strong",
    "positive",
    "success",
    "successful",
    "improve",
    "improved",
    "improving",
    "breakthrough",
    "opportunity",
    "optimistic",
    "up",
    "surge",
    "surged",
    "record",
    "boom",
    "innovation",
    "innovative",
    "promising",
    "confident",
    "gains",
    "gain",
}
_NEGATIVE = {
    "bad",
    "terrible",
    "awful",
    "hate",
    "worst",
    "bearish",
    "loss",
    "losses",
    "crash",
    "crashed",
    "decline",
    "declining",
    "weak",
    "negative",
    "fail",
    "failed",
    "failure",
    "scam",
    "fraud",
    "risk",
    "risky",
    "concern",
    "concerned",
    "problem",
    "problems",
    "crisis",
    "down",
    "drop",
    "dropped",
    "fear",
    "worried",
    "disappointing",
    "disaster",
    "layoffs",
    "lawsuit",
    "investigation",
    "warning",
}
_NEGATIONS = {
    "not",
    "no",
    "never",
    "isn't",
    "aren't",
    "wasn't",
    "don't",
    "doesn't",
    "can't",
    "won't",
}

_HASHTAG_RE = re.compile(r"#(\w{2,30})")
_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")

# Common words that add no trend signal.
_TREND_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "have",
    "has",
    "are",
    "was",
    "were",
    "will",
    "you",
    "your",
    "our",
    "its",
    "their",
    "about",
    "into",
    "just",
    "new",
    "now",
    "get",
    "got",
    "can",
    "all",
    "but",
    "not",
    "what",
    "how",
    "why",
    "when",
    "who",
    "via",
    "amp",
    "https",
    "http",
    "com",
    "www",
    "twitter",
    "x",
    "post",
    "status",
    "more",
    "than",
    "them",
    "they",
    "out",
    "one",
    "two",
}


def analyze_sentiment(text: str) -> dict[str, Any]:
    """Lexicon-based sentiment with simple negation handling."""
    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    pos = neg = 0
    for i, word in enumerate(words):
        negated = i > 0 and words[i - 1] in _NEGATIONS
        if word in _POSITIVE:
            if negated:
                neg += 1
            else:
                pos += 1
        elif word in _NEGATIVE:
            if negated:
                pos += 1
            else:
                neg += 1
    total = pos + neg
    score = (pos - neg) / total if total else 0.0
    if score > 0.15:
        label = "positive"
    elif score < -0.15:
        label = "negative"
    else:
        label = "neutral"
    return {"label": label, "score": round(score, 3), "positive": pos, "negative": neg}


def detect_trends(posts: list[dict], top: int = 8) -> dict[str, Any]:
    """Extract hashtags, cashtags and recurring keywords across posts."""
    hashtags: Counter[str] = Counter()
    cashtags: Counter[str] = Counter()
    keywords: Counter[str] = Counter()
    for post in posts:
        text = post.get("text", "") or ""
        hashtags.update(h.lower() for h in _HASHTAG_RE.findall(text))
        cashtags.update(c.upper() for c in _CASHTAG_RE.findall(text))
        for word in _WORD_RE.findall(text.lower()):
            if word not in _TREND_STOPWORDS:
                keywords[word] += 1
    return {
        "hashtags": hashtags.most_common(top),
        "cashtags": cashtags.most_common(top),
        "keywords": [w for w, _ in keywords.most_common(top)],
    }


def summarize_sentiment(posts: list[dict]) -> dict[str, Any]:
    if not posts:
        return {"label": "neutral", "score": 0.0, "positive": 0, "negative": 0, "distribution": {}}
    scores: list[float] = []
    labels: Counter[str] = Counter()
    for post in posts:
        result = analyze_sentiment(post.get("text", ""))
        scores.append(result["score"])
        labels[result["label"]] += 1
    avg = sum(scores) / len(scores)
    if avg > 0.15:
        label = "positive"
    elif avg < -0.15:
        label = "negative"
    else:
        label = "neutral"
    return {
        "label": label,
        "score": round(avg, 3),
        "positive": labels.get("positive", 0),
        "negative": labels.get("negative", 0),
        "distribution": dict(labels),
    }


def _ddg_site_search(query: str, site: str, max_results: int) -> list[dict]:
    from palimind.core.web_search import _ddg_search

    raw = _ddg_search(f"site:{site} {query}", max_results)
    out: list[dict] = []
    for item in raw:
        url = (item.get("href") or item.get("url") or "").strip()
        if not url:
            continue
        out.append(
            {
                "text": (item.get("title") or "").strip(),
                "snippet": (item.get("body") or item.get("snippet") or "").strip(),
                "url": url,
                "author": _author_from_url(url),
            }
        )
    return out


def _author_from_url(url: str) -> str:
    match = re.search(r"(?:x|twitter)\.com/([^/?#]+)/status", url)
    return match.group(1) if match else ""


def x_search(query: str, max_results: int = 8) -> dict[str, Any]:
    """Search X/Twitter via the web index and return analysed posts."""
    if not query or not query.strip():
        return {"error": "empty query", "posts": [], "sentiment": {}, "trends": {}}

    per_site = max(2, max_results // 2)
    posts = _ddg_site_search(query, "x.com", per_site) + _ddg_site_search(
        query, "twitter.com", per_site
    )

    # Deduplicate by URL.
    seen: set[str] = set()
    unique: list[dict] = []
    for post in posts:
        if post["url"] in seen:
            continue
        seen.add(post["url"])
        # Use the snippet as the post text when available.
        if post.get("snippet"):
            post["text"] = f"{post['text']} — {post['snippet']}".strip(" —")
        post["sentiment"] = analyze_sentiment(post["text"])
        unique.append(post)
    unique = unique[:max_results]

    return {
        "query": query,
        "posts": unique,
        "sentiment": summarize_sentiment(unique),
        "trends": detect_trends(unique),
        "count": len(unique),
    }


def format_x_report(result: dict[str, Any]) -> str:
    """Human/LLM-readable report with numbered citations to original posts."""
    if result.get("error"):
        return f"X search error: {result['error']}"
    posts = result.get("posts", [])
    if not posts:
        return f"No X/Twitter posts found for: {result.get('query', '')}"

    sentiment = result.get("sentiment", {})
    trends = result.get("trends", {})
    lines = [
        f"=== X/TWITTER SIGNAL FOR: '{result.get('query', '')}' ===",
        f"Overall sentiment: {sentiment.get('label')} ({sentiment.get('score')})",
    ]
    hashtags = trends.get("hashtags") or []
    if hashtags:
        lines.append("Trending hashtags: " + ", ".join(f"#{h} ({n})" for h, n in hashtags[:6]))
    cashtags = trends.get("cashtags") or []
    if cashtags:
        lines.append("Tickers: " + ", ".join(f"${c} ({n})" for c, n in cashtags[:6]))
    keywords = trends.get("keywords") or []
    if keywords:
        lines.append("Keywords: " + ", ".join(keywords[:8]))
    lines.append("")
    for idx, post in enumerate(posts, start=1):
        s = post.get("sentiment", {})
        lines.append(
            f"Post [{idx}] (@{post.get('author') or 'unknown'}) — sentiment {s.get('label')}\n"
            f"URL: {post.get('url')}\n"
            f"Text: {post.get('text', '')[:400]}\n"
        )
    lines.append("=" * 40)
    return "\n".join(lines)


def x_search_tool(query: str, max_results: int = 8) -> str:
    """Tool entry point: return the formatted X/Twitter signal report."""
    return format_x_report(x_search(query, max_results=max_results))
