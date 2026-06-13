from __future__ import annotations
from core.swarm.agents.base import BaseAgent

class EmailAgent(BaseAgent):
    """Agent responsible for email interaction."""
    
    def __init__(self, ollama_url: str, model: str):
        super().__init__(
            name="EmailAgent",
            system_prompt="You are an email assistant. You can read, search, and draft emails for the user.",
            ollama_url=ollama_url,
            model=model
        )
        
        self.register_tool(
            name="search_emails",
            description="Search local emails.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"]
            },
            func=self._search_emails
        )

    def _search_emails(self, query: str) -> str:
        try:
            from core.email.store import search_fts
            results = search_fts(query, limit=5)
            if not results:
                return "No emails found matching the query."
            formatted = []
            for r in results:
                formatted.append(f"Subject: {r.subject}\nSender: {r.sender}\nSnippet: {r.snippet}")
            return "\n\n".join(formatted)
        except Exception as e:
            return f"Error searching emails: {e}"
