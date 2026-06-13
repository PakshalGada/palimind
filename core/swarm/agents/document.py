from __future__ import annotations
from pathlib import Path
from core.swarm.agents.base import BaseAgent

class DocumentAgent(BaseAgent):
    """Agent responsible for deep-dive interactions with specific documents (Document Mode)."""
    
    def __init__(self, root: Path, ollama_url: str, model: str):
        super().__init__(
            name="DocumentAgent",
            system_prompt="You are a document analyst. You perform deep analysis, summarization, and extraction on specific files.",
            ollama_url=ollama_url,
            model=model
        )
        self.root = root
        
        self.register_tool(
            name="summarize_document",
            description="Summarize a specific document.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "The path to the file"}
                },
                "required": ["file_path"]
            },
            func=self._summarize
        )

    def _summarize(self, file_path: str) -> str:
        try:
            from core.tools.comparison import summarize_document
            return summarize_document(file_path, self.root, self.ollama_url, self.model)
        except Exception as e:
            return f"Error summarizing document: {e}"
