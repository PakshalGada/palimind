from __future__ import annotations
from pathlib import Path
from core.swarm.agents.base import BaseAgent
from core.retrieval.searcher import retrieve_documents
import json

class RAGAgent(BaseAgent):
    """Agent responsible for searching the local indexed knowledge base."""
    
    def __init__(self, root: Path, ollama_url: str, model: str):
        super().__init__(
            name="RAGAgent",
            system_prompt="You are a research assistant. You search the local knowledge base to answer questions. Use the list_documents tool to see all available files. Use the retrieve_documents tool to search for specific information.",
            ollama_url=ollama_url,
            model=model
        )
        self.root = root
        
        self.register_tool(
            name="retrieve_documents",
            description="Search the local indexed documents for a given query.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "limit": {"type": "integer", "description": "Number of results to return", "default": 5}
                },
                "required": ["query"]
            },
            func=self._retrieve
        )

        self.register_tool(
            name="list_documents",
            description="List all indexed documents in the workspace.",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            func=self._list_docs
        )

    def _retrieve(self, query: str, limit: int = 5) -> str:
        try:
            results = retrieve_documents(query, self.root, limit=limit)
            if not results:
                return "No results found for this query. Try rephrasing or use list_documents to see available files."
            return json.dumps(results, default=str)
        except Exception as e:
            return f"Error retrieving documents: {e}"

    def _list_docs(self) -> str:
        try:
            from core.storage.db import get_connection, get_all_files
            conn = get_connection(self.root)
            try:
                files = get_all_files(conn)
                if not files:
                    return "No documents are currently indexed in the workspace."
                return json.dumps([{"path": f["path"], "summary": f["summary"]} for f in files])
            finally:
                conn.close()
        except Exception as e:
            return f"Error listing documents: {e}"
