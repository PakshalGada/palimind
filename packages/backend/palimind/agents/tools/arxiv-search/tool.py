from __future__ import annotations

import json
import urllib.parse
from typing import Any


def arxiv_search(query: str, max_results: int = 5) -> str:
    """Query the public arXiv API (no key required). Returns a JSON list of
    recent papers matching the query: {title, authors, summary, link, published}."""
    if not query or not str(query).strip():
        return "Error: query is required"

    import xml.etree.ElementTree as ET
    from urllib.request import Request, urlopen

    base = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": int(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{base}?{urllib.parse.urlencode(params)}"

    req = Request(url, headers={"User-Agent": "Palimind/2.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            data = resp.read(2_000_000)
    except Exception as e:
        return f"Error querying arXiv: {e}"

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root_el = ET.fromstring(data)
    except ET.ParseError as e:
        return f"Error parsing arXiv response: {e}"

    papers: list[dict[str, Any]] = []
    for entry in root_el.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
        link = ""
        for l in entry.findall("atom:link", ns):
            if l.attrib.get("rel") == "alternate":
                link = l.attrib.get("href", "")
                break
        authors = [
            (a.findtext("atom:name", "", ns) or "").strip()
            for a in entry.findall("atom:author", ns)
        ]
        summary = (entry.findtext("atom:summary", "", ns) or "").strip().replace("\n", " ")
        published = (entry.findtext("atom:published", "", ns) or "").strip()
        papers.append(
            {
                "title": title[:300],
                "authors": authors[:20],
                "summary": summary[:800],
                "link": link,
                "published": published,
            }
        )
        if len(papers) >= max_results:
            break

    if not papers:
        return f"No arXiv papers matched '{query}'."
    return json.dumps(papers, ensure_ascii=False)


# registry metadata for the main TOOL_REGISTRY
TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Search the public arXiv API for recent papers matching a query. "
        "Returns a JSON list of {title, authors, summary, link, published}."
    ),
    "parameters": {
        "query": "The search query",
        "max_results": "Optional: maximum number of papers (default 5)",
    },
    "tier": 1,
    "requires_approval": False,
}
