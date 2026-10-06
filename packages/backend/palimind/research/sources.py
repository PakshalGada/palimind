"""Source quality scoring and collection for deep research (Phase 3.1)."""

from __future__ import annotations

from urllib.parse import urlparse

from palimind.generative.citation import Source

# Domains that are usually low-signal for research.
_LOW_QUALITY = {
    "pinterest.com",
    "quora.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.co.uk",
}

# Curated authority priors (0-1). Longest suffix match wins.
_AUTHORITY: dict[str, float] = {
    "nature.com": 1.0,
    "science.org": 1.0,
    "nejm.org": 1.0,
    "who.int": 0.96,
    "nasa.gov": 0.95,
    "arxiv.org": 0.9,
    "ieee.org": 0.9,
    "acm.org": 0.9,
    "reuters.com": 0.9,
    "apnews.com": 0.9,
    "bbc.com": 0.88,
    "bbc.co.uk": 0.88,
    "nytimes.com": 0.85,
    "wikipedia.org": 0.82,
    "economist.com": 0.88,
    "ft.com": 0.88,
    "bloomberg.com": 0.86,
    "github.com": 0.8,
}


def domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _authority_score(dom: str) -> float | None:
    if not dom:
        return None
    best: tuple[int, float] | None = None
    for suffix, value in _AUTHORITY.items():
        if dom == suffix or dom.endswith("." + suffix):
            if best is None or len(suffix) > best[0]:
                best = (len(suffix), value)
    if best is not None:
        return best[1]
    if dom.endswith(".gov"):
        return 0.95
    if dom.endswith(".edu"):
        return 0.9
    if dom.endswith(".org"):
        return 0.6
    return None


def score_source(source: Source) -> float:
    """Heuristic 0-1 quality score for a source."""
    if source.kind == "document":
        # User's own indexed documents are trusted.
        return 0.8

    dom = domain(source.url)
    if dom in _LOW_QUALITY:
        return 0.15

    score = _authority_score(dom) or 0.5
    # Depth bonuses: fetched content is a stronger signal than a snippet.
    if len(source.content) >= 1500:
        score += 0.06
    elif len(source.content) >= 400:
        score += 0.03
    if source.snippet:
        score += 0.02
    return round(min(1.0, max(0.0, score)), 4)


def score_sources(sources: list[Source]) -> list[Source]:
    for source in sources:
        source.score = score_source(source)
    return sources


def dedupe_sources(sources: list[Source]) -> list[Source]:
    """Deduplicate by URL (web) or file+section (documents), renumbering."""
    seen: set[str] = set()
    out: list[Source] = []
    for source in sources:
        key = source.url.lower() if source.url else f"{source.file}::{source.section}"
        if key in seen:
            continue
        seen.add(key)
        out.append(source)
    for index, source in enumerate(out, start=1):
        source.marker = index
    return out


def sources_from_collected(items: list[dict]) -> list[Source]:
    """Build sources from the raw dicts recorded by the web tools."""
    sources: list[Source] = []
    for item in items:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        sources.append(
            Source(
                marker=0,
                title=(item.get("title") or url).strip(),
                kind="web",
                url=url,
                snippet=(item.get("snippet") or "").strip()[:600],
                content=(item.get("content") or "").strip()[:4000],
            )
        )
    return sources
