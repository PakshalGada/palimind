from __future__ import annotations
from core.swarm.agents.base import BaseAgent

class VerifierAgent(BaseAgent):
    def __init__(self, ollama_url: str, model: str):
        super().__init__(
            name="Verifier",
            system_prompt="""You are the Verification Agent. Your job is to read the previous response and verify its claims against the retrieved chunks in the conversation history.
Strip out any unsupported claims. Format the final output cleanly. Do not call any transfer tools; your output is the final answer.""",
            ollama_url=ollama_url,
            model=model
        )
