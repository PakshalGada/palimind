from __future__ import annotations
from core.swarm.agents.base import BaseAgent

class ResearcherAgent(BaseAgent):
    def __init__(self, ollama_url: str, model: str):
        super().__init__(
            name="Researcher",
            system_prompt="""You are the Researcher Agent. Your job is to synthesize a general answer based on the retrieved context.
After finishing, you must transfer to the Verifier agent.""",
            ollama_url=ollama_url,
            model=model
        )
