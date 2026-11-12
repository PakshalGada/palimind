"""Research-grade web search pipeline.

The plain ``perform_web_search`` call answers one query and fetches a handful
of pages. That is fine for a quick fact, but it misses the aspects a good
answer needs. This module adds a staged pipeline:

1. understand the query (intent, entities, freshness),
2. decompose it into non-overlapping aspects,
3. expand each aspect into several search queries,
4. search all queries in parallel and fuse the results with reciprocal rank
   fusion, lexical/domain scoring and MMR diversity,
5. fetch the best pages and extract sentence-level evidence per aspect,
6. run one bounded second hop for aspects that are still uncovered,
7. return a :class:`SearchBundle` with evidence, sources and gaps.

Everything degrades gracefully: when the planning model is unavailable the
deterministic fallback still produces a useful multi-aspect search, and a
failed query or page never sinks the whole run.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from palimind.core import web_search as _web
from palimind.generative.citation import Source, parse_web_sources

# ── depth profiles ─────────────────────────────────────────────────────────

DEPTH_PROFILES: dict[str, dict[str, Any]] = {
    "quick": {
        "max_aspects": 2,
        "queries_per_aspect": 2,
        "max_fetch": 5,
        "max_results_per_query": 6,
        "second_hop": False,
    },
    "standard": {
        "max_aspects": 3,
        "queries_per_aspect": 3,
        "max_fetch": 9,
        "max_results_per_query": 6,
        "second_hop": True,
    },
    "deep": {
        "max_aspects": 4,
        "queries_per_aspect": 3,
        "max_fetch": 14,
        "max_results_per_query": 8,
        "second_hop": True,
    },
}

_ACADEMIC_RE = re.compile(
    r"\b(paper|papers|study|studies|research|journal|arxiv|peer[- ]reviewed|"
    r"citation|literature|pubmed|clinical|trial)\b",
    re.IGNORECASE,
)
_NEWS_RE = re.compile(
    r"\b(news|latest|today|yesterday|breaking|recent|update|release|"
    r"announced|earnings|market|stock|price)\b",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"\b(code|api|library|framework|python|javascript|typescript|rust|"
    r"github|implementation|debug|function|algorithm)\b",
    re.IGNORECASE,
)
_MEDICAL_RE = re.compile(
    r"\b(health|medical|disease|drug|symptom|treatment|patient)\b", re.IGNORECASE
)
_FINANCE_RE = re.compile(
    r"\b(sec|filing|10-k|10-q|revenue|investor|company|financial)\b", re.IGNORECASE
)
_COMPARISON_RE = re.compile(
    r"\b(vs\.?|versus|compare|comparison|best|better|difference)\b", re.IGNORECASE
)
_HOWTO_RE = re.compile(
    r"\b(how to|how do|guide|tutorial|steps|setup|install|configure)\b", re.IGNORECASE
)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")

# Query plans are stable for an hour, and identical follow-ups are common.
_PLAN_CACHE_TTL = 3600.0
_PLAN_CACHE_MAX = 64
_plan_cache: dict[str, tuple[float, Any]] = {}
_plan_cache_lock = threading.Lock()


# ── data model ─────────────────────────────────────────────────────────────


@dataclass
class SearchAspect:
    """One sub-question the pipeline tries to answer."""

    id: int
    title: str
    question: str
    queries: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=lambda: ["web"])
    priority: int = 1
    status: str = "pending"  # pending | searching | done | gap
    source_count: int = 0
    evidence_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "question": self.question,
            "queries": list(self.queries),
            "source_types": list(self.source_types),
            "status": self.status,
            "source_count": self.source_count,
            "evidence_count": self.evidence_count,
        }


@dataclass
class Evidence:
    """A sentence-level finding tied to an aspect and a source."""

    aspect_id: int
    claim: str
    quote: str
    url: str
    title: str
    domain: str
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "aspect_id": self.aspect_id,
            "claim": self.claim,
            "quote": self.quote,
            "url": self.url,
            "title": self.title,
            "domain": self.domain,
            "score": self.score,
        }


@dataclass
class SearchBundle:
    """Everything the answer prompt needs from one search run."""

    query: str
    intent: str = "factual"
    entities: list[str] = field(default_factory=list)
    freshness: str = "any"
    aspects: list[SearchAspect] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    queries_run: int = 0
    provider: str = ""
    available: bool = True

    @property
    def has_results(self) -> bool:
        return bool(self.sources)

    def to_prompt(self, max_chars: int | None = None) -> str:
        """Format the bundle for an LLM prompt, including a parseable source block."""
        if not self.sources:
            return ""
        from palimind.settings import SEARCH_PROMPT_CHARS

        limit = max_chars if max_chars is not None else SEARCH_PROMPT_CHARS
        lines: list[str] = [
            f"=== SEARCH BRIEFING FOR: '{self.query}' ===",
            f"Intent: {self.intent} | Freshness: {self.freshness} | "
            f"Sources: {len(self.sources)} | Profile: {len(self.aspects)} aspects",
            "",
        ]

        if self.aspects:
            lines.append("SUB-QUESTIONS:")
            for aspect in self.aspects:
                status = "covered" if aspect.status == "done" else "gap"
                lines.append(f"- [{aspect.id}] {aspect.question} ({status})")
            lines.append("")

        if self.evidence:
            aspect_titles = {aspect.id: aspect.title for aspect in self.aspects}
            lines.append("EVIDENCE (use these facts and cite the source numbers):")
            for item in self.evidence:
                marker = next(
                    (s.marker for s in self.sources if s.url == item.url),
                    None,
                )
                cite = f" [{marker}]" if marker is not None else ""
                aspect = aspect_titles.get(item.aspect_id, "")
                label = f"{aspect} — {item.title}" if aspect else item.title
                lines.append(f"- ({label}) {item.quote}{cite}")
            lines.append("")

        if self.gaps:
            lines.append("UNCOVERED ASPECTS (say so explicitly instead of guessing):")
            for gap in self.gaps:
                lines.append(f"- {gap}")
            lines.append("")

        # Canonical block so existing citation parsing keeps working.
        lines.append(f"=== WEB SEARCH RESULTS FOR: '{self.query}' ===")
        lines.append(f"Provider: {self.provider or 'web'}")
        lines.append(f"Sources: {len(self.sources)}")
        for source in self.sources:
            summary = " ".join(
                (source.snippet or source.content or source.title or source.url).split()
            )[:500]
            lines.append(f"Source [{source.marker}]: {source.title or source.url}")
            lines.append(f"URL: {source.url}")
            lines.append(f"Summary: {summary}")
            lines.append("")
        lines.append("=" * 39)

        text = "\n".join(lines)
        return text[:limit]


# ── JSON helpers ───────────────────────────────────────────────────────────


def _loads_json(text: str) -> Any:
    """Parse a JSON object/array from a model response, tolerating fences."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except (json.JSONDecodeError, TypeError):
                continue
    return None


def _as_str_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text.lower() not in {v.lower() for v in out}:
            out.append(text)
        if len(out) >= limit:
            break
    return out


# ── query understanding ────────────────────────────────────────────────────


def _heuristic_intent(query: str) -> str:
    if _ACADEMIC_RE.search(query):
        return "academic"
    if _NEWS_RE.search(query):
        return "news"
    if _CODE_RE.search(query):
        return "code"
    if _MEDICAL_RE.search(query):
        return "medical"
    if _FINANCE_RE.search(query):
        return "finance"
    if _COMPARISON_RE.search(query):
        return "comparison"
    if _HOWTO_RE.search(query):
        return "howto"
    return "factual"


def _heuristic_freshness(query: str) -> str:
    if re.search(r"\b(today|yesterday|this week|breaking|latest|current)\b", query, re.I):
        return "recent"
    if re.search(r"\b19\d{2}\b", query):
        return "historical"
    return "any"


def _default_source_types(query: str, intent: str) -> list[str]:
    types = ["web"]
    if intent in ("academic", "medical"):
        types.append("academic")
    if intent == "news":
        types.append("news")
    if intent == "code":
        types.append("code")
    if intent == "finance":
        types.append("finance")
    if _MEDICAL_RE.search(query) and "academic" not in types:
        types.append("academic")
    return types


def _history_context(history: list[dict] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for message in history[-4:]:
        role = str(message.get("role") or "user")
        content = " ".join(str(message.get("content") or "").split())
        if content:
            lines.append(f"{role}: {content[:400]}")
    return "\n".join(lines)


def build_search_plan_prompt(
    query: str,
    max_aspects: int,
    *,
    history: list[dict] | None = None,
) -> str:
    history_section = ""
    if context := _history_context(history):
        history_section = f"\nRecent conversation (resolve pronouns and follow-ups):\n{context}\n"

    return f"""You are a search planner for an AI assistant. The user asks:
"{query}"
{history_section}
Design a focused web-research plan that will let another model answer this
question well. Break it into up to {max_aspects} non-overlapping aspects.

Each aspect must be specific, researchable, and together they should cover the
whole question. Prefer 2-4 aspects. Do not add filler aspects.

Return ONLY valid JSON with this shape:
{{
  "intent": "factual|comparison|howto|news|academic|code|medical|finance|opinion",
  "entities": ["named entities, products, people, organisations"],
  "freshness": "any|recent|historical",
  "aspects": [
    {{
      "title": "short aspect name",
      "question": "the specific question this aspect answers",
      "queries": ["2-3 search queries, keyword style, no filler words"],
      "source_types": ["web|news|academic|code|finance|docs"]
    }}
  ]
}}

Return only the raw JSON object."""


def _fallback_aspects(query: str, max_aspects: int, intent: str) -> list[SearchAspect]:
    templates: list[tuple[str, str]] = [
        ("Core answer", f"What is the direct, current answer to: {query}?"),
        ("Key facts & context", f"What key facts, definitions and background explain {query}?"),
    ]
    if intent == "comparison":
        templates.append(
            (
                "Comparison",
                f"How do the main options for {query} compare on cost, quality and trade-offs?",
            )
        )
    elif intent in ("code", "howto"):
        templates.append(
            ("Steps & examples", f"What are the concrete steps, examples and pitfalls for {query}?")
        )
    elif intent in ("news", "finance"):
        templates.append(
            (
                "Recent developments",
                f"What changed recently about {query}, and what do the primary sources say?",
            )
        )
    elif intent == "academic":
        templates.append(
            ("Evidence & studies", f"What peer-reviewed evidence and studies exist about {query}?")
        )
    else:
        templates.append(
            (
                "Evidence & data",
                f"What data, numbers and authoritative sources support or challenge {query}?",
            )
        )

    aspects: list[SearchAspect] = []
    for index, (title, question) in enumerate(templates[: max(1, max_aspects)]):
        # Without an LLM plan we cannot invent better keywords than the user's
        # own query. Reuse it (deduplicated at dispatch) instead of appending
        # filler words that search engines ignore.
        aspects.append(
            SearchAspect(
                id=index + 1,
                title=title,
                question=question,
                queries=[query],
                source_types=_default_source_types(query, intent),
            )
        )
    return aspects


def normalize_plan(
    data: Any,
    query: str,
    max_aspects: int,
) -> tuple[str, list[str], str, list[SearchAspect]]:
    """Normalise an untrusted plan payload into intent, entities, freshness, aspects."""
    if isinstance(data, list):
        data = {"aspects": data}
    if not isinstance(data, dict):
        intent = _heuristic_intent(query)
        return (
            intent,
            [],
            _heuristic_freshness(query),
            _fallback_aspects(query, max_aspects, intent),
        )

    intent = str(data.get("intent") or "").strip().lower()
    if intent not in {
        "factual",
        "comparison",
        "howto",
        "news",
        "academic",
        "code",
        "medical",
        "finance",
        "opinion",
    }:
        intent = _heuristic_intent(query)

    freshness = str(data.get("freshness") or "").strip().lower()
    if freshness not in {"any", "recent", "historical"}:
        freshness = _heuristic_freshness(query)

    entities = _as_str_list(data.get("entities"), 8)

    raw_aspects = data.get("aspects")
    if not isinstance(raw_aspects, list):
        raw_aspects = []

    aspects: list[SearchAspect] = []
    for index, item in enumerate(raw_aspects):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        question = str(item.get("question") or "").strip()
        queries = _as_str_list(item.get("queries"), 6)
        if not question and not title:
            continue
        if not question:
            question = f"What should the answer cover about {title or query}?"
        if not title:
            title = question[:70]
        source_types = _as_str_list(item.get("source_types"), 4) or _default_source_types(
            question, intent
        )
        aspects.append(
            SearchAspect(
                id=len(aspects) + 1,
                title=title[:120],
                question=question[:500],
                queries=queries,
                source_types=source_types,
            )
        )
        if len(aspects) >= max_aspects:
            break

    if not aspects:
        aspects = _fallback_aspects(query, max_aspects, intent)
    return intent, entities, freshness, aspects


# ── query expansion ────────────────────────────────────────────────────────


def _base_keywords(text: str) -> str:
    stripped = text.strip().rstrip("?.!")
    return _web._QUESTION_PREFIX_RE.sub("", stripped).strip() or stripped


def expand_aspect_queries(
    aspect: SearchAspect,
    freshness: str,
    max_queries: int,
) -> list[str]:
    """Deterministic expansion: keyword form, year, source-scoped variants."""
    raw = list(aspect.queries) or [aspect.question or aspect.title]
    out: list[str] = []

    def add(value: str) -> None:
        value = " ".join(value.split()).strip()
        if value and value.lower() not in {v.lower() for v in out}:
            out.append(value)

    for query in raw:
        try:
            variants = _web._build_query_variants(query)
        except Exception:
            variants = [query]
        for variant in variants:
            add(variant)

    base = _base_keywords(aspect.question or aspect.title)
    types = set(aspect.source_types)
    if "academic" in types:
        add(f"site:arxiv.org {base}")
    if "code" in types and "github" not in base.lower():
        add(f"site:github.com {base}")
    if "news" in types and not re.search(r"\b(news|latest|today|recent)\b", base, re.I):
        add(f"{base} news")
    if "finance" in types and "sec.gov" not in base.lower():
        add(f"site:sec.gov {base}")
    if freshness == "recent" and not re.search(r"\b20\d{2}\b", base):
        add(f"{base} {time.gmtime().tm_year}")
    return out[: max(1, max_queries)]


# ── discovery / fusion ─────────────────────────────────────────────────────


@dataclass
class _Candidate:
    source: Source
    rrf: float = 0.0
    relevance: float = 0.0
    quality: float = 0.0
    score: float = 0.0
    queries: list[str] = field(default_factory=list)


async def _search_one(
    query: str,
    max_results: int,
    semaphore: asyncio.Semaphore,
) -> list[tuple[str, int, Source]]:
    async with semaphore:
        try:
            text = await asyncio.to_thread(_web.perform_web_search, query, max_results, False)
        except Exception:
            return []
        sources = parse_web_sources(text)
        return [(query, index, source) for index, source in enumerate(sources)]


def _candidate_quality(source: Source) -> float:
    try:
        from palimind.research.sources import score_source

        return float(score_source(source))
    except Exception:
        return 0.5


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def fuse_candidates(
    entries: list[tuple[str, int, Source]],
    query: str,
    limit: int,
    *,
    mmr: bool = True,
    mmr_lambda: float = 0.35,
    freshness: str = "any",
) -> list[Source]:
    """Reciprocal-rank fusion + lexical/domain scoring + optional MMR."""
    by_url: dict[str, _Candidate] = {}
    terms = _web._query_terms(query)
    for search_query, rank, source in entries:
        url = (source.url or "").strip()
        if not url:
            continue
        key = url.lower()
        candidate = by_url.get(key)
        if candidate is None:
            candidate = _Candidate(source=source)
            by_url[key] = candidate
            candidate.relevance = _web._relevance(
                {
                    "title": source.title,
                    "snippet": source.snippet,
                    "url": source.url,
                },
                terms,
            )
            candidate.quality = _candidate_quality(source)
        candidate.rrf += 1.0 / (60.0 + max(0, rank))
        if search_query not in candidate.queries:
            candidate.queries.append(search_query)

    if not by_url:
        return []

    max_rrf = max(candidate.rrf for candidate in by_url.values()) or 1.0
    candidates = list(by_url.values())
    for candidate in candidates:
        rrf = candidate.rrf / max_rrf
        freshness_bonus = 0.0
        if freshness == "recent":
            text = f"{candidate.source.title} {candidate.source.snippet}".lower()
            if re.search(r"\b(20\d{2}|latest|today|new)\b", text):
                freshness_bonus = 0.05
        candidate.score = (
            0.5 * rrf
            + 0.3 * min(1.0, candidate.relevance)
            + 0.2 * candidate.quality
            + freshness_bonus
        )

    candidates.sort(key=lambda item: item.score, reverse=True)

    if not mmr or limit <= 1:
        selected = candidates[:limit]
    else:
        selected: list[_Candidate] = []
        token_sets = {
            id(candidate): _web._query_terms(f"{candidate.source.title} {candidate.source.snippet}")
            for candidate in candidates
        }
        remaining = list(candidates)
        while remaining and len(selected) < limit:
            best: _Candidate | None = None
            best_value = float("-inf")
            for candidate in remaining:
                similarity = 0.0
                if selected:
                    similarity = max(
                        _jaccard(token_sets[id(candidate)], token_sets[id(other)])
                        for other in selected
                    )
                value = candidate.score - mmr_lambda * similarity
                if value > best_value:
                    best, best_value = candidate, value
            if best is None:
                break
            selected.append(best)
            remaining.remove(best)

    sources: list[Source] = []
    for index, candidate in enumerate(selected, start=1):
        source = candidate.source
        source.marker = index
        source.score = round(candidate.score, 4)
        source.snippet = " ".join((source.snippet or "").split())
        sources.append(source)
    return sources


# ── evidence extraction ────────────────────────────────────────────────────


def _sentences(text: str) -> list[str]:
    collapsed = " ".join((text or "").split())
    if not collapsed:
        return []
    parts = _SENTENCE_RE.split(collapsed)
    out: list[str] = []
    for part in parts:
        sentence = part.strip()
        if len(sentence) < 45 or len(sentence) > 700:
            continue
        # Skip navigation/boilerplate fragments.
        if sentence.lower().startswith(("cookie", "subscribe", "sign in", "menu", "home ")):
            continue
        out.append(sentence)
    return out


def _sentence_score(sentence: str, aspect: SearchAspect, query: str) -> float:
    terms = _web._query_terms(f"{aspect.question} {aspect.title} {query}")
    if not terms:
        return 0.0
    haystack = sentence.lower()
    overlap = sum(1 for term in terms if term in haystack)
    score = overlap / max(1, len(terms))
    if re.search(r"\b\d+(?:\.\d+)?%?\b", sentence):
        score += 0.12
    if re.search(r"\b(19|20)\d{2}\b", sentence):
        score += 0.06
    return score


def extract_evidence(
    aspects: list[SearchAspect],
    sources: list[Source],
    query: str,
    *,
    per_aspect: int,
) -> list[Evidence]:
    evidence: list[Evidence] = []
    seen_quotes: set[str] = set()
    if not aspects:
        aspects = [SearchAspect(id=1, title="Answer", question=query)]

    for aspect in aspects:
        picked: list[Evidence] = []
        for source in sources:
            text = source.content or source.snippet
            if not text:
                continue
            candidates: list[tuple[float, str]] = []
            for sentence in _sentences(text):
                key = re.sub(r"\W+", " ", sentence.lower()).strip()[:120]
                if key in seen_quotes:
                    continue
                score = _sentence_score(sentence, aspect, query)
                if score <= 0:
                    continue
                candidates.append((score, sentence))
            candidates.sort(key=lambda item: item[0], reverse=True)
            # One sentence per source first: this spreads the evidence across
            # independent domains instead of taking everything from one page.
            for score, sentence in candidates[:1]:
                key = re.sub(r"\W+", " ", sentence.lower()).strip()[:120]
                if key in seen_quotes:
                    continue
                seen_quotes.add(key)
                picked.append(
                    Evidence(
                        aspect_id=aspect.id,
                        claim=sentence[:240],
                        quote=sentence,
                        url=source.url,
                        title=source.title or _web._domain(source.url),
                        domain=_web._domain(source.url),
                        score=round(float(score) + source.score, 4),
                    )
                )
                break
            if len(picked) >= per_aspect:
                break

        # Still under the target: take a second sentence from the strongest
        # sources now that every source has contributed once.
        if len(picked) < per_aspect:
            for source in sources:
                text = source.content or source.snippet
                if not text:
                    continue
                candidates = []
                for sentence in _sentences(text):
                    key = re.sub(r"\W+", " ", sentence.lower()).strip()[:120]
                    if key in seen_quotes:
                        continue
                    score = _sentence_score(sentence, aspect, query)
                    if score > 0:
                        candidates.append((score, sentence))
                candidates.sort(key=lambda item: item[0], reverse=True)
                for score, sentence in candidates[:1]:
                    key = re.sub(r"\W+", " ", sentence.lower()).strip()[:120]
                    if key in seen_quotes:
                        continue
                    seen_quotes.add(key)
                    picked.append(
                        Evidence(
                            aspect_id=aspect.id,
                            claim=sentence[:240],
                            quote=sentence,
                            url=source.url,
                            title=source.title or _web._domain(source.url),
                            domain=_web._domain(source.url),
                            score=round(float(score) + source.score, 4),
                        )
                    )
                    break
                if len(picked) >= per_aspect:
                    break

        if not picked:
            # Fall back to the strongest snippet so an aspect with a source is
            # never reported as empty.
            for source in sources:
                snippet = " ".join((source.snippet or "").split())
                if snippet:
                    picked.append(
                        Evidence(
                            aspect_id=aspect.id,
                            claim=snippet[:240],
                            quote=snippet[:400],
                            url=source.url,
                            title=source.title or _web._domain(source.url),
                            domain=_web._domain(source.url),
                            score=source.score,
                        )
                    )
                    break

        picked.sort(key=lambda item: item.score, reverse=True)
        evidence.extend(picked[:per_aspect])
        aspect.evidence_count = min(len(picked), per_aspect)
        aspect.status = "done" if picked else "gap"

    return evidence


# ── pipeline ───────────────────────────────────────────────────────────────


def _profile(depth: str) -> dict[str, Any]:
    return dict(DEPTH_PROFILES.get((depth or "").lower(), DEPTH_PROFILES["standard"]))


async def _emit(
    callback: Callable[[dict[str, Any]], Any] | None,
    payload: dict[str, Any],
) -> None:
    if callback is None:
        return
    try:
        result = callback(payload)
        if inspect.isawaitable(result):
            await result
    except Exception:
        # Streaming must never break the search.
        pass


def _plan_cache_key(query: str, max_aspects: int, history: list[dict] | None) -> str:
    last_user = ""
    for message in reversed(history or []):
        if str(message.get("role") or "") == "user":
            last_user = " ".join(str(message.get("content") or "").split())[:200]
            break
    return f"{query.strip().lower()}::{max_aspects}::{last_user.lower()}"


def _plan_cache_get(key: str) -> Any:
    now = time.monotonic()
    with _plan_cache_lock:
        entry = _plan_cache.get(key)
        if entry is None:
            return None
        timestamp, value = entry
        if now - timestamp > _PLAN_CACHE_TTL:
            del _plan_cache[key]
            return None
        return value


def _plan_cache_put(key: str, value: Any) -> None:
    now = time.monotonic()
    with _plan_cache_lock:
        _plan_cache[key] = (now, value)
        while len(_plan_cache) > _PLAN_CACHE_MAX:
            oldest = min(_plan_cache, key=lambda item: _plan_cache[item][0])
            _plan_cache.pop(oldest, None)


def _plan_with_llm(
    prompt: str,
    llm_fn: Callable[..., dict[str, Any]],
    model: str,
    ollama_url: str,
    *,
    timeout: float,
) -> Any:
    result = llm_fn(
        [{"role": "user", "content": prompt}],
        model,
        ollama_url,
        format="json",
        temperature=0.1,
        num_predict=900,
        read_timeout=timeout,
        num_ctx=8192,
        error_prefix="[search-planner error",
    )
    return _loads_json(str((result or {}).get("content") or ""))


async def run_search_pipeline(
    query: str,
    *,
    ollama_url: str = "",
    model: str = "",
    depth: str = "",
    root: Any = None,
    history: list[dict] | None = None,
    on_event: Callable[[dict[str, Any]], Any] | None = None,
    llm_fn: Callable[..., dict[str, Any]] | None = None,
    source_types: list[str] | None = None,
    max_results: int | None = None,
) -> SearchBundle:
    """Run the decomposed search pipeline and return an evidence bundle.

    ``llm_fn`` is injectable so MoE/deep-research reuse the exact client they
    already resolve and tests never hit the network.
    """
    from palimind import settings

    if not query or not query.strip():
        return SearchBundle(query=query, available=False)

    profile = _profile(depth or settings.SEARCH_DEPTH)
    max_aspects = int(profile["max_aspects"])
    if settings.SEARCH_MAX_ASPECTS > 0:
        max_aspects = min(max_aspects, settings.SEARCH_MAX_ASPECTS)
    max_fetch = int(profile["max_fetch"])
    if max_results is not None:
        profile["max_results_per_query"] = max_results

    bundle = SearchBundle(query=query, provider="")
    started = time.monotonic()

    # ── 1. Understand + decompose ────────────────────────────────────────
    plan_data: Any = None
    plan_started = time.monotonic()
    cache_key = _plan_cache_key(query, max_aspects, history)
    if settings.SEARCH_DECOMPOSE and model and ollama_url:
        plan_data = _plan_cache_get(cache_key)
        if plan_data is None:
            planner = llm_fn
            if planner is None:
                from palimind.llm.mixture_of_expert.llm import llm_chat_safe

                planner = llm_chat_safe
            prompt = build_search_plan_prompt(query, max_aspects, history=history)
            try:
                plan_data = await asyncio.to_thread(
                    _plan_with_llm, prompt, planner, model, ollama_url, timeout=90.0
                )
                if plan_data is not None:
                    _plan_cache_put(cache_key, plan_data)
            except Exception:
                plan_data = None

    intent, entities, freshness, aspects = normalize_plan(plan_data, query, max_aspects)
    if source_types:
        allowed = {item.strip().lower() for item in source_types if item.strip()}
        if allowed:
            for aspect in aspects:
                merged = [item for item in aspect.source_types if item.lower() in allowed]
                aspect.source_types = merged or list(allowed)
    bundle.intent = intent
    bundle.entities = entities
    bundle.freshness = freshness
    bundle.aspects = aspects
    bundle.timings["plan"] = time.monotonic() - plan_started

    await _emit(
        on_event,
        {
            "type": "search_plan",
            "intent": intent,
            "entities": entities,
            "freshness": freshness,
            "aspects": [aspect.to_dict() for aspect in aspects],
        },
    )

    # ── 2. Expand and discover ───────────────────────────────────────────
    discover_started = time.monotonic()
    semaphore = asyncio.Semaphore(max(1, int(settings.SEARCH_QUERY_CONCURRENCY)))
    # Aspects often share the same query (especially the deterministic
    # fallback). Search each unique query once and credit every owning aspect.
    query_owners: dict[str, list[int]] = {}
    for aspect in aspects:
        queries = expand_aspect_queries(aspect, freshness, int(profile["queries_per_aspect"]))
        aspect.queries = queries
        aspect.status = "searching"
        for search_query in queries:
            owners = query_owners.setdefault(search_query, [])
            if aspect.id not in owners:
                owners.append(aspect.id)

    async def run_query(aspect_ids: list[int], search_query: str) -> list[tuple[str, int, Source]]:
        for aspect_id in aspect_ids:
            await _emit(
                on_event,
                {
                    "type": "search_query",
                    "aspect_id": aspect_id,
                    "query": search_query,
                    "status": "running",
                },
            )
        group = await _search_one(
            search_query,
            int(profile["max_results_per_query"]),
            semaphore,
        )
        for aspect_id in aspect_ids:
            await _emit(
                on_event,
                {
                    "type": "search_result",
                    "aspect_id": aspect_id,
                    "query": search_query,
                    "count": len(group),
                    "status": "done",
                },
            )
        return group

    if settings.SEARCH_MAX_QUERIES > 0 and len(query_owners) > settings.SEARCH_MAX_QUERIES:
        keep = list(query_owners)[: settings.SEARCH_MAX_QUERIES]
        if query in query_owners and query not in keep:
            keep[-1] = query
        query_owners = {search_query: query_owners[search_query] for search_query in keep}

    # Keep the exact user query as the final dispatch so the most literal
    # search is also the freshest one in provider order and logs.
    if query in query_owners and len(query_owners) > 1:
        owners = query_owners.pop(query)
        query_owners[query] = owners

    coroutines = [
        run_query(aspect_ids, search_query) for search_query, aspect_ids in query_owners.items()
    ]

    results = await asyncio.gather(*coroutines) if coroutines else []
    entries: list[tuple[str, int, Source]] = []
    for group in results:
        entries.extend(group)
    bundle.queries_run = len(coroutines)
    bundle.timings["discover"] = time.monotonic() - discover_started

    # ── 3. Fuse, diversify and fetch ─────────────────────────────────────
    fuse_started = time.monotonic()
    selected = fuse_candidates(
        entries,
        query,
        max_fetch,
        mmr=settings.SEARCH_MMR,
        mmr_lambda=settings.SEARCH_MMR_LAMBDA,
        freshness=freshness,
    )
    bundle.sources = selected
    bundle.timings["fuse"] = time.monotonic() - fuse_started

    fetch_started = time.monotonic()
    fetch_sem = asyncio.Semaphore(max(1, int(settings.SEARCH_FETCH_CONCURRENCY)))

    async def fetch(source: Source) -> None:
        if source.content or not source.url:
            return
        async with fetch_sem:
            try:
                source.content = await asyncio.to_thread(_web._fetch_page_content, source.url)
            except Exception:
                source.content = ""

    await asyncio.gather(*(fetch(source) for source in selected))
    bundle.timings["fetch"] = time.monotonic() - fetch_started

    for source in selected:
        await _emit(
            on_event,
            {
                "type": "search_source",
                "title": source.title,
                "url": source.url,
                "domain": _web._domain(source.url),
                "score": source.score,
            },
        )

    # ── 4. Evidence per aspect ───────────────────────────────────────────
    extract_started = time.monotonic()
    bundle.evidence = extract_evidence(
        aspects,
        selected,
        query,
        per_aspect=int(settings.SEARCH_EVIDENCE_PER_ASPECT),
    )
    for aspect in aspects:
        aspect.source_count = len(
            {item.url for item in bundle.evidence if item.aspect_id == aspect.id and item.url}
        )
    gaps = [aspect for aspect in aspects if aspect.status != "done"]
    bundle.timings["extract"] = time.monotonic() - extract_started

    # ── 5. Bounded second hop for uncovered aspects ──────────────────────
    if gaps and settings.SEARCH_SECOND_HOP and bool(profile["second_hop"]) and selected:
        hop_started = time.monotonic()
        known_urls = {source.url.lower() for source in selected if source.url}
        hop_entries: list[tuple[str, int, Source]] = []
        hop_queries: list[str] = []
        for aspect in gaps[:2]:
            follow_up = aspect.question or aspect.title
            if freshness == "recent" and not re.search(r"\b20\d{2}\b", follow_up):
                follow_up = f"{follow_up} {time.gmtime().tm_year}"
            hop_queries.append(follow_up)
            await _emit(
                on_event,
                {
                    "type": "search_gap",
                    "aspect_id": aspect.id,
                    "question": aspect.question,
                },
            )
            group = await _search_one(follow_up, int(profile["max_results_per_query"]), semaphore)
            hop_entries.extend(group)
        bundle.queries_run += len(hop_queries)
        new_entries = [
            item for item in hop_entries if (item[2].url or "").lower() not in known_urls
        ]
        if new_entries:
            extra = fuse_candidates(
                new_entries,
                query,
                3,
                mmr=settings.SEARCH_MMR,
                mmr_lambda=settings.SEARCH_MMR_LAMBDA,
                freshness=freshness,
            )
            offset = len(selected)
            for index, source in enumerate(extra, start=offset + 1):
                source.marker = index
            selected.extend(extra)
            await asyncio.gather(*(fetch(source) for source in extra))
            bundle.evidence = extract_evidence(
                aspects,
                selected,
                query,
                per_aspect=int(settings.SEARCH_EVIDENCE_PER_ASPECT),
            )
            for aspect in aspects:
                aspect.source_count = len(
                    {
                        item.url
                        for item in bundle.evidence
                        if item.aspect_id == aspect.id and item.url
                    }
                )
            gaps = [aspect for aspect in aspects if aspect.status != "done"]
        bundle.timings["second_hop"] = time.monotonic() - hop_started

    # ── 6. Finalize ──────────────────────────────────────────────────────
    bundle.gaps = [aspect.question for aspect in gaps]
    bundle.sources = selected
    bundle.available = bool(selected)
    bundle.timings["total"] = time.monotonic() - started

    if not selected:
        for aspect in aspects:
            aspect.status = "gap"
        bundle.gaps = [aspect.question for aspect in aspects]
        await _emit(
            on_event,
            {
                "type": "search_done",
                "sources": 0,
                "queries": bundle.queries_run,
                "gaps": bundle.gaps,
                "timings": bundle.timings,
            },
        )
        return bundle

    for aspect in bundle.aspects:
        if aspect.evidence_count == 0:
            aspect.status = "gap"

    await _emit(
        on_event,
        {
            "type": "search_done",
            "sources": len(bundle.sources),
            "queries": bundle.queries_run,
            "aspects": [aspect.to_dict() for aspect in bundle.aspects],
            "gaps": bundle.gaps,
            "timings": bundle.timings,
        },
    )
    return bundle
