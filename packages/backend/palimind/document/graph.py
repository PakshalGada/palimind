"""Knowledge graph of indexed documents: file relationships, sections, entities.

Design notes (Phase 2):
* ``load_doc_graph`` is **load-only** — it never calls an LLM on the query path.
* Graph builds are **incremental**: a ``path → md5`` map is persisted in the
  JSON, so sync/capture only re-extract entities for new or changed files.
* Entities are seeded from ``files.entity_name`` (index-time regex) before any
  LLM extraction, and names are normalized (casefold + suffix strip) so lookups
  are case-insensitive.
* Edges are deduplicated and backed by an adjacency index for cheap lookups.
* ``entity_mentions`` is written at build time so SQLite/FTS stays aligned.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from palimind.config import load_config, palimind_dir
from palimind.storage.db import (
    clear_entity_mentions_for_path,
    get_chunk_ids_for_file,
    get_rich_chunks_for_file,
    insert_entity_mentions,
)

GRAPH_FILE = "doc_graph.json"

_ENTITY_SUFFIXES = (
    "inc",
    "corp",
    "corporation",
    "llc",
    "ltd",
    "limited",
    "co",
    "company",
    "gmbh",
    "plc",
    "ag",
    "s.a.",
)


def normalize_entity_name(name: str) -> str:
    """Canonical form for entity matching: casefold + strip legal suffix."""
    n = re.sub(r"[.,;:!?]+$", "", (name or "").strip()).strip()
    cf = n.casefold()
    for suffix in _ENTITY_SUFFIXES:
        pat = r"\b" + re.escape(suffix) + r"\b"
        if re.search(pat, cf):
            cf = re.sub(pat, "", cf).strip()
            break
    return cf or n.casefold()


def entity_node_id(canonical: str) -> str:
    return f"entity:{canonical}"


class DocGraph:
    """Knowledge graph of indexed documents: file relationships, sections, entities."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.nodes: dict[str, dict[str, Any]] = {}  # node_id -> metadata
        self.edges: list[dict[str, Any]] = []  # {source, target, relation, weight}
        self.file_nodes: dict[str, str] = {}  # file_path -> node_id
        self.file_hashes: dict[str, str] = {}  # file_path -> md5 (incremental tracking)
        self.adj: dict[str, set[str]] = {}  # node_id -> set of connected node_ids
        self._edge_keys: set[tuple[str, str, str]] = set()
        self.dirty = False

    # ── persistence ──────────────────────────────────────────────────────

    def path(self) -> Path:
        return palimind_dir(self.root) / GRAPH_FILE

    def save(self) -> None:
        data = {
            "nodes": self.nodes,
            "edges": self.edges,
            "file_nodes": self.file_nodes,
            "file_hashes": self.file_hashes,
        }
        self.path().parent.mkdir(parents=True, exist_ok=True)
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
            g.file_hashes = data.get("file_hashes", {})
            g._rebuild_index()
            return g
        except Exception:
            return None

    def _rebuild_index(self) -> None:
        """Rebuild adjacency + edge-key indexes from the raw edge list."""
        self.adj = {}
        self._edge_keys = set()
        for e in self.edges:
            src, tgt, rel = e["source"], e["target"], e["relation"]
            self.adj.setdefault(src, set()).add(tgt)
            self.adj.setdefault(tgt, set()).add(src)
            self._edge_keys.add((src, tgt, rel))

    # ── graph operations ─────────────────────────────────────────────────

    def add_file_node(
        self,
        file_path: str,
        label: str = "",
        doc_type: str = "other",
        doc_year: int | None = None,
        summary: str = "",
        md5: str = "",
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
        if md5:
            self.file_hashes[file_path] = md5
        self.dirty = True
        return node_id

    def add_section_node(self, section_name: str, file_path: str) -> str:
        node_id = f"section:{file_path}::{section_name}"
        if node_id in self.nodes:
            return node_id
        self.nodes[node_id] = {
            "type": "section",
            "label": section_name,
            "file_path": file_path,
        }
        self.dirty = True
        return node_id

    def add_entity_node(self, entity_name: str, entity_type: str = "organization") -> str:
        canonical = normalize_entity_name(entity_name)
        node_id = entity_node_id(canonical)
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                "type": "entity",
                "label": entity_name.strip(),
                "entity_type": entity_type,
            }
            self.dirty = True
        return node_id

    def add_edge(self, source: str, target: str, relation: str, weight: float = 1.0) -> None:
        key = (source, target, relation)
        if key in self._edge_keys:
            return
        self.edges.append(
            {"source": source, "target": target, "relation": relation, "weight": weight}
        )
        self._edge_keys.add(key)
        self.adj.setdefault(source, set()).add(target)
        self.adj.setdefault(target, set()).add(source)
        self.dirty = True

    def remove_file(self, file_path: str) -> None:
        """Drop a file node and every edge/nodes that only it touches."""
        nid = self.file_nodes.pop(file_path, None)
        self.file_hashes.pop(file_path, None)
        if nid is None:
            return

        # Section nodes belong to a single file — always remove them.
        section_ids = [
            n
            for n, meta in self.nodes.items()
            if meta.get("type") == "section" and meta.get("file_path") == file_path
        ]

        removed: set[str] = set()
        kept: list[dict] = []
        for e in self.edges:
            if e["source"] in {nid, *section_ids} or e["target"] in {nid, *section_ids}:
                self._edge_keys.discard((e["source"], e["target"], e["relation"]))
                continue
            kept.append(e)
            # Track entity nodes touched by this file's edges
            for side in (e["source"], e["target"]):
                if self.nodes.get(side, {}).get("type") == "entity":
                    removed.add(side)
        self.edges = kept

        # Remove the file node and its sections.
        for nid_to_drop in [nid, *section_ids]:
            self.nodes.pop(nid_to_drop, None)

        # Drop entity nodes that no longer have any edges.
        entity_ids = [n for n, m in self.nodes.items() if m.get("type") == "entity"]
        for ent in entity_ids:
            if not any(e["source"] == ent or e["target"] == ent for e in self.edges):
                self.nodes.pop(ent, None)

        self._rebuild_index()
        self.dirty = True

    # ── query ────────────────────────────────────────────────────────────

    def get_file_node(self, file_path: str) -> dict[str, Any] | None:
        nid = self.file_nodes.get(file_path)
        return self.nodes.get(nid) if nid else None

    def get_related_files(self, file_path: str, relation: str | None = None) -> list[str]:
        """Return file paths related to *file_path*.

        Follows direct file→file edges (``related_via``) and traverses shared
        entity nodes (2-hop: file → entity → file). When *relation* is given,
        only edges of that relation are considered.
        """
        nid = self.file_nodes.get(file_path)
        if not nid:
            return []

        related: set[str] = set()
        for neighbor in self.adj.get(nid, set()):
            node = self.nodes.get(neighbor)
            if not node:
                continue
            if node.get("type") == "file":
                if relation is None or any(
                    e["relation"] == relation
                    for e in self.edges
                    if {e["source"], e["target"]} == {nid, neighbor}
                ):
                    fp = node.get("file_path", "")
                    if fp and fp != file_path:
                        related.add(fp)
            elif node.get("type") == "entity":
                for f in self._files_for_entity(neighbor):
                    fp = f.get("file_path", "")
                    if fp and fp != file_path:
                        related.add(fp)
        return sorted(related)

    def search_by_entity(self, entity_name: str) -> list[dict[str, Any]]:
        """Find all file nodes associated with an entity (case-insensitive)."""
        canonical = normalize_entity_name(entity_name)
        nid = entity_node_id(canonical)

        # Exact canonical match first.
        if nid in self.nodes:
            return self._files_for_entity(nid)

        # Fallback: substring match over entity labels.
        cf = entity_name.casefold()
        matches: list[dict[str, Any]] = []
        for node_id, meta in self.nodes.items():
            if meta.get("type") != "entity":
                continue
            if len(meta.get("label", "")) >= 3 and cf in meta["label"].casefold():
                matches.extend(self._files_for_entity(node_id))
        seen: dict[str, dict[str, Any]] = {}
        for f in matches:
            seen[f.get("file_path", "")] = f
        return list(seen.values())

    def match_entities(self, query: str) -> list[str]:
        """Return canonical entity node ids whose label OR normalized name
        appears in *query* (case-insensitive). Short labels require a
        word-boundary match."""
        q = query.casefold()
        matches: list[str] = []
        for node_id, meta in self.nodes.items():
            if meta.get("type") != "entity":
                continue
            label = meta.get("label", "")
            candidates = {label.casefold()}
            if node_id.startswith("entity:"):
                candidates.add(node_id[len("entity:") :])
            for cf in candidates:
                if not cf:
                    continue
                if len(cf) < 3:
                    if re.search(rf"\b{re.escape(cf)}\b", q):
                        matches.append(node_id)
                        break
                elif cf in q:
                    matches.append(node_id)
                    break
        return matches

    def files_for_entity(self, node_id: str) -> list[str]:
        return [f["file_path"] for f in self._files_for_entity(node_id)]

    def _files_for_entity(self, node_id: str) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for neighbor in self.adj.get(node_id, set()):
            target = self.nodes.get(neighbor)
            if target and target.get("type") == "file":
                files.append(target)
        return files


# ── LLM entity extraction ──────────────────────────────────────────────


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


def _extract_entities_batched(
    file_excerpts: list[tuple[str, str]],
    ollama_url: str,
    light: str,
) -> dict[str, list[str]]:
    """LLM entity extraction for ``(path, excerpt)`` pairs, in batches of 10.

    Returns ``{path: [entity strings]}``. Fails safe on any batch.
    """
    extracted: dict[str, list[str]] = {}
    batch_size = 10
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
        m = re.search(r"\{.*\}", resp, re.DOTALL)
        if not m:
            continue
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        for idx, (fp, _) in enumerate(batch):
            entities = parsed.get(f"FILE {idx + 1}", [])
            if isinstance(entities, list):
                extracted[fp] = [str(e).strip() for e in entities if isinstance(e, str) and len(e) > 1]
    return extracted


def _file_excerpt(conn, f: dict) -> str:
    if f.get("summary"):
        return f["summary"][:2000]
    try:
        chunks = get_rich_chunks_for_file(conn, f["path"])
        if chunks:
            return chunks[0].get("content", "")[:2000]
    except Exception:
        pass
    return ""


def _add_file_nodes_and_sections(g: DocGraph, conn, f: dict) -> str:
    """Add a file node, its section nodes, and the seeded index-time entity.

    No LLM call — seeds from ``files.entity_name`` (regex extracted at index).
    """
    file_nid = g.add_file_node(
        file_path=f["path"],
        label=Path(f["path"]).name,
        doc_type=f.get("doc_type", "other"),
        doc_year=f.get("doc_year"),
        summary=f.get("summary", ""),
        md5=f.get("md5", ""),
    )

    seen_sections: set[str] = set()
    try:
        chunks = get_rich_chunks_for_file(conn, f["path"])
        for c in chunks:
            sec = c.get("section_title", "") or c.get("main_section", "")
            if sec and sec not in seen_sections:
                seen_sections.add(sec)
                g.add_edge(file_nid, g.add_section_node(sec, f["path"]), "has_section")
    except Exception:
        pass

    if f.get("entity_name"):
        g.add_edge(file_nid, g.add_entity_node(f["entity_name"]), "references")

    return file_nid


def _extract_entities_for_paths(
    g: DocGraph, conn, paths: list[str], ollama_url: str, light: str
) -> None:
    """LLM-extract entities for *paths* (batched) and wire references edges."""
    excerpts: list[tuple[str, str]] = []
    for p in paths:
        f = {"path": p}
        excerpt = _file_excerpt(conn, f)
        if excerpt:
            excerpts.append((p, excerpt[:1000]))
    if not excerpts:
        return
    extracted = _extract_entities_batched(excerpts, ollama_url, light)
    for p, entities in extracted.items():
        file_nid = g.file_nodes.get(p)
        if not file_nid:
            continue
        for ent in entities:
            g.add_edge(file_nid, g.add_entity_node(ent), "references")


def _link_related_files(g: DocGraph) -> None:
    """Add ``related_via`` edges between files sharing an entity."""
    for node_id, meta in list(g.nodes.items()):
        if meta.get("type") != "entity":
            continue
        files = [f for f in g._files_for_entity(node_id) if f.get("file_path")]
        for i, f1 in enumerate(files):
            for f2 in files[i + 1 :]:
                g.add_edge(
                    f"file:{f1['file_path']}",
                    f"file:{f2['file_path']}",
                    "related_via",
                    weight=0.5,
                )


def _write_entity_mentions(g: DocGraph, conn, paths: list[str]) -> None:
    """Populate the ``entity_mentions`` table so FTS/graph stay aligned.

    For each file, scan its chunks for each linked entity label (case-insensitive)
    and insert a mention row per match.
    """
    if not paths:
        return
    for path in paths:
        try:
            clear_entity_mentions_for_path(conn, path)
        except Exception:
            continue
        file_nid = g.file_nodes.get(path)
        if not file_nid:
            continue
        entity_labels: set[str] = set()
        for neighbor in g.adj.get(file_nid, set()):
            meta = g.nodes.get(neighbor)
            if meta and meta.get("type") == "entity":
                entity_labels.add(meta.get("label", ""))
        if not entity_labels:
            continue
        try:
            chunks = get_chunk_ids_for_file(conn, path)
        except Exception:
            continue
        rows: list[tuple] = []
        for chunk_id, content in chunks:
            content_cf = (content or "").casefold()
            for label in entity_labels:
                if label.casefold() in content_cf:
                    rows.append((chunk_id, label, "organization", content[:160]))
        if rows:
            try:
                insert_entity_mentions(conn, rows)
            except Exception:
                pass


# ── build entry points ─────────────────────────────────────────────────


def build_doc_graph(root: Path, ollama_url: str, light_model: str = "") -> DocGraph:
    """Full rebuild of the document knowledge graph."""
    from palimind.storage.db import get_connection, get_files_with_hash

    config = load_config(root)
    light = light_model or config.get("chat_model", "gemma4:e2b")

    g = DocGraph(root)
    conn = get_connection(root)
    try:
        files = get_files_with_hash(conn)
        paths: list[str] = []
        for f in files:
            _add_file_nodes_and_sections(g, conn, f)
            paths.append(f["path"])
        _extract_entities_for_paths(g, conn, paths, ollama_url, light)
        _link_related_files(g)
        _write_entity_mentions(g, conn, paths)
        conn.commit()
    finally:
        conn.close()

    g.save()
    print(f"[graph] built: {len(g.nodes)} nodes, {len(g.edges)} edges")
    return g


def build_doc_graph_incremental(
    root: Path, ollama_url: str, light_model: str = ""
) -> DocGraph:
    """Incrementally update the graph: drop deleted files, re-extract only
    new/changed files. Falls back to a full build when no graph exists."""
    from palimind.storage.db import get_connection, get_files_with_hash

    existing = DocGraph.load(root)
    if existing is None or len(existing.nodes) == 0:
        return build_doc_graph(root, ollama_url, light_model)

    config = load_config(root)
    light = light_model or config.get("chat_model", "gemma4:e2b")

    conn = get_connection(root)
    try:
        files = get_files_with_hash(conn)
    finally:
        conn.close()

    current = {f["path"]: f for f in files}
    prev_hashes = dict(existing.file_hashes)

    deleted = [p for p in prev_hashes if p not in current]
    changed = [
        p for p, f in current.items() if p not in prev_hashes or prev_hashes[p] != f["md5"]
    ]

    if deleted:
        for p in deleted:
            existing.remove_file(p)

    if changed:
        conn = get_connection(root)
        try:
            for p in changed:
                existing.remove_file(p)
            for p in changed:
                _add_file_nodes_and_sections(existing, conn, current[p])
            _extract_entities_for_paths(existing, conn, changed, ollama_url, light)
            _link_related_files(existing)
            _write_entity_mentions(existing, conn, changed)
            conn.commit()
        finally:
            conn.close()

    existing.file_hashes = {p: f["md5"] for p, f in current.items()}
    existing.save()
    print(
        f"[graph] incremental: {len(deleted)} removed, {len(changed)} updated, "
        f"{len(existing.nodes)} nodes, {len(existing.edges)} edges"
    )
    return existing


def load_doc_graph(
    root: Path, ollama_url: str = "", light_model: str = "", force_rebuild: bool = False
) -> DocGraph:
    """Load the graph from disk. Never calls an LLM unless *force_rebuild*."""
    if force_rebuild:
        return build_doc_graph(root, ollama_url, light_model)
    g = DocGraph.load(root)
    if g is not None and len(g.nodes) > 0:
        return g
    return DocGraph(root)
