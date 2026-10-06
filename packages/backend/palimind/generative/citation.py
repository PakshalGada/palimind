"""Citation engine (Phase 3.3).

Post-processes generated answers to attach inline ``[n]`` markers that map
claims back to their sources, builds a bibliography, and scores how well the
answer is grounded. Designed to be deterministic and dependency-free so it can
run offline and be unit-tested without an LLM.

The module is intentionally source-agnostic: callers build :class:`Source`
objects from web-search output, RAG text refs, or agent tool results.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# ── data model ─────────────────────────────────────────────────────────────


@dataclass
class Source:
    """A single citable source with a stable 1-based marker."""

    marker: int
    title: str
    kind: str = "web"  # "web" | "document" | "media" | "agent"
    url: str = ""
    file: str = ""
    section: str = ""
    snippet: str = ""
    content: str = ""
    score: float = 0.0

    @property
    def id(self) -> str:
        return f"s{self.marker}"

    def search_text(self) -> str:
        parts = [self.title, self.snippet, self.section, self.content]
        return " ".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Citation:
    """A claim-level link between a sentence and a source."""

    marker: int
    source_id: str
    sentence: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CitationResult:
    text: str
    citations: list[Citation] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    bibliography: str = ""
    accuracy: float = 0.0
    coverage: float = 0.0
    mean_score: float = 0.0
    cited_markers: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "citations": [c.to_dict() for c in self.citations],
            "sources": [s.to_dict() for s in self.sources],
            "bibliography": self.bibliography,
            "accuracy": round(self.accuracy, 4),
            "coverage": round(self.coverage, 4),
            "mean_score": round(self.mean_score, 4),
            "cited_markers": self.cited_markers,
        }


# ── tokenisation / scoring ─────────────────────────────────────────────────

_STOPWORDS = set(
    "the and for are but not you all any can her was one our out day get has "
    "him his how its may new now old see two way who boy did use that with this "
    "from they have were been their which would there about into more other some "
    "these such than then them also over when what your will each most many much "
    "very just because while where after before between being under during "
    "through should could does doing here only same both those upon within without".split()
)

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}")
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]+|[^.!?\n]+$")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def tokenize(text: str) -> set[str]:
    """Lowercased content words (len >= 3, stopwords removed)."""
    return {w.lower() for w in _WORD_RE.findall(text) if w.lower() not in _STOPWORDS}


def _score(sentence_tokens: set[str], source_tokens: set[str]) -> float:
    if not sentence_tokens or not source_tokens:
        return 0.0
    overlap = len(sentence_tokens & source_tokens)
    if overlap == 0:
        return 0.0
    # Cosine-like normalisation; sqrt dampens the length penalty for long pages.
    return overlap / ((len(sentence_tokens) ** 0.5) * (len(source_tokens) ** 0.5))


def _mask(text: str, pattern: re.Pattern[str]) -> str:
    """Replace matches with spaces of equal length (keeps offsets stable)."""
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def _is_prose(sentence: str) -> bool:
    stripped = sentence.strip()
    if not stripped or len(stripped) < 25:
        return False
    if _HEADING_RE.match(stripped) or _LIST_RE.match(stripped):
        return False
    if stripped.startswith(("|", ">", "---", "===")):
        return False
    return len(tokenize(stripped)) >= 4


# ── source construction ────────────────────────────────────────────────────

_WEB_HEADER_RE = re.compile(r"=== WEB SEARCH RESULTS FOR:.*?===")
_WEB_SOURCE_RE = re.compile(
    r"Source \[(\d+)\]:\s*(.*?)\nURL:\s*(\S+)\nSummary:\s*(.*?)(?:\nPage Content:\s*(.*?))?(?=\nSource \[|\n=+$|\Z)",
    re.DOTALL,
)


def parse_web_sources(search_text: str) -> list[Source]:
    """Parse the formatted output of ``perform_web_search`` into sources."""
    if not search_text:
        return []
    sources: list[Source] = []
    for match in _WEB_SOURCE_RE.finditer(search_text):
        marker = int(match.group(1))
        sources.append(
            Source(
                marker=marker,
                title=(match.group(2) or "Untitled").strip(),
                kind="web",
                url=(match.group(3) or "").strip(),
                snippet=(match.group(4) or "").strip()[:600],
                content=(match.group(5) or "").strip()[:4000],
            )
        )
    return sources


def sources_from_text_refs(text_refs: list[dict]) -> list[Source]:
    """Build document sources from the RAG ``text_refs`` payload."""
    sources: list[Source] = []
    seen: set[str] = set()
    for ref in text_refs:
        file = (ref.get("file") or "").strip()
        section = (ref.get("section") or "").strip()
        key = f"{file}:{section}"
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            Source(
                marker=len(sources) + 1,
                title=section or file.split("/")[-1] or file or "Document",
                kind="document",
                file=file,
                section=section,
                snippet=(ref.get("snippet") or "").strip()[:600],
            )
        )
    return sources


# ── citation attachment ────────────────────────────────────────────────────


def attach_citations(
    answer: str,
    sources: list[Source],
    *,
    threshold: float = 0.16,
    max_per_sentence: int = 1,
) -> CitationResult:
    """Insert inline ``[n]`` markers into ``answer`` and score the result.

    Only plain prose sentences are considered; code blocks, headings, list
    markers and quotes are left untouched. Each sentence is linked to the
    best-matching source whose score clears ``threshold``.
    """
    if not answer:
        return CitationResult(text=answer or "", sources=list(sources))

    prepared: list[tuple[Source, set[str]]] = [(s, tokenize(s.search_text())) for s in sources]

    # Mask code/inline-code so their contents never receive citations, while
    # keeping character offsets aligned with the original answer.
    masked = _mask(answer, _FENCE_RE)
    masked = _mask(masked, _INLINE_CODE_RE)

    insertions: list[tuple[int, int]] = []  # (position, marker)
    citations: list[Citation] = []
    cited: set[int] = set()
    prose_count = 0
    score_total = 0.0

    for match in _SENTENCE_RE.finditer(masked):
        raw = match.group(0)
        if not _is_prose(raw):
            continue
        prose_count += 1
        tokens = tokenize(raw)
        scored = sorted(
            ((_score(tokens, st), s) for s, st in prepared),
            key=lambda pair: pair[0],
            reverse=True,
        )
        picked = [(sc, s) for sc, s in scored if sc >= threshold][:max_per_sentence]
        if not picked:
            continue

        pos = match.end()
        while pos > match.start() and answer[pos - 1].isspace():
            pos -= 1
        for score, source in picked:
            insertions.append((pos, source.marker))
            citations.append(
                Citation(
                    marker=source.marker,
                    source_id=source.id,
                    sentence=raw.strip()[:400],
                    score=round(score, 4),
                )
            )
            cited.add(source.marker)
            score_total += score

    # Apply insertions right-to-left so earlier offsets stay valid.
    text = answer
    for pos, marker in sorted(insertions, key=lambda item: item[0], reverse=True):
        text = f"{text[:pos]} [{marker}]{text[pos:]}"

    coverage = (len(citations) / prose_count) if prose_count else 0.0
    mean_score = (score_total / len(citations)) if citations else 0.0
    # Overall accuracy blends how much of the prose is cited with how strong
    # those matches are (0.35 treated as a strong lexical match).
    accuracy = 0.5 * coverage + 0.5 * min(1.0, mean_score / 0.35)

    return CitationResult(
        text=text,
        citations=citations,
        sources=list(sources),
        bibliography=build_bibliography(sources),
        accuracy=accuracy,
        coverage=coverage,
        mean_score=mean_score,
        cited_markers=sorted(cited),
    )


def build_bibliography(sources: list[Source]) -> str:
    """Render a numbered Markdown bibliography."""
    if not sources:
        return ""
    lines = ["#### Sources", ""]
    for source in sources:
        if source.kind == "web" and source.url:
            entry = f"{source.marker}. [{source.title}]({source.url})"
        elif source.file:
            location = source.file
            if source.section:
                location = f"{location} → {source.section}"
            entry = f"{source.marker}. `{location}`"
        else:
            entry = f"{source.marker}. {source.title}"
        lines.append(entry)
    return "\n".join(lines)


def existing_markers(text: str) -> list[int]:
    """Return inline ``[n]`` markers already present in an answer."""
    return sorted({int(m) for m in re.findall(r"\[(\d+)\]", text or "")})


def score_citation_accuracy(
    text: str, sources: list[Source], citations: list[Citation] | None = None
) -> float:
    """Score an already-cited answer: valid markers vs. total markers."""
    valid = {s.marker for s in sources}
    markers = existing_markers(text)
    if not markers:
        return 0.0
    good = sum(1 for m in markers if m in valid)
    return good / len(markers)


def finalize_citations(
    answer: str,
    sources: list[Source],
    *,
    threshold: float = 0.16,
) -> CitationResult:
    """Attach citations unless the model already cited sources itself.

    Some models emit their own ``[n]`` markers. In that case we keep the text
    as-is and only build the bibliography / score marker validity.
    """
    if existing_markers(answer):
        return CitationResult(
            text=answer,
            sources=list(sources),
            bibliography=build_bibliography(sources),
            accuracy=score_citation_accuracy(answer, sources),
            cited_markers=existing_markers(answer),
        )
    return attach_citations(answer, sources, threshold=threshold)
