from __future__ import annotations
from core.swarm.agents.base import BaseAgent

class QuoteExtractorAgent(BaseAgent):
    def __init__(self, ollama_url: str, model: str):
        super().__init__(
            name="QuoteExtractor",
            system_prompt="""You are the Quote Extractor Agent. Your job is to pull exact verbatim quotes from the retrieved context that match the user's query.
After finishing, you must transfer to the Verifier agent.""",
            ollama_url=ollama_url,
            model=model
        )
