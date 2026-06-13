from __future__ import annotations
from pathlib import Path
import json

from core.swarm.agents.base import BaseAgent
from core.retrieval.searcher import retrieve_by_metadata
from core.retrieval.query_rewriter import rewrite_query

class PlannerAgent(BaseAgent):
    """
    Lightweight planner that processes the user query (rewriting, filtering, retrieval)
    and then transfers to the appropriate task-specific agent.
    """
    def __init__(self, root: Path, ollama_url: str, model: str):
        super().__init__(
            name="Planner",
            system_prompt="""You are the Planner Agent. Your job is to:
1. Understand the user's query and the retrieved context provided below.
2. Transfer to the most appropriate specialized agent (Comparator, Timeline, Advisor, Researcher, QuoteExtractor) to formulate the final answer.
Do not attempt to answer the question yourself. For general questions use Researcher.""",
            ollama_url=ollama_url,
            model=model
        )
        self.root = root
        
    def run(self, messages: list[dict], stream: bool = False):
        # Check if context was already injected
        has_context = any("CONTEXT INJECTED FROM KNOWLEDGE BASE" in m.get("content", "") for m in messages)
        
        if not has_context and messages:
            last_msg = messages[-1]["content"]
            
            # Extract files if user selected them
            files = []
            if "[User selected files:" in last_msg:
                try:
                    lines = last_msg.split("[User selected files:")[1].split("]")[0].strip().split("\n")
                    for line in lines:
                        if line.startswith("- "):
                            files.append(line[2:].strip())
                except Exception:
                    pass
            
            # Extract raw query
            query = last_msg.split("\n\n")[-1] if "\n\n" in last_msg else last_msg
            
            # Run the deterministic retrieval pipeline
            context_str = self._prepare_context(query, files if files else None)
            
            # Inject context
            messages[-1]["content"] = f"CONTEXT INJECTED FROM KNOWLEDGE BASE:\n{context_str}\n\nUser Query:\n{last_msg}"
            
        return super().run(messages, stream)

    def _prepare_context(self, query: str, files: list[str] | None = None) -> str:
        try:
            # 1. Query Rewrite
            rewritten = rewrite_query(query, self.ollama_url, self.model, self.root)
            primary_query = rewritten.search_queries[0] if rewritten.search_queries else query
            
            # 2. Metadata filtering
            doc_year = rewritten.years[0] if rewritten.years and len(rewritten.years) == 1 else None
            section_title = rewritten.sections[0] if rewritten.sections else None
            
            # 3. Hybrid Search + Reranking + Parent Retrieval
            if rewritten.years and len(rewritten.years) > 1:
                from core.retrieval.searcher import retrieve_for_comparison
                comp_results = retrieve_for_comparison(
                    primary_query, self.root, rewritten.years, chunks_per_doc=4, section_title=section_title, files_filter=files
                )
                results = []
                for chunks in comp_results.values():
                    results.extend(chunks)
            else:
                results = retrieve_by_metadata(
                    primary_query, self.root, limit=12,
                    doc_year=doc_year, section_title=section_title,
                    files_filter=files
                )
            
            if not results:
                return "No context found. Transfer to a generic agent or inform the user."
            
            # Extract content to reduce context window size
            context_data = []
            for r in results:
                context_data.append({
                    "file_path": r.get("file_path"),
                    "doc_year": r.get("doc_year"),
                    "section_title": r.get("section_title"),
                    "content": r.get("content")
                })
            return json.dumps(context_data)
        except Exception as e:
            return f"Error preparing context: {e}"
