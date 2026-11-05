"""Document knowledge-graph endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

router = APIRouter(prefix="/api/document", tags=["knowledge"])


@router.get("/graph")
async def get_document_graph():
    from palimind import api_server as server

    if not server.state.active_field:
        return {"error": "No active field", "nodes": [], "edges": []}
    try:
        from palimind.document.graph import DocGraph

        graph = DocGraph.load(server.state.active_field)
        needs_rebuild = False
        if graph is None or len(graph.nodes) == 0:
            from palimind.storage.db import get_all_files, get_connection

            try:
                conn = get_connection(server.state.active_field)
                files = get_all_files(conn)
                conn.close()
                needs_rebuild = bool(files)
            except Exception:
                needs_rebuild = False
            if graph is None:
                graph = DocGraph(server.state.active_field)
        nodes = [
            {
                "id": nid,
                "type": ndata.get("type", "unknown"),
                "label": ndata.get("label", nid),
                "file_path": ndata.get("file_path", ""),
            }
            for nid, ndata in graph.nodes.items()
        ]
        edges = [
            {"source": e["source"], "target": e["target"], "relation": e["relation"]}
            for e in graph.edges
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "indexed_files": len(graph.file_nodes),
            "needs_rebuild": needs_rebuild,
        }
    except Exception:
        return {"error": "Failed to get document graph", "nodes": [], "edges": []}


@router.post("/graph/rebuild")
async def rebuild_document_graph():
    from palimind import api_server as server

    if not server.state.active_field:
        return {"error": "No active field"}
    try:
        from palimind.config import load_config as _lc
        from palimind.document.graph import build_doc_graph

        cfg = _lc(server.state.active_field)
        ollama_url = cfg.get("ollama_base_url", "http://localhost:11434")
        graph = await asyncio.to_thread(build_doc_graph, server.state.active_field, ollama_url)
        return {
            "status": "success",
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "indexed_files": len(graph.file_nodes),
        }
    except Exception:
        return {"error": "Failed to rebuild document graph"}
