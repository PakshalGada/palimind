from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from palimind.config import load_config, palimind_dir

GRAPH_FILE = "doc_graph.json"


class DocGraph:
    """Knowledge graph of indexed documents: file relationships, sections, entities."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.nodes: dict[str, dict[str, Any]] = {}  # node_id -> metadata
        self.edges: list[dict[str, Any]] = []  # {source, target, relation}
        self.file_nodes: dict[str, str] = {}  # file_path -> node_id
        self.dirty = False

    # ── persistence ──────────────────────────────────────────────────────

    def path(self) -> Path:
        return palimind_dir(self.root) / GRAPH_FILE

    def save(self) -> None:
        data = {
            "nodes": self.nodes,
            "edges": self.edges,
            "file_nodes": self.file_nodes,
        }
        self.path().write_text(json.dumps(data, separators=(",", ":")))

    @classmethod
    def load(cls, root: Path) -> DocGraph | None:
        p = palimind_dir(root) / GRAPH_FILE
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            g = cls(root)
            g.nodes = data.get("nodes", {})
            g.edges = data.get("edges", [])
            g.file_nodes = data.get("file_nodes", {})
            return g
        except Exception:
            return None

    # ── graph operations ─────────────────────────────────────────────────

    def add_file_node(
        self,
        file_path: str,
        label: str = "",
        doc_type: str = "other",
        doc_year: int | None = None,
        summary: str = "",
    ) -> str:
        node_id = f"file:{file_path}"
        self.nodes[node_id] = {
            "type": "file",
            "label": label or Path(file_path).name,
            "file_path": file_path,
            "doc_type": doc_type,
            "doc_year": doc_year,
            "summary": summary,
        }
        self.file_nodes[file_path] = node_id
        self.dirty = True
        return node_id

    def add_section_node(self, section_name: str, file_path: str) -> str:
        node_id = f"section:{file_path}::{section_name}"
        self.nodes[node_id] = {
            "type": "section",
            "label": section_name,
            "file_path": file_path,
        }
        self.dirty = True
        return node_id

    def add_entity_node(self, entity_name: str, entity_type: str = "organization") -> str:
        node_id = f"entity:{entity_name}"
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                "type": "entity",
                "label": entity_name,
                "entity_type": entity_type,
            }
            self.dirty = True
        return node_id

    def add_edge(self, source: str, target: str, relation: str, weight: float = 1.0) -> None:
        self.edges.append(
            {"source": source, "target": target, "relation": relation, "weight": weight}
        )
        self.dirty = True

    # ── query ────────────────────────────────────────────────────────────

    def get_file_node(self, file_path: str) -> dict[str, Any] | None:
        nid = self.file_nodes.get(file_path)
        return self.nodes.get(nid) if nid else None

    def get_related_files(self, file_path: str, relation: str | None = None) -> list[str]:
        """Return file paths related to *file_path* via shared entities/sections.

        When *relation* is None, all edge types are considered.
        """
        nid = self.file_nodes.get(file_path)
        if not nid:
            return []

        related: set[str] = set()
        for edge in self.edges:
            if relation is not None and edge["relation"] != relation:
                continue
            if edge["source"] == nid:
                target_node = self.nodes.get(edge["target"])
                if target_node and target_node["type"] == "file":
                    related.add(target_node["file_path"])
            elif edge["target"] == nid:
                source_node = self.nodes.get(edge["source"])
                if source_node and source_node["type"] == "file":
                    related.add(source_node["file_path"])
        return sorted(related)

    def search_by_entity(self, entity_name: str) -> list[dict[str, Any]]:
        """Find all file nodes associated with an entity."""
        entity_nid = f"entity:{entity_name}"
        if entity_nid not in self.nodes:
            return []
        files: list[dict[str, Any]] = []
        for edge in self.edges:
            if edge["source"] == entity_nid:
                target = self.nodes.get(edge["target"])
                if target and target["type"] == "file":
                    files.append(target)
        return files


def _light_llm_chat(prompt: str, ollama_url: str, model: str) -> str:
    """Call a smaller/cheaper LLM for light tasks like graph building."""
    import httpx

    url = f"{ollama_url.rstrip('/')}/api/chat"
    try:
        resp = httpx.post(
            url,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2048},
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception:
        return ""


def build_doc_graph(root: Path, ollama_url: str, light_model: str = "") -> DocGraph:
    """Build or rebuild the document knowledge graph.

    Uses *light_model* (a small/fast model) for entity extraction; falls back
    to the configured chat model if empty.
    """
    from palimind.storage.db import get_all_files, get_connection

    config = load_config(root)
    light = light_model or config.get("chat_model", "gemma4:e2b")

    g = DocGraph(root)

    # Get or create DB connection
    conn = get_connection(root)
    try:
        files = get_all_files(conn)
    except Exception as exc:
        print(f"[graph] get_all_files failed: {exc}")
        files = []
    finally:
        conn.close()

    if not files:
        # Still save so the cache knows we tried
        g.save()
        return g

    # 1. Add file nodes with summaries
    for f in files:
        g.add_file_node(
            file_path=f["path"],
            label=Path(f["path"]).name,
            doc_type=f.get("doc_type", "other"),
            doc_year=f.get("doc_year"),
            summary=f.get("summary", ""),
        )

    # 2. Add section nodes
    conn = get_connection(root)
    try:
        from palimind.storage.db import get_rich_chunks_for_file

        for f in files:
            file_nid = g.file_nodes.get(f["path"])
            if not file_nid:
                continue

            try:
                chunks = get_rich_chunks_for_file(conn, f["path"])
            except Exception as exc:
                print(f"[graph] get_rich_chunks_for_file failed for {f['path']}: {exc}")
                chunks = []

            seen_sections: set[str] = set()
            for c in chunks:
                sec = c.get("section_title", "") or c.get("main_section", "")
                if sec and sec not in seen_sections:
                    seen_sections.add(sec)
                    sec_nid = g.add_section_node(sec, f["path"])
                    g.add_edge(file_nid, sec_nid, "has_section")
    except Exception as exc:
        print(f"[graph] sections partial failure: {exc}")
    finally:
        conn.close()

    # 3. Entity extraction — batched via low-cost LLM
    conn = get_connection(root)
    try:
        from palimind.storage.db import get_rich_chunks_for_file

        batch_size = 10
        file_excerpts: list[tuple[str, str]] = []
        for f in files:
            file_nid = g.file_nodes.get(f["path"])
            if not file_nid:
                continue
            excerpt = ""
            if f.get("summary"):
                excerpt = f["summary"][:2000]
            else:
                try:
                    chunks = get_rich_chunks_for_file(conn, f["path"])
                    if chunks:
                        excerpt = chunks[0].get("content", "")[:2000]
                except Exception:
                    pass
            if excerpt:
                file_excerpts.append((f["path"], excerpt[:1000]))

        # Extract entities in batches
        for i in range(0, len(file_excerpts), batch_size):
            batch = file_excerpts[i : i + batch_size]
            batch_text = "\n---\n".join(
                f"FILE {idx + 1}: {fp}\n{excerpt}" for idx, (fp, excerpt) in enumerate(batch)
            )
            batch_prompt = (
                "Extract key entities (organizations, people, products, technologies) "
                "from each file below. Return ONLY valid JSON where keys are the "
                f'"FILE 1", "FILE 2", … labels and values are arrays of entity strings. '
                "If a file has no entities, use an empty array. Example:\n"
                '{"FILE 1": ["Acme Corp", "John Doe"], "FILE 2": []}\n\n'
                f"{batch_text}"
            )
            resp = _light_llm_chat(batch_prompt, ollama_url, light)
            if not resp:
                continue
            import re as _re

            m = _re.search(r"\{.*\}", resp, _re.DOTALL)
            if not m:
                continue
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            for idx, (fp, _) in enumerate(batch):
                file_nid = g.file_nodes.get(fp)
                if not file_nid:
                    continue
                entities = parsed.get(f"FILE {idx + 1}", [])
                if not isinstance(entities, list):
                    continue
                for ent in entities:
                    if isinstance(ent, str) and len(ent) > 1:
                        ent_nid = g.add_entity_node(ent.strip(), "organization")
                        g.add_edge(ent_nid, file_nid, "mentions")
                        g.add_edge(file_nid, ent_nid, "references")
    except Exception as exc:
        print(f"[graph] entity extraction partial failure: {exc}")
    finally:
        conn.close()

    # 4. Link related files via shared entity nodes
    try:
        for edge in list(g.edges):
            if edge["relation"] == "references":
                target_node = g.nodes.get(edge["target"])
                source_node = g.nodes.get(edge["source"])
                if target_node and source_node:
                    if target_node["type"] == "entity" and source_node["type"] == "file":
                        entity_nid = edge["target"]
                        for other_edge in g.edges:
                            if (
                                other_edge["relation"] == "references"
                                and other_edge["target"] == entity_nid
                            ):
                                other_file_nid = other_edge["source"]
                                if other_file_nid != edge["source"]:
                                    existing = any(
                                        e["source"] == edge["source"]
                                        and e["target"] == other_file_nid
                                        for e in g.edges
                                    )
                                    if not existing:
                                        g.add_edge(
                                            edge["source"],
                                            other_file_nid,
                                            "related_via",
                                            weight=0.5,
                                        )
    except Exception as exc:
        print(f"[graph] related-file linking partial failure: {exc}")

    g.save()
    print(f"[graph] built: {len(g.nodes)} nodes, {len(g.edges)} edges")
    return g


def load_doc_graph(
    root: Path, ollama_url: str = "", light_model: str = "", force_rebuild: bool = False
) -> DocGraph:
    """Load existing graph, build if missing or empty."""
    if not force_rebuild:
        g = DocGraph.load(root)
        if g is not None and len(g.nodes) > 0:
            return g
    print(f"[graph] rebuilding (force={force_rebuild})")
    return build_doc_graph(root, ollama_url, light_model)
