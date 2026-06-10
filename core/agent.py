from __future__ import annotations

import re
import httpx


# ---------------------------------------------------------------------------
# Fast heuristic patterns for needs_retrieval — avoids LLM round-trip
# ---------------------------------------------------------------------------

# These patterns reliably signal the query needs NO retrieval.
_NO_RETRIEVAL_PATTERNS = re.compile(
    r"^\s*("
    r"(hi|hello|hey|howdy|greetings)[!,.\s]*|"          # greetings
    r"(thanks?|thank\s+you|thx|ty)[!,.\s]*|"            # thanks
    r"(bye|goodbye|see\s+you)[!,.\s]*|"                  # farewells
    r"(yes|no|ok|okay|sure|got\s+it|great|perfect)[!,.\s]*|"  # ack
    r"(what\s+(is|are)\s+\d[\d\s+\-*/()^.]+)|"          # math
    r"(how\s+are\s+you)|"                                # small talk
    r"(who\s+are\s+you|what\s+can\s+you\s+do)"          # meta
    r")\s*$",
    re.IGNORECASE,
)

# Keywords that strongly suggest retrieval IS needed.
_YES_RETRIEVAL_KEYWORDS = re.compile(
    r"\b("
    r"file|document|code|function|class|method|variable|config|"
    r"summarize|summarise|explain|describe|what\s+does|how\s+does|"
    r"find|search|look\s+up|show\s+me|list|index|indexed|"
    r"error|bug|fix|issue|implement|write|create|generate"
    r")\b",
    re.IGNORECASE,
)


def _heuristic_needs_retrieval(query: str) -> bool | None:
    """Return True/False if confident, None if uncertain (needs LLM fallback)."""
    stripped = query.strip()
    if not stripped:
        return False
    if _NO_RETRIEVAL_PATTERNS.match(stripped):
        return False
    if _YES_RETRIEVAL_KEYWORDS.search(stripped):
        return True
    # Uncertain — let LLM decide
    return None


# ---------------------------------------------------------------------------
# Heuristic for detecting standalone queries (skip reformulation)
# ---------------------------------------------------------------------------

_PRONOUN_PATTERN = re.compile(
    r"\b(it|its|they|them|their|this|that|these|those|he|she|his|her|we|our)\b",
    re.IGNORECASE,
)


def _is_standalone(query: str, history: list[dict]) -> bool:
    """True if the query is clearly standalone and reformulation can be skipped."""
    if not history:
        return True
    words = query.split()
    if len(words) > 12:
        return False  # Longer queries may need context resolution
    if _PRONOUN_PATTERN.search(query):
        return False  # Pronoun reference → likely needs history for resolution
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reformulate_query(query: str, history: list[dict], ollama_url: str, model: str) -> str:
    """Rewrite a follow-up query into a standalone question for semantic search.

    Skips the LLM call entirely when the query is already standalone,
    saving ~1–2 s on every self-contained question.
    """
    if _is_standalone(query, history):
        return query

    system_prompt = (
        "You are an expert query reformulator. "
        "Given the following conversation history and a follow-up user query, "
        "rewrite the follow-up query to be a standalone question that can be "
        "understood without the conversation history. "
        "DO NOT answer the query. ONLY return the rewritten standalone query. "
        "If the query is already standalone, just return it exactly as is."
    )

    messages = [{"role": "system", "content": system_prompt}]
    history_text = "\n".join(
        [f"{msg['role'].capitalize()}: {msg['content']}" for msg in history[-6:]]
    )
    user_prompt = (
        f"Chat History:\n{history_text}\n\nFollow-up Query: {query}\n\nStandalone Query:"
    )
    messages.append({"role": "user", "content": user_prompt})

    url = f"{ollama_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.0},
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            rewritten = data.get("message", {}).get("content", "").strip().strip("\"'")
            return rewritten if rewritten else query
    except Exception:
        return query


def needs_retrieval(query: str, history: list[dict], ollama_url: str, model: str) -> bool:
    """Determine if the query requires the indexed knowledge base.

    Uses fast regex heuristics first (~0 ms). If the heuristics are uncertain
    (return None), we default to True (retrieve context) to avoid slow, fragile
    LLM intent classification calls and prevent missing relevant context.
    """
    result = _heuristic_needs_retrieval(query)
    if result is not None:
        return result
    return True
