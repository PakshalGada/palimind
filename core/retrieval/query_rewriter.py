import json
import re
import httpx
from dataclasses import dataclass
from typing import Any

@dataclass
class RewrittenQuery:
    original: str
    keywords: list[str]
    entities: list[str]
    years: list[int]
    sections: list[str]
    search_queries: list[str]
    is_comparison: bool

    @classmethod
    def default(cls, original: str) -> "RewrittenQuery":
        return cls(
            original=original,
            keywords=[],
            entities=[],
            years=[],
            sections=[],
            search_queries=[original],
            is_comparison=False,
        )

def rewrite_query(query: str, ollama_url: str, chat_model: str) -> RewrittenQuery:
    """
    Rewrite the user query to extract entities, years, sections, and multiple sub-queries.
    """
    prompt = f"""You are a query analysis engine. Analyze the following user query for a RAG system and output a JSON object.
Do NOT output any markdown, markdown codeblocks, or explanations. ONLY output the raw JSON object.

Extract the following fields:
- "keywords": list of important string keywords
- "entities": list of specific entities (like companies, people, products)
- "years": list of 4-digit integers if any years are mentioned
- "sections": list of specific document sections mentioned (e.g. "Supply of Components", "Risk Factors", "Competition")
- "search_queries": list of 2-4 optimized string queries for semantic search. The first should be a cleaned up version of the original.
- "is_comparison": boolean. True if the user is asking to compare, find differences, see what changed, added, removed, etc.

Query: "{query}"

JSON:"""

    try:
        resp = httpx.post(
            f"{ollama_url.rstrip('/')}/api/chat",
            json={
                "model": chat_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")

        # Try to extract JSON from the output
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            content = m.group(0)

        data = json.loads(content)
        return RewrittenQuery(
            original=query,
            keywords=data.get("keywords", []),
            entities=data.get("entities", []),
            years=data.get("years", []),
            sections=data.get("sections", []),
            search_queries=data.get("search_queries", [query]),
            is_comparison=bool(data.get("is_comparison", False)),
        )
    except Exception as e:
        # Fallback to default if there is any error parsing or calling the API
        return RewrittenQuery.default(query)
