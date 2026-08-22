from __future__ import annotations

from pathlib import Path
from typing import Any


def query_graph(entity_name: str = "", file_path: str = "") -> str:
    """Query the field's document knowledge graph for entities, files and
    relationships. Lifts the graph query capability out of DocumentToolSet
    so it is available in the main tool registry."""
    from core.llm.mixture_of_expert.tools import _get_context

    ctx = _get_context()
    root: Path | None = ctx.get("root")
    if root is None:
        return "Error: no active workspace configured for graph queries."

    from core.config import load_config
    from core.document.graph import load_doc_graph

    config = load_config(root)
    ollama_url = ctx.get("ollama_url") or config.get(
        "ollama_base_url", "http://localhost:11434"
    )

    try:
        graph = load_doc_graph(root, ollama_url, force_rebuild=False)
    except Exception as e:
        return f"Error loading document graph: {e}"
    if graph is None:
        return "Error: no document knowledge graph found for this field (run a sync first)."

    if entity_name:
        try:
            files = graph.search_by_entity(entity_name)
            rel = [f.get("file_path", "") for f in files if isinstance(f, dict)]
            if not rel:
                return f"No entities matching '{entity_name}' found in the graph."
            return (
                f"Entities matching '{entity_name}':\n"
                + "\n".join(f"  - {p}" for p in rel[:20])
            )
        except Exception as e:
            return f"Error querying entity '{entity_name}': {e}"

    if file_path:
        try:
            node = graph.get_file_node(file_path)
            related = graph.get_related_files(file_path)
            lines = [f"File node: {node or 'not found'}"]
            if related:
                lines.append("Related files:")
                lines += [f"  - {r}" for r in related[:20]]
            return "\n".join(lines)
        except Exception as e:
            return f"Error querying file '{file_path}': {e}"

    return (
        f"Document graph summary: {len(graph.nodes)} nodes, "
        f"{len(graph.edges)} edges, {len(graph.file_nodes)} files."
    )


# registry metadata for the main TOOL_REGISTRY
TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Query the field's document knowledge graph (entities, related files, "
        "relationships). Provide entity_name or file_path."
    ),
    "parameters": {
        "entity_name": "Optional: an entity to look up in the graph",
        "file_path": "Optional: a file path to look up in the graph",
    },
    "tier": 1,
    "requires_approval": False,
}
