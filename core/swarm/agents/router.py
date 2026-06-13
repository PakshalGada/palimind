from __future__ import annotations
import re
from core.swarm.agents.base import BaseAgent


# Keywords used as a fallback when the LLM does not emit a transfer tool call
_EMAIL_KEYWORDS = re.compile(
    r"\b(emails?|mails?|inbox|inboxes|sender|subject|newsletter|newsletters|unread|gmail|outlook|e-mail)\b",
    re.IGNORECASE,
)
_DOCUMENT_KEYWORDS = re.compile(
    r"\b(summarize|summarise|pdf|doc|docx|analyse|analyze|this file|open file|extract from)\b",
    re.IGNORECASE,
)
_PLANNER_KEYWORDS = re.compile(
    r"\b(search|find|look up|lookup|retrieve|knowledge base|documents?|research|report|what does.*say|tell me about|notes?)\b",
    re.IGNORECASE,
)


def keyword_route(query: str) -> str | None:
    """Return a target agent name based on simple keyword heuristics, or None.

    Priority: email > document > rag
    """
    # Email is checked first because queries like "search my emails" contain
    # both email and search keywords — the intent is clearly email.
    if _EMAIL_KEYWORDS.search(query):
        return "email"
    if _DOCUMENT_KEYWORDS.search(query):
        return "document"
    if _PLANNER_KEYWORDS.search(query):
        return "planner"
    return None


class RouterAgent(BaseAgent):
    """Entry-point agent that routes conversations to the appropriate specialized agent."""

    def __init__(self, ollama_url: str, model: str):
        super().__init__(
            name="RouterAgent",
            system_prompt=(
                "You are the Swarm Router. Your sole responsibility is to read the user's query "
                "and immediately call the appropriate transfer tool — do NOT answer the query yourself.\n\n"
                "Routing rules (apply the FIRST matching rule):\n"
                "1. If the query mentions emails, inbox, sender, subject, newsletter, or anything "
                "   related to email → call transfer_to_email.\n"
                "2. If the user has selected a specific file and wants it analysed, summarised, "
                "   or extracted → call transfer_to_document.\n"
                "3. If the query asks to search, find, retrieve, or look up information from the "
                "   local knowledge base / workspace documents → call transfer_to_planner.\n"
                "4. If the query is a simple greeting or general knowledge question with no local "
                "   document context needed → answer it directly WITHOUT calling any transfer tool.\n\n"
                "You MUST call a transfer tool for all non-trivial queries. Do not explain your "
                "decision — just call the tool."
            ),
            ollama_url=ollama_url,
            model=model,
        )
