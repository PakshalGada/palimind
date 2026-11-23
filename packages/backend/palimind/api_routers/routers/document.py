"""Knowledge workspace endpoints (library, settings, retrieval, graph).

Every endpoint is scope-aware. ``scope=field`` targets the active folder-based
workspace; ``scope=project:<id>`` targets that project's private index whose
source files live in the project workspace.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/document", tags=["knowledge"])


def _scope(value: str | None) -> str:
    return (value or "field").strip() or "field"


def _roots(scope: str) -> tuple[Any, Any]:
    from palimind import knowledge

    root = knowledge.resolve_root(scope)
    content_root = knowledge.resolve_content_root(scope) or root
    return root, content_root


def _missing() -> dict[str, Any]:
    return {"error": "No active knowledge base", "scope": "field"}


# ── overview ─────────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_document_stats(scope: str = "field"):
    from palimind import knowledge

    scope = _scope(scope)
    root, _content = _roots(scope)
    if root is None:
        return _missing()
    payload = await asyncio.to_thread(knowledge.collect_stats, root)
    payload["scope"] = scope
    return payload


@router.get("/diagnostics")
async def get_document_diagnostics(scope: str = "field"):
    from palimind import knowledge

    scope = _scope(scope)
    root, content_root = _roots(scope)
    if root is None:
        return _missing()
    payload = await asyncio.to_thread(
        knowledge.diagnostics, root, content_root=content_root
    )
    payload["scope"] = scope
    return payload


# ── file library ─────────────────────────────────────────────────────────────


@router.get("/files")
async def list_document_files(
    scope: str = "field",
    q: str = "",
    doc_type: str = "",
    doc_year: int | None = None,
    entity: str = "",
    status: str = "all",
    sort: str = "recent",
    limit: int = 100,
    offset: int = 0,
):
    from palimind import knowledge

    scope = _scope(scope)
    root, _content = _roots(scope)
    if root is None:
        return {"files": [], "total": 0, "limit": limit, "offset": offset}
    payload = await asyncio.to_thread(
        knowledge.list_files,
        root,
        q=q,
        doc_type=doc_type,
        doc_year=doc_year,
        entity=entity,
        status=status,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    payload["scope"] = scope
    return payload


@router.get("/files/detail")
async def get_document_file(
    path: str,
    scope: str = "field",
    include_content: bool = False,
):
    from palimind import knowledge

    scope = _scope(scope)
    root, content_root = _roots(scope)
    if root is None:
        return _missing()
    payload = await asyncio.to_thread(
        knowledge.get_file_detail,
        root,
        path,
        include_content=include_content,
        content_root=content_root,
    )
    if payload is None:
        return {"error": "File not found", "path": path, "scope": scope}
    payload["scope"] = scope
    return payload


@router.post("/files/reindex")
async def reindex_document_file(req: Request):
    from palimind import knowledge

    try:
        body = await req.json()
    except Exception:
        body = {}
    scope = _scope(str(body.get("scope") or ""))
    path = str(body.get("path") or "")
    if not path:
        return {"error": "Path is required"}
    root, content_root = _roots(scope)
    if root is None:
        return _missing()
    try:
        payload = await asyncio.to_thread(
            knowledge.reindex_file, root, path, content_root=content_root
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to reindex file: {exc}"}
    payload["scope"] = scope
    return payload


@router.delete("/files")
async def delete_document_file(path: str, scope: str = "field"):
    from palimind import knowledge

    scope = _scope(scope)
    root, _content = _roots(scope)
    if root is None:
        return _missing()
    removed = await asyncio.to_thread(knowledge.remove_file, root, path)
    return {"removed": bool(removed), "path": path, "scope": scope}


# ── retrieval preview ────────────────────────────────────────────────────────


@router.get("/search")
async def search_document(
    q: str,
    scope: str = "field",
    limit: int = 8,
    doc_type: str = "",
    doc_year: int | None = None,
    entity: str = "",
    section: str = "",
    collection: str = "",
):
    from palimind import knowledge

    scope = _scope(scope)
    root, _content = _roots(scope)
    if root is None:
        return _missing()
    payload = await asyncio.to_thread(
        knowledge.search,
        root,
        q,
        limit=limit,
        doc_type=doc_type,
        doc_year=doc_year,
        entity=entity,
        section=section,
        collection=collection,
    )
    payload["scope"] = scope
    return payload


# ── settings ─────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_document_config(scope: str = "field"):
    from palimind import knowledge

    scope = _scope(scope)
    root, _content = _roots(scope)
    if root is None:
        return _missing()
    settings = await asyncio.to_thread(knowledge.read_settings, root)
    return {"scope": scope, "root": str(root), **settings}


@router.patch("/config")
async def patch_document_config(req: Request, scope: str = "field"):
    from palimind import knowledge

    try:
        body = await req.json()
    except Exception:
        body = {}
    scope = _scope(str(body.pop("scope", "") or scope))
    root, _content = _roots(scope)
    if root is None:
        return _missing()
    try:
        settings = await asyncio.to_thread(knowledge.update_settings, root, body)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to update settings: {exc}"}
    return {"status": "success", "scope": scope, "settings": settings}


# ── indexing runs ────────────────────────────────────────────────────────────


@router.post("/sync")
async def sync_document(req: Request, scope: str = "field"):
    from palimind import knowledge  # noqa: F401 - keeps the import path warm
    from palimind.jobs import runner_running
    from palimind.rag import incremental

    try:
        body = await req.json()
    except Exception:
        body = {}
    scope = _scope(str(body.get("scope") or scope))
    root, content_root = _roots(scope)
    if root is None:
        return _missing()
    wait = bool(body.get("wait", False))
    priority = int(body.get("priority") or 0)
    try:
        run = await asyncio.to_thread(
            incremental.enqueue_run,
            root,
            source_root=content_root,
            priority=priority,
        )
        # In a process without the durable worker (CLI/tests) the planned run
        # would otherwise sit in the queue forever. Only inline-process a run
        # that was actually persisted.
        if not wait and not runner_running():
            if incremental.get_run(str(run.get("run_id") or "")) is not None:
                run = await asyncio.to_thread(
                    incremental.process_run, str(run["run_id"])
                )
        elif wait and incremental.get_run(str(run.get("run_id") or "")) is not None:
            waited = await asyncio.to_thread(
                incremental.wait_for_run, str(run["run_id"]), 600.0
            )
            run = waited or run
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to start index run: {exc}"}
    return {"status": "success", "scope": scope, "run": run}


@router.get("/runs")
async def list_document_runs(scope: str = "field", limit: int = 50):
    from palimind import knowledge
    from palimind.rag import incremental

    scope = _scope(scope)
    root, _content = _roots(scope)
    if root is None:
        return {"runs": []}
    key = str(root)
    runs = await asyncio.to_thread(incremental.list_runs, max(1, min(limit, 200)))
    scoped = [run for run in runs if str(run.get("root") or "") == key]
    return {"scope": scope, "runs": scoped}


@router.get("/runs/{run_id}")
async def get_document_run(run_id: str):
    from palimind.rag import incremental

    summary = await asyncio.to_thread(incremental.get_run, run_id)
    if summary is None:
        return {"error": "index run not found"}
    return {"run": summary}


@router.get("/runs/{run_id}/events")
async def get_document_run_events(run_id: str, limit: int = 200):
    from palimind.rag import incremental

    summary = await asyncio.to_thread(incremental.get_run, run_id)
    if summary is None:
        return {"error": "index run not found"}
    events = await asyncio.to_thread(
        incremental.list_events,
        Path(str(summary.get("root") or "")),
        run_id,
        max(1, min(limit, 1000)),
    )
    return {"events": events}


@router.post("/runs/{run_id}/cancel")
async def cancel_document_run(run_id: str):
    from palimind.rag import incremental

    summary = await asyncio.to_thread(incremental.cancel_run, run_id)
    return {"run": summary} if summary else {"error": "index run not found"}


@router.post("/runs/{run_id}/resume")
async def resume_document_run(run_id: str):
    from palimind.rag import incremental

    summary = await asyncio.to_thread(incremental.resume_run, run_id)
    return {"run": summary} if summary else {"error": "index run not found"}


# ── graph ────────────────────────────────────────────────────────────────────


@router.get("/graph")
async def get_document_graph(
    scope: str = "field",
    types: str = "",
    q: str = "",
    doc_year: int | None = None,
    doc_type: str = "",
    relation: str = "",
    min_degree: int = 0,
    max_nodes: int = 400,
    max_edges: int = 1200,
    collection: str = "",
    since_year: int | None = None,
    until_year: int | None = None,
):
    from palimind import knowledge

    scope = _scope(scope)
    root, _content = _roots(scope)
    if root is None:
        return {"error": "No active field", "nodes": [], "edges": []}
    requested = [item.strip() for item in types.split(",") if item.strip()]
    try:
        payload = await asyncio.to_thread(
            knowledge.graph_payload,
            root,
            types=requested,
            q=q,
            doc_year=doc_year,
            doc_type=doc_type,
            relation=relation,
            min_degree=min_degree,
            max_nodes=max_nodes,
            max_edges=max_edges,
            collection=collection,
            since_year=since_year,
            until_year=until_year,
        )
    except Exception:  # noqa: BLE001
        return {"error": "Failed to get document graph", "nodes": [], "edges": []}
    payload["scope"] = scope
    return payload


@router.post("/graph/rebuild")
async def rebuild_document_graph(req: Request, scope: str = "field"):
    from palimind.config import load_config
    from palimind.document.graph import build_doc_graph

    try:
        body = await req.json()
    except Exception:
        body = {}
    scope = _scope(str(body.get("scope") or scope))
    root, _content = _roots(scope)
    if root is None:
        return _missing()
    try:
        cfg = await asyncio.to_thread(load_config, root)
        ollama_url = cfg.get("ollama_base_url", "http://localhost:11434")
        graph = await asyncio.to_thread(build_doc_graph, root, ollama_url)
        return {
            "status": "success",
            "scope": scope,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "indexed_files": len(graph.file_nodes),
        }
    except Exception:  # noqa: BLE001
        return {"error": "Failed to rebuild document graph"}
