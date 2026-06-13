from __future__ import annotations
from core.swarm.agents.base import BaseAgent

class ComparatorAgent(BaseAgent):
    def __init__(self, ollama_url: str, model: str):
        super().__init__(
            name="Comparator",
            system_prompt="""You are the Comparator Agent. Your job is to compare documents based on the retrieved context in the conversation history.
Use the `compute_diff` tool if you need a strict deterministic diff between text segments.
Otherwise, summarize the differences directly. After finishing, you must transfer to the Verifier agent.""",
            ollama_url=ollama_url,
            model=model
        )
        self.register_tool(
            name="compute_diff",
            description="Compute a strict line-by-line diff between two texts.",
            parameters={
                "type": "object",
                "properties": {
                    "text1": {"type": "string"},
                    "text2": {"type": "string"}
                },
                "required": ["text1", "text2"]
            },
            func=self._compute_diff
        )

    def _compute_diff(self, text1: str, text2: str) -> str:
        from core.tools.diff_engine import compute_diff
        return compute_diff(text1, text2)
