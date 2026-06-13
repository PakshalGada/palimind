from __future__ import annotations
from core.swarm.agents.base import BaseAgent

class AdvisorAgent(BaseAgent):
    def __init__(self, ollama_url: str, model: str):
        super().__init__(
            name="Advisor",
            system_prompt="""You are the Advisor Agent. Your job is to extract recommendations or advice from the retrieved context.
After finishing, you must transfer to the Verifier agent.""",
            ollama_url=ollama_url,
            model=model
        )
