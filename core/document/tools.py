from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from core.config import load_config
from core.embedder import generate_embedding
from core.storage.vector_store import search as vector_search
from core.storage.db import get_connection, get_file_summary, fts_search
from core.document.graph import DocGraph


class DocumentToolSet:
    """Tools available in strict document mode.

    Each tool returns a dict with keys: success (bool), result (str), error (str|None).
    """

    def __init__(
        self,
        root: Path,
        ollama_url: str,
        embed_model: str,
        graph: DocGraph | None = None,
        progress_cb: Callable[[str], None] | None = None,
    ) -> None:
        self.root = root
        self.ollama_url = ollama_url
        self.embed_model = embed_model
        self.graph = graph
        self._progress = progress_cb

    def _progress_msg(self, msg: str) -> None:
        if self._progress:
            self._progress(msg)

    # ── search ───────────────────────────────────────────────────────────

    def search_documents(self, query: str, limit: int = 8) -> dict[str, Any]:
        """Hybrid search: semantic vector + BM25 keyword + graph traversal.

        Returns ranked chunks with source attribution.
        """
        self._progress_msg(f"Searching documents for: {query}")

        conn = get_connection(self.root)
        results: list[dict] = []
        seen_content: set[str] = set()

        try:
            # 1. Semantic vector search
            query_vec = generate_embedding(query, self.ollama_url, self.embed_model, root=self.root)
            vec_results = vector_search(self.root, query_vec, limit=limit)
            for r in vec_results:
                content = r.get("content", "")
                if content and content not in seen_content:
                    seen_content.add(content)
                    r["search_type"] = "semantic"
                    r["relevance"] = "high"
                    results.append(r)

            # 2. BM25 keyword search for complementary results
            kw_results = fts_search(conn, query, limit=limit)
            for r in kw_results:
                content = r.get("content", "")
                if content and content not in seen_content:
                    seen_content.add(content)
                    r["search_type"] = "keyword"
                    r["relevance"] = "medium"
                    results.append(r)

            # 3. Graph-based expansion
            if self.graph:
                for r in list(results):
                    fp = r.get("file_path", "")
                    if fp:
                        related = self.graph.get_related_files(fp)
                        for rel_fp in related[:3]:
                            summary = get_file_summary(conn, rel_fp)
                            if summary:
                                results.append({
                                    "file_path": rel_fp,
                                    "content": f"[Related document: {rel_fp}]\n{summary[:2000]}",
                                    "section_title": "Related Document",
                                    "search_type": "graph",
                                    "relevance": "low",
                                    "doc_year": r.get("doc_year"),
                                    "doc_type": r.get("doc_type"),
                                })
        finally:
            conn.close()

        # Deduplicate by file_path + content prefix.
        # Always keep graph-based results; cap regular results at *limit*.
        seen_paths: set[str] = set()
        deduped: list[dict] = []
        regular_count = 0
        for r in results:
            is_graph = r.get("search_type") == "graph"
            if not is_graph and regular_count >= limit:
                continue
            if not is_graph:
                regular_count += 1
            key = f"{r.get('file_path', '')}::{r.get('content', '')[:100]}"
            if key not in seen_paths:
                seen_paths.add(key)
                deduped.append(r)

        return {"success": True, "results": deduped, "total": len(deduped)}

    def search_by_metadata(
        self,
        query: str = "",
        doc_type: str | None = None,
        doc_year: int | None = None,
        entity_name: str | None = None,
        section: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Search documents filtered by metadata (type, year, entity, section)."""
        from core.storage.db import fts_search_filtered

        conn = get_connection(self.root)
        try:
            results = fts_search_filtered(
                conn, query or "",
                doc_type=doc_type,
                doc_year=doc_year,
                entity_name=entity_name,
                section_title=section,
                limit=limit,
            )
            return {"success": True, "results": results, "total": len(results)}
        finally:
            conn.close()

    # ── file I/O ─────────────────────────────────────────────────────────

    def read_file(self, file_path: str) -> dict[str, Any]:
        """Read the full content of an indexed file."""
        resolved = (self.root / file_path).resolve()
        try:
            if not resolved.exists():
                return {"success": False, "error": f"File not found: {file_path}", "result": ""}
            if not str(resolved).startswith(str(self.root.resolve())):
                return {"success": False, "error": "Path traversal denied", "result": ""}
            content = resolved.read_text(encoding="utf-8", errors="replace")
            return {"success": True, "result": content, "file_path": file_path}
        except Exception as e:
            return {"success": False, "error": str(e), "result": ""}

    def write_file(self, file_path: str, content: str) -> dict[str, Any]:
        """Write content to an indexed file (overwrites existing)."""
        resolved = (self.root / file_path).resolve()
        try:
            if not str(resolved).startswith(str(self.root.resolve())):
                return {"success": False, "error": "Path traversal denied"}
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return {"success": True, "result": f"Written {len(content)} bytes to {file_path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_file(self, file_path: str, content: str = "") -> dict[str, Any]:
        """Create a new file in the workspace (fails if exists)."""
        resolved = (self.root / file_path).resolve()
        try:
            if not str(resolved).startswith(str(self.root.resolve())):
                return {"success": False, "error": "Path traversal denied"}
            if resolved.exists():
                return {"success": False, "error": f"File already exists: {file_path}"}
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return {"success": True, "result": f"Created {file_path} ({len(content)} bytes)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_files(self, subdir: str = "", pattern: str = "") -> dict[str, Any]:
        """List files in the workspace, optionally filtered by subdir or glob pattern."""
        target = (self.root / subdir).resolve() if subdir else self.root.resolve()
        try:
            if not str(target).startswith(str(self.root.resolve())):
                return {"success": False, "error": "Path traversal denied", "files": []}

            import glob as _glob
            if pattern:
                matched = _glob.glob(str(target / pattern), recursive=True)
                files = [str(Path(p).relative_to(self.root)) for p in sorted(matched) if Path(p).is_file()]
            else:
                files = []
                for p in sorted(target.rglob("*")):
                    if p.is_file():
                        rel = str(p.relative_to(self.root))
                        if not rel.startswith(".palimind"):
                            files.append(rel)

            return {"success": True, "files": files[:200], "total": len(files)}
        except Exception as e:
            return {"success": False, "error": str(e), "files": []}

    def get_file_summary(self, file_path: str) -> dict[str, Any]:
        """Return the indexed summary for a file."""
        conn = get_connection(self.root)
        try:
            summary = get_file_summary(conn, file_path)
            if summary:
                return {"success": True, "summary": summary, "file_path": file_path}
            return {"success": True, "summary": "", "file_path": file_path, "note": "No summary available"}
        finally:
            conn.close()

    # ── graph ────────────────────────────────────────────────────────────

    def query_graph(self, entity_name: str = "", file_path: str = "") -> dict[str, Any]:
        """Query the document knowledge graph for entities and relationships."""
        if not self.graph:
            return {"success": False, "error": "No document graph loaded"}
        if entity_name:
            files = self.graph.search_by_entity(entity_name)
            return {"success": True, "entity": entity_name, "related_files": [f.get("file_path", "") for f in files]}
        if file_path:
            node = self.graph.get_file_node(file_path)
            related = self.graph.get_related_files(file_path)
            return {"success": True, "file_node": node, "related_files": related}
        return {"success": True, "node_count": len(self.graph.nodes), "edge_count": len(self.graph.edges)}
