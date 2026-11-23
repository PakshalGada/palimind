"""Fetch a web page and turn it into a citeable Markdown source.

Security notes
--------------
Every URL *and every redirect hop* is checked by the same SSRF guard used by
web search (``core.web_search._is_safe_url``). Private, loopback, link-local
and metadata addresses are refused. ``robots.txt`` is honoured, response size
is capped, and non-HTML content is rejected in this phase.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 20.0
MAX_REDIRECTS = 6
USER_AGENT = "PaliMind/0.1 (+local knowledge capture)"
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}

_robots_lock = threading.Lock()
_robots_cache: dict[str, tuple[float, RobotFileParser | None]] = {}


class FetchError(RuntimeError):
    """A user-actionable fetch/extract failure."""


@dataclass
class FetchedPage:
    url: str
    canonical_url: str = ""
    title: str = ""
    author: str = ""
    site: str = ""
    published_at: str = ""
    text: str = ""
    html: str = ""
    etag: str = ""
    last_modified: str = ""
    content_hash: str = ""
    status: int = 200
    not_modified: bool = False
    content_type: str = ""
    raw: bytes = b""
    warnings: list[str] = field(default_factory=list)


# ── URL helpers ──────────────────────────────────────────────────────────────


def normalise_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise FetchError("Paste a link to save.")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise FetchError("Only http and https links can be saved.")
    if not parsed.hostname:
        raise FetchError("That link has no hostname.")
    return urlunparse(parsed._replace(fragment=""))


def canonicalise(url: str) -> str:
    """Strip tracking params, fragments and trailing slashes."""
    parsed = urlparse(normalise_url(url))
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            path=path,
            query=urlencode(query),
            fragment="",
        )
    )


def _safe_url(url: str, *, allow_private: bool) -> bool:
    if allow_private:
        return True
    from palimind.core.web_search import _is_safe_url

    return bool(_is_safe_url(url))


def _robots_allowed(url: str, *, allow_private: bool) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    now = time.time()
    with _robots_lock:
        cached = _robots_cache.get(origin)
        if cached is not None and now - cached[0] < 3600:
            parser = cached[1]
        else:
            parser = None
            try:
                import httpx

                robots_url = origin + "/robots.txt"
                if _safe_url(robots_url, allow_private=allow_private):
                    resp = httpx.get(
                        robots_url,
                        timeout=8.0,
                        headers={"User-Agent": USER_AGENT},
                        follow_redirects=False,
                    )
                    if resp.status_code == 200 and len(resp.text) < 500_000:
                        parser = RobotFileParser()
                        parser.parse(resp.text.splitlines())
            except Exception:  # noqa: BLE001 - robots is best-effort
                parser = None
            _robots_cache[origin] = (now, parser)
    if parser is None:
        return True
    try:
        return parser.can_fetch(USER_AGENT, url)
    except Exception:  # noqa: BLE001
        return True


# ── extraction ───────────────────────────────────────────────────────────────


def _meta(soup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def _site_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _extract_html(html: str, url: str) -> dict[str, str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    title = _meta(soup, "og:title", "twitter:title") or (
        soup.title.get_text(strip=True) if soup.title else ""
    )
    author = _meta(soup, "author", "article:author", "twitter:creator")
    site = _meta(soup, "og:site_name") or _site_from_url(url)
    published = _meta(
        soup,
        "article:published_time",
        "datePublished",
        "date",
        "pubdate",
        "og:published_time",
    )

    canonical = ""
    link = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
    if link and link.get("href"):
        canonical = urljoin(url, str(link["href"]))

    for tag in soup(
        ["script", "style", "nav", "header", "footer", "aside", "noscript", "form", "svg"]
    ):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"})
    text = (main or soup).get_text(separator="\n")

    # Prefer a reader extractor when it is installed; it handles boilerplate
    # better than the fallback and is already a common local-first dependency.
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        if extracted and len(extracted) > len(text) * 0.5:
            text = extracted
    except Exception:  # noqa: BLE001 - trafilatura is optional
        pass

    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return {
        "title": title.strip(),
        "author": author.strip(),
        "site": site.strip(),
        "published_at": published.strip(),
        "canonical_url": canonical.strip(),
        "text": text.strip(),
    }


# ── fetch ────────────────────────────────────────────────────────────────────


def fetch_page(
    url: str,
    *,
    etag: str = "",
    last_modified: str = "",
    allow_private: bool = False,
    extra_headers: dict[str, str] | None = None,
    respect_robots: bool = True,
) -> FetchedPage:
    import httpx

    start = normalise_url(url)
    if not _safe_url(start, allow_private=allow_private):
        raise FetchError("That address is not allowed (private or internal network).")
    if respect_robots and not _robots_allowed(start, allow_private=allow_private):
        raise FetchError("robots.txt does not allow saving this page.")

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    if extra_headers:
        headers.update(
            {str(key): str(value) for key, value in extra_headers.items() if str(key)}
        )
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    current = start
    response = None
    with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=False) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            if not _safe_url(current, allow_private=allow_private):
                raise FetchError("A redirect pointed at a private address.")
            try:
                response = client.get(current, headers=headers)
            except httpx.HTTPError as exc:
                raise FetchError(f"Could not fetch the page: {exc}") from exc
            if response.status_code == 304:
                return FetchedPage(url=current, not_modified=True, etag=etag)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location", "")
                if not location:
                    raise FetchError("The page returned an empty redirect.")
                current = urljoin(current, location)
                continue
            break
        else:
            raise FetchError("Too many redirects.")

    if response is None:
        raise FetchError("The page did not respond.")
    if response.status_code == 304:
        return FetchedPage(url=current, not_modified=True, etag=etag)
    if response.status_code >= 400:
        raise FetchError(f"The page returned HTTP {response.status_code}.")
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    raw = response.content
    if len(raw) > MAX_BYTES:
        raise FetchError("The page is too large to save (max 5 MB).")

    if content_type == "application/pdf":
        filename = Path(urlparse(current).path).name or "document.pdf"
        return FetchedPage(
            url=current,
            canonical_url=canonicalise(current),
            title=filename,
            site=_site_from_url(current),
            content_type=content_type,
            raw=raw,
            content_hash=hashlib.sha256(raw).hexdigest(),
            etag=response.headers.get("etag", ""),
            last_modified=response.headers.get("last-modified", ""),
            status=response.status_code,
        )

    if content_type and content_type not in (
        "text/html",
        "application/xhtml+xml",
        "application/xml",  # some blogs serve XHTML as XML
    ):
        raise FetchError(f"Unsupported content type: {content_type}.")

    html = response.text
    extracted = _extract_html(html, current)
    if not extracted["text"]:
        raise FetchError("No readable text was found on that page.")
    canonical = extracted.get("canonical_url") or current
    try:
        canonical = canonicalise(canonical)
    except FetchError:
        canonical = canonicalise(current)
    digest = hashlib.sha256(extracted["text"].encode("utf-8", "replace")).hexdigest()
    return FetchedPage(
        url=current,
        canonical_url=canonical,
        title=extracted["title"] or _site_from_url(current),
        author=extracted["author"],
        site=extracted["site"] or _site_from_url(current),
        published_at=extracted["published_at"],
        text=extracted["text"],
        html=html,
        etag=response.headers.get("etag", ""),
        last_modified=response.headers.get("last-modified", ""),
        content_hash=digest,
        status=response.status_code,
    )


# ── archive fallback ─────────────────────────────────────────────────────────


def fetch_wayback(url: str, *, allow_private: bool = False) -> FetchedPage | None:
    """Fetch the closest Internet Archive snapshot when the live page dies.

    Best-effort: any failure returns ``None`` so the caller can report the
    original error. Only used for pages that failed with a network/HTTP error.
    """
    import httpx

    try:
        if not _safe_url("https://archive.org/", allow_private=allow_private):
            return None
        response = httpx.get(
            "https://archive.org/wayback/available",
            params={"url": url},
            timeout=12.0,
            headers={"User-Agent": USER_AGENT},
        )
        if response.status_code != 200:
            return None
        data = response.json()
        closest = (
            (data.get("archived_snapshots") or {}).get("closest") or {}
        )
        snapshot = str(closest.get("url") or "")
        if not snapshot:
            return None
        snapshot = snapshot.replace("http://", "https://", 1)
        page = fetch_page(snapshot, allow_private=allow_private)
        page.url = url
        page.canonical_url = canonicalise(url)
        page.site = "web.archive.org"
        page.warnings.append("Live page failed; showing an archived copy.")
        return page
    except Exception:  # noqa: BLE001 - fallback must never mask the real error
        logger.debug("Wayback fallback failed for %s", url, exc_info=True)
        return None


_TAG_STOPWORDS = {
    "about",
    "after",
    "also",
    "been",
    "before",
    "being",
    "between",
    "could",
    "does",
    "from",
    "have",
    "into",
    "more",
    "most",
    "other",
    "over",
    "should",
    "such",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "will",
    "with",
    "would",
    "your",
    "you",
}

_TAG_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{3,}")


def derive_tags(text: str, *, site: str = "", limit: int = 4) -> list[str]:
    """Cheap deterministic tags from the page body (no model call)."""
    counts: dict[str, int] = {}
    for match in _TAG_RE.findall((text or "")[:12000]):
        word = match.lower()
        if word in _TAG_STOPWORDS or len(word) > 24:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    tags = [word.replace("-", " ").title() for word, count in ranked if count >= 2][:limit]
    if site:
        label = site.split(".")[0].replace("-", " ").title()
        if label and label.lower() not in {tag.lower() for tag in tags}:
            tags.insert(0, label)
    return tags[:limit]


def fallback_eligible(error: str) -> bool:
    """Archive fallback is for dead links, not policy/format refusals."""
    text = (error or "").lower()
    if any(token in text for token in ("robots", "private", "not allowed", "unsupported")):
        return False
    return any(
        token in text
        for token in ("http", "could not fetch", "redirect", "respond", "timed out")
    )


# ── Markdown rendering ───────────────────────────────────────────────────────

def slug_for(title: str, url: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    if not base:
        base = re.sub(r"[^a-z0-9]+", "-", urlparse(url).path.lower()).strip("-")
    return (base or "page")[:60]


def render_markdown(page: FetchedPage, *, source_id: str, saved_at: float | None = None) -> str:
    saved = datetime.fromtimestamp(saved_at or time.time(), tz=timezone.utc).isoformat()
    front = {
        "source_id": source_id,
        "source_type": "web",
        "url": page.url,
        "canonical_url": page.canonical_url,
        "title": page.title,
        "author": page.author,
        "site": page.site,
        "published_at": page.published_at,
        "fetched_at": saved,
        "content_hash": page.content_hash,
    }
    lines = ["---"]
    for key, value in front.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.extend(["---", "", f"# {page.title or page.site or 'Saved page'}", ""])
    if page.url:
        byline = f"> Source: [{page.site or page.url}]({page.url})"
        if page.author:
            byline += f" · {page.author}"
        if page.published_at:
            byline += f" · {page.published_at}"
        lines.extend([byline, ""])
    lines.append(page.text)
    lines.append("")
    return "\n".join(lines)


def strip_front_matter(text: str) -> str:
    """Remove a leading YAML front-matter block from saved Markdown."""
    if not text.startswith("---"):
        return text
    match = re.match(r"^---\s*\n.*?\n---\s*\n?", text, flags=re.DOTALL)
    if not match:
        return text
    return text[match.end() :]


def summarise_change(old_text: str, new_text: str) -> str:
    """Human summary of what changed between two saved copies."""
    import difflib

    old_lines = [line.strip() for line in old_text.splitlines() if line.strip()]
    new_lines = [line.strip() for line in new_text.splitlines() if line.strip()]
    if not old_lines:
        return "First snapshot"
    added = removed = 0
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    if not added and not removed:
        return ""
    parts = []
    if added:
        parts.append(f"{added} line{'s' if added != 1 else ''} added")
    if removed:
        parts.append(f"{removed} line{'s' if removed != 1 else ''} removed")
    return ", ".join(parts)


def write_source_file(
    root: Path,
    page: FetchedPage,
    *,
    source_id: str,
    source_dir: str = "sources",
    existing_path: str = "",
) -> tuple[str, str | None]:
    """Write the Markdown source (and an HTML snapshot); return (rel, snapshot)."""
    root = Path(root)
    rel = existing_path.strip()
    if not rel:
        name = f"{slug_for(page.title, page.url)}-{source_id[:8]}.md"
        rel = str(Path(source_dir) / "web" / name)
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_markdown(page, source_id=source_id), encoding="utf-8"
    )

    snapshot_rel = None
    if page.html:
        snapshot = root / ".palimind" / "raw" / "web" / f"{source_id}.html"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(page.html, encoding="utf-8")
        snapshot_rel = str(snapshot.relative_to(root))
    return rel, snapshot_rel
