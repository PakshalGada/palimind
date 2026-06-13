from __future__ import annotations
from core.swarm.agents.base import BaseAgent

class TimelineAgent(BaseAgent):
    def __init__(self, ollama_url: str, model: str):
        super().__init__(
            name="Timeline",
            system_prompt="""You are the Timeline Agent. Your job is to build a chronological timeline from the retrieved context.
After finishing, you must transfer to the Verifier agent.""",
            ollama_url=ollama_url,
            model=model
        )
