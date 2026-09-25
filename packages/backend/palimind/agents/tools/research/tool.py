"""Research / knowledge tools backed by public, keyless APIs.

Each tool returns compact JSON (or text for ``pdf_read``) so the agent can
cite sources. All are tier 1 (read-only, no approval) and degrade gracefully:
network/parse failures come back as an ``Error:`` string rather than raising.

Optional keys (see settings) improve rate limits: ``PALIMIND_GITHUB_TOKEN``,
``PALIMIND_SEMANTIC_SCHOLAR_API_KEY``.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

_UA = "PaliMind/0.1 (local research agent; +https://palimind.local)"
_TIMEOUT = 20


def _get_json(
    url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> Any:
    import httpx

    merged = {"User-Agent": _UA}
    if headers:
        merged.update(headers)
    resp = httpx.get(url, params=params, headers=merged, timeout=_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def _err(source: str, exc: Exception) -> str:
    return f"Error: {source} request failed: {exc}"


def _n(limit: int, default: int = 5, cap: int = 25) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, cap))


# ── academic ──────────────────────────────────────────────────────────────


def semantic_scholar_search(query: str, limit: int = 5) -> str:
    """Search Semantic Scholar for papers (title, authors, year, citations, abstract)."""
    if not query or not str(query).strip():
        return "Error: query is required"
    from palimind.settings import SEMANTIC_SCHOLAR_API_KEY

    headers = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else None
    try:
        data = _get_json(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": str(query),
                "limit": _n(limit),
                "fields": "title,abstract,year,authors,url,citationCount,venue",
            },
            headers=headers,
        )
    except Exception as e:  # noqa: BLE001
        return _err("Semantic Scholar", e)
    papers = data.get("data", [])
    if not papers:
        return f"No papers found for '{query}'."
    out = []
    for p in papers:
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:6])
        out.append(
            {
                "title": p.get("title"),
                "year": p.get("year"),
                "authors": authors,
                "venue": p.get("venue"),
                "citations": p.get("citationCount"),
                "url": p.get("url"),
                "abstract": (p.get("abstract") or "")[:600],
            }
        )
    return json.dumps(out, ensure_ascii=False)


def openalex_search(query: str, limit: int = 5) -> str:
    """Search OpenAlex for scholarly works."""
    if not query or not str(query).strip():
        return "Error: query is required"
    try:
        data = _get_json(
            "https://api.openalex.org/works",
            params={"search": str(query), "per-page": _n(limit)},
        )
    except Exception as e:  # noqa: BLE001
        return _err("OpenAlex", e)
    out = []
    for w in data.get("results", []):
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (w.get("authorships") or [])[:6]
        ]
        loc = w.get("primary_location") or {}
        out.append(
            {
                "title": w.get("title"),
                "year": w.get("publication_year"),
                "authors": ", ".join(a for a in authors if a),
                "cited_by": w.get("cited_by_count"),
                "doi": w.get("doi"),
                "url": loc.get("landing_page_url") or w.get("doi"),
            }
        )
    return json.dumps(out, ensure_ascii=False) if out else f"No works found for '{query}'."


def crossref_search(query: str, limit: int = 5) -> str:
    """Search Crossref for published works (DOI metadata)."""
    if not query or not str(query).strip():
        return "Error: query is required"
    try:
        data = _get_json(
            "https://api.crossref.org/works",
            params={"query": str(query), "rows": _n(limit)},
        )
    except Exception as e:  # noqa: BLE001
        return _err("Crossref", e)
    items = (data.get("message") or {}).get("items", [])
    out = []
    for item in items:
        authors = ", ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in (item.get("author") or [])[:6]
        )
        parts = (item.get("issued") or {}).get("date-parts") or [[None]]
        out.append(
            {
                "title": (item.get("title") or ["(untitled)"])[0],
                "year": parts[0][0] if parts and parts[0] else None,
                "authors": authors,
                "container": (item.get("container-title") or [None])[0],
                "doi": item.get("DOI"),
                "url": item.get("URL"),
            }
        )
    return json.dumps(out, ensure_ascii=False) if out else f"No works found for '{query}'."


def pubmed_search(query: str, limit: int = 5) -> str:
    """Search PubMed (NCBI E-utilities) for biomedical literature."""
    if not query or not str(query).strip():
        return "Error: query is required"
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    try:
        search = _get_json(
            f"{base}/esearch.fcgi",
            params={"db": "pubmed", "term": str(query), "retmax": _n(limit), "retmode": "json"},
        )
        ids = (search.get("esearchresult") or {}).get("idlist", [])
        if not ids:
            return f"No PubMed results for '{query}'."
        summary = _get_json(
            f"{base}/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        )
    except Exception as e:  # noqa: BLE001
        return _err("PubMed", e)
    result = summary.get("result") or {}
    out = []
    for pid in result.get("uids", []):
        rec = result.get(pid, {})
        authors = ", ".join(a.get("name", "") for a in (rec.get("authors") or [])[:6])
        out.append(
            {
                "pmid": pid,
                "title": rec.get("title"),
                "journal": rec.get("fulljournalname") or rec.get("source"),
                "date": rec.get("pubdate"),
                "authors": authors,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            }
        )
    return json.dumps(out, ensure_ascii=False)


# ── reference & news ──────────────────────────────────────────────────────


def wikipedia_search(query: str, limit: int = 5) -> str:
    """Search Wikipedia and return matching article titles and snippets."""
    if not query or not str(query).strip():
        return "Error: query is required"
    try:
        data = _get_json(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": str(query),
                "srlimit": _n(limit),
                "format": "json",
            },
        )
    except Exception as e:  # noqa: BLE001
        return _err("Wikipedia", e)
    hits = (data.get("query") or {}).get("search", [])
    out = []
    for h in hits:
        title = h.get("title", "")
        snippet = re.sub(r"<[^>]+>", "", str(h.get("snippet", ""))).strip()
        out.append(
            {
                "title": title,
                "snippet": snippet,
                "url": f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
            }
        )
    return json.dumps(out, ensure_ascii=False) if out else f"No Wikipedia articles for '{query}'."


def wikipedia_page(title: str, max_chars: int = 4000) -> str:
    """Return the plain-text summary of a Wikipedia article."""
    if not title or not str(title).strip():
        return "Error: title is required"
    try:
        data = _get_json(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(str(title).replace(' ', '_'))}"
        )
    except Exception as e:  # noqa: BLE001
        return _err("Wikipedia", e)
    extract = data.get("extract") or ""
    if not extract:
        return f"No summary found for '{title}'."
    return f"{data.get('title', title)}\n\n{extract[: int(max_chars)]}"


def news_search(query: str, limit: int = 10) -> str:
    """Search recent global news coverage via GDELT."""
    if not query or not str(query).strip():
        return "Error: query is required"
    try:
        data = _get_json(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": str(query),
                "mode": "artlist",
                "format": "json",
                "maxrecords": _n(limit, default=10, cap=50),
                "sort": "datedesc",
            },
        )
    except Exception as e:  # noqa: BLE001
        return _err("GDELT", e)
    out = [
        {
            "title": a.get("title"),
            "url": a.get("url"),
            "domain": a.get("domain"),
            "seen": a.get("seendate"),
            "language": a.get("language"),
        }
        for a in data.get("articles", [])
    ]
    return json.dumps(out, ensure_ascii=False) if out else f"No news found for '{query}'."


def hn_search(query: str, limit: int = 10) -> str:
    """Search Hacker News stories via the Algolia API."""
    if not query or not str(query).strip():
        return "Error: query is required"
    try:
        data = _get_json(
            "https://hn.algolia.com/api/v1/search",
            params={
                "query": str(query),
                "tags": "story",
                "hitsPerPage": _n(limit, default=10, cap=50),
            },
        )
    except Exception as e:  # noqa: BLE001
        return _err("Hacker News", e)
    out = []
    for h in data.get("hits", []):
        oid = h.get("objectID")
        out.append(
            {
                "title": h.get("title") or h.get("story_title"),
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                "points": h.get("points"),
                "comments": h.get("num_comments"),
                "created": h.get("created_at"),
            }
        )
    return json.dumps(out, ensure_ascii=False) if out else f"No Hacker News stories for '{query}'."


# ── developer & data ──────────────────────────────────────────────────────


def github_search(query: str, limit: int = 5) -> str:
    """Search GitHub repositories by keyword."""
    if not query or not str(query).strip():
        return "Error: query is required"
    from palimind.settings import GITHUB_TOKEN

    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        data = _get_json(
            "https://api.github.com/search/repositories",
            params={"q": str(query), "per_page": _n(limit), "sort": "stars"},
            headers=headers,
        )
    except Exception as e:  # noqa: BLE001
        return _err("GitHub", e)
    out = [
        {
            "name": r.get("full_name"),
            "description": (r.get("description") or "")[:300],
            "stars": r.get("stargazers_count"),
            "language": r.get("language"),
            "url": r.get("html_url"),
        }
        for r in data.get("items", [])
    ]
    return json.dumps(out, ensure_ascii=False) if out else f"No repositories found for '{query}'."


def stackexchange_search(query: str, limit: int = 5) -> str:
    """Search Stack Overflow via the Stack Exchange API."""
    if not query or not str(query).strip():
        return "Error: query is required"
    try:
        data = _get_json(
            "https://api.stackexchange.com/2.3/search/advanced",
            params={
                "order": "desc",
                "sort": "relevance",
                "q": str(query),
                "site": "stackoverflow",
                "pagesize": _n(limit),
            },
        )
    except Exception as e:  # noqa: BLE001
        return _err("Stack Exchange", e)
    out = [
        {
            "title": i.get("title"),
            "url": i.get("link"),
            "score": i.get("score"),
            "answers": i.get("answer_count"),
            "answered": i.get("is_answered"),
            "tags": i.get("tags"),
        }
        for i in data.get("items", [])
    ]
    return (
        json.dumps(out, ensure_ascii=False) if out else f"No Stack Overflow results for '{query}'."
    )


def open_meteo(latitude: float, longitude: float, days: int = 3) -> str:
    """Get a short weather forecast for a coordinate (Open-Meteo, no key)."""
    try:
        lat = float(latitude)
        lon = float(longitude)
        forecast_days = max(1, min(int(days), 16))
    except (TypeError, ValueError):
        return "Error: latitude, longitude and days must be numbers"
    try:
        data = _get_json(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "forecast_days": forecast_days,
                "timezone": "auto",
            },
        )
    except Exception as e:  # noqa: BLE001
        return _err("Open-Meteo", e)
    return json.dumps(
        {
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "timezone": data.get("timezone"),
            "daily": data.get("daily"),
        },
        ensure_ascii=False,
    )


def sec_edgar_search(query: str, limit: int = 5) -> str:
    """Full-text search of SEC EDGAR filings."""
    if not query or not str(query).strip():
        return "Error: query is required"
    from palimind.settings import SEC_CONTACT

    try:
        data = _get_json(
            "https://efts.sec.gov/LATEST/search-index",
            params={"q": str(query)},
            headers={"User-Agent": f"PaliMind {SEC_CONTACT}"},
        )
    except Exception as e:  # noqa: BLE001
        return _err("SEC EDGAR", e)
    hits = (data.get("hits") or {}).get("hits", [])[: _n(limit, default=5, cap=25)]
    out = []
    for h in hits:
        src = h.get("_source") or {}
        out.append(
            {
                "form": src.get("root_form") or src.get("file_type"),
                "date": src.get("file_date"),
                "companies": src.get("display_names") or src.get("ciks"),
                "accession": h.get("_id"),
            }
        )
    return json.dumps(out, ensure_ascii=False) if out else f"No SEC filings found for '{query}'."


# ── local files ───────────────────────────────────────────────────────────


def pdf_read(path: str, max_chars: int = 20000) -> str:
    """Extract text from a PDF in the workspace (sandboxed to the field)."""
    from palimind.llm.mixture_of_expert.tools import _resolve_in_workspace

    resolved = _resolve_in_workspace(str(path))
    if resolved is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    if not resolved.exists() or not resolved.is_file():
        return f"Error: file not found at {path}"
    try:
        import pymupdf
    except ImportError:
        return "Error: PyMuPDF is not installed."
    try:
        doc = pymupdf.open(resolved)
        try:
            text = "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    except Exception as e:  # noqa: BLE001
        return f"Error: could not read PDF: {e}"
    return text[: int(max_chars)] or "(no extractable text)"


TOOLS: dict[str, dict[str, Any]] = {
    "semantic_scholar_search": {
        "fn": semantic_scholar_search,
        "description": "Search Semantic Scholar for academic papers (title, authors, year, citations, abstract).",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 5)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "openalex_search": {
        "fn": openalex_search,
        "description": "Search OpenAlex for scholarly works.",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 5)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "crossref_search": {
        "fn": crossref_search,
        "description": "Search Crossref for published works and DOI metadata.",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 5)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "pubmed_search": {
        "fn": pubmed_search,
        "description": "Search PubMed for biomedical literature.",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 5)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "wikipedia_search": {
        "fn": wikipedia_search,
        "description": "Search Wikipedia for articles.",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 5)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "wikipedia_page": {
        "fn": wikipedia_page,
        "description": "Get the plain-text summary of a Wikipedia article by title.",
        "parameters": {
            "title": "Article title",
            "max_chars": "Optional: max characters (default 4000)",
        },
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "news_search": {
        "fn": news_search,
        "description": "Search recent global news coverage via GDELT.",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 10)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "hn_search": {
        "fn": hn_search,
        "description": "Search Hacker News stories.",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 10)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "github_search": {
        "fn": github_search,
        "description": "Search GitHub repositories by keyword.",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 5)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "stackexchange_search": {
        "fn": stackexchange_search,
        "description": "Search Stack Overflow questions.",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 5)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "open_meteo": {
        "fn": open_meteo,
        "description": "Get a short weather forecast for a latitude/longitude.",
        "parameters": {
            "latitude": "Latitude",
            "longitude": "Longitude",
            "days": "Optional: forecast days (default 3, max 16)",
        },
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "sec_edgar_search": {
        "fn": sec_edgar_search,
        "description": "Full-text search of SEC EDGAR filings.",
        "parameters": {"query": "Search query", "limit": "Optional: max results (default 5)"},
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 30,
    },
    "pdf_read": {
        "fn": pdf_read,
        "description": "Extract text from a PDF inside the workspace.",
        "parameters": {
            "path": "Workspace-relative or absolute path to the PDF",
            "max_chars": "Optional: max characters (default 20000)",
        },
        "tier": 1,
        "requires_approval": False,
        "timeout_s": 45,
    },
}
