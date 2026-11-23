"""Knowledge space lifecycle endpoints (create / link / rename / delete)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(prefix="/api/spaces", tags=["knowledge"])


@router.get("")
async def list_spaces():
    from palimind import spaces

    active = spaces.ensure_active_space()
    return {
        "spaces": spaces.list_spaces(),
        "active_space_id": (active or {}).get("id"),
        "default_parent": str(spaces.default_parent()),
    }


@router.post("")
async def create_space(req: Request):
    from palimind import spaces

    try:
        body = await req.json()
    except Exception:
        body = {}
    name = str(body.get("name") or "").strip()
    mode = str(body.get("mode") or "create").strip().lower()
    try:
        record = await asyncio.to_thread(
            spaces.create_space,
            name,
            parent_dir=str(body.get("parent_dir") or "") or None,
            root=str(body.get("root") or "") or None,
            mode=mode,
            folder_name=str(body.get("folder_name") or "") or None,
            icon=str(body.get("icon") or "book"),
        )
    except spaces.SpaceError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not create the space: {exc}"}

    if bool(body.get("index", True)):
        # Index in the background so the dialog closes immediately.
        try:
            from palimind import knowledge

            asyncio.create_task(
                asyncio.to_thread(
                    knowledge.run_index,
                    Path(str(record["root"])),
                    wait=True,
                )
            )
        except Exception:  # noqa: BLE001 - creation succeeded; indexing can be retried
            pass
    return {"status": "success", "space": record, "active_space_id": record["id"]}


@router.get("/{space_id}")
async def get_space(space_id: str):
    from palimind import spaces

    record = spaces.get_space(space_id)
    if record is None:
        return {"error": "Space not found"}
    return {"space": record}


@router.patch("/{space_id}")
async def patch_space(space_id: str, req: Request):
    from palimind import spaces

    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return {"error": "Invalid payload"}
    try:
        record = await asyncio.to_thread(spaces.update_space, space_id, body)
    except spaces.SpaceError as exc:
        return {"error": str(exc)}
    if record is None:
        return {"error": "Space not found"}
    return {"status": "success", "space": record}


@router.delete("/{space_id}")
async def remove_space(space_id: str, delete_files: bool = False):
    from palimind import spaces

    try:
        removed = await asyncio.to_thread(
            spaces.delete_space, space_id, delete_files=delete_files
        )
    except spaces.SpaceError as exc:
        return {"error": str(exc)}
    if not removed:
        return {"error": "Space not found"}
    return {"status": "success", "removed": True}


@router.post("/{space_id}/activate")
async def activate_space(space_id: str):
    from palimind import spaces

    try:
        record = await asyncio.to_thread(spaces.set_active_space, space_id)
    except spaces.SpaceError as exc:
        return {"error": str(exc)}
    if record is None:
        return {"error": "Space not found"}
    return {"status": "success", "space": record, "active_space_id": record["id"]}


@router.post("/migrate")
async def migrate_spaces():
    from palimind import api_server as server
    from palimind import spaces

    created = await asyncio.to_thread(
        spaces.migrate_legacy_fields, list(server.state.fields)
    )
    active = spaces.ensure_active_space()
    return {
        "status": "success",
        "created": created,
        "spaces": spaces.list_spaces(),
        "active_space_id": (active or {}).get("id"),
    }


# ── sources ──────────────────────────────────────────────────────────────────


def _space_root(space_id: str) -> Path | None:
    from palimind import spaces

    return spaces.resolve_space(space_id)


def _schedule_ingest(root: Path, source_id: str) -> None:
    """Run ingestion in the durable worker, or inline in CLI/test processes."""
    try:
        from palimind.jobs import enqueue, runner_running

        if runner_running():
            enqueue(
                "web_ingest",
                str(root),
                {"source_id": source_id, "root": str(root)},
                idempotency_key=f"web_ingest:{source_id}",
            )
            return
    except Exception:  # noqa: BLE001 - fall back to the local thread
        pass
    from palimind import knowledge
    from palimind.spaces import sources as sources_mod

    def _work() -> None:
        sources_mod.ingest_web_source(root, source_id)
        try:
            knowledge.run_index(root, wait=False)
        except Exception:  # noqa: BLE001 - the next sync will retry
            pass

    asyncio.create_task(asyncio.to_thread(_work))


@router.post("/{space_id}/crawl")
async def crawl_space_site(space_id: str, req: Request):
    from palimind.spaces import crawl as crawl_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    url = str(body.get("url") or "").strip()
    if not url:
        return {"error": "Paste a page URL to crawl."}
    try:
        result = await asyncio.to_thread(
            crawl_mod.crawl_site,
            root,
            url,
            max_pages=int(body.get("max_pages") or 10),
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not crawl that site: {exc}"}
    return result


@router.post("/{space_id}/feeds")
async def add_space_feed(space_id: str, req: Request):
    from palimind.spaces import feeds as feeds_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    url = str(body.get("url") or "").strip()
    if not url:
        return {"error": "Paste a feed URL."}
    try:
        result = await asyncio.to_thread(
            feeds_mod.add_feed,
            root,
            url,
            limit=int(body.get("limit") or 30),
        )
    except feeds_mod.FeedError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not read the feed: {exc}"}
    for item in result.get("items") or []:
        if item.get("status") in ("queued", "failed", "blocked"):
            _schedule_ingest(root, str(item["id"]))
    return {
        "status": "success",
        "feed": result.get("feed"),
        "items": result.get("items") or [],
    }


@router.post("/{space_id}/sources")
async def add_space_sources(space_id: str, req: Request):
    from palimind import knowledge
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    try:
        body = await req.json()
    except Exception:
        body = {}

    text = str(body.get("text") or "").strip()
    if text:
        record = await asyncio.to_thread(
            sources_mod.create_text_source,
            root,
            text,
            title=str(body.get("title") or ""),
            tags=body.get("tags"),
            note=str(body.get("note") or ""),
        )
        if record.get("error"):
            return {"error": record["error"]}
        asyncio.create_task(asyncio.to_thread(knowledge.run_index, root, wait=False))
        return {"status": "success", "sources": [record]}

    raw_urls = body.get("urls")
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    urls = list(raw_urls or [])
    if body.get("url"):
        urls.insert(0, str(body["url"]))
    if not urls:
        return {"error": "Paste a link or some text to save."}

    created = []
    errors = []
    for raw in urls[:50]:
        url = str(raw or "").strip()
        if not url:
            continue
        try:
            record = await asyncio.to_thread(
                sources_mod.create_web_source,
                root,
                url,
                title=str(body.get("title") or ""),
                tags=body.get("tags"),
                note=str(body.get("note") or ""),
            )
            created.append(record)
            if record.get("status") in ("queued", "failed", "blocked"):
                _schedule_ingest(root, str(record["id"]))
        except Exception as exc:  # noqa: BLE001
            errors.append({"url": url, "error": str(exc)})
    return {"status": "success", "sources": created, "errors": errors}


@router.get("/{space_id}/sources")
async def list_space_sources(
    space_id: str,
    q: str = "",
    kind: str = "",
    status: str = "",
    reading_state: str = "",
    collection: str = "",
    favorite: bool | None = None,
    limit: int = 200,
    offset: int = 0,
):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    payload = await asyncio.to_thread(
        sources_mod.list_space_sources,
        root,
        q=q,
        kind=kind,
        status=status,
        reading_state=reading_state,
        collection_id=collection,
        favorite=1 if favorite else (0 if favorite is False else None),
        limit=limit,
        offset=offset,
    )
    return payload


@router.get("/{space_id}/sources/{source_id}")
async def get_space_source(space_id: str, source_id: str):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    record = await asyncio.to_thread(sources_mod.get_space_source, root, source_id)
    if record is None:
        return {"error": "Source not found"}
    return {"source": record}


@router.get("/{space_id}/sources/{source_id}/content")
async def get_space_source_content(space_id: str, source_id: str):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    payload = await asyncio.to_thread(sources_mod.source_content, root, source_id)
    if payload is None:
        return {"error": "Source not found"}
    return payload


@router.patch("/{space_id}/sources/{source_id}")
async def patch_space_source(space_id: str, source_id: str, req: Request):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return {"error": "Invalid payload"}
    record = await asyncio.to_thread(
        sources_mod.update_space_source, root, source_id, body
    )
    if record is None:
        return {"error": "Source not found"}
    return {"status": "success", "source": record}


@router.delete("/{space_id}/sources/{source_id}")
async def delete_space_source(
    space_id: str,
    source_id: str,
    delete_file: bool = False,
    keep_index: bool = False,
):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    removed = await asyncio.to_thread(
        sources_mod.delete_space_source,
        root,
        source_id,
        delete_file=delete_file,
        remove_from_index=not keep_index,
    )
    if not removed:
        return {"error": "Source not found"}
    return {"status": "success", "removed": True}


@router.post("/{space_id}/sources/{source_id}/refresh")
async def refresh_space_source(space_id: str, source_id: str):
    from palimind.jobs import enqueue, runner_running
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    record = await asyncio.to_thread(sources_mod.get_space_source, root, source_id)
    if record is None:
        return {"error": "Source not found"}
    if record.get("kind") == "web":
        try:
            if runner_running():
                job = enqueue(
                    "web_ingest",
                    str(root),
                    {"source_id": source_id, "root": str(root), "refresh": True},
                    idempotency_key=f"web_ingest:{source_id}:{int(__import__('time').time())}",
                )
                return {"status": "queued", "job_id": job.get("id")}
        except Exception:  # noqa: BLE001
            pass
    updated = await asyncio.to_thread(sources_mod.refresh_source, root, source_id)
    for item in updated.get("items") or []:
        if item.get("status") in ("queued", "failed", "blocked"):
            _schedule_ingest(root, str(item["id"]))
    if updated.get("items"):
        window = {"status": "success", "source": updated.get("feed"), "items": updated["items"]}
        return window
    return {"status": "success", "source": updated}


@router.post("/{space_id}/sources/{source_id}/reindex")
async def reindex_space_source(space_id: str, source_id: str):
    from palimind import knowledge
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    record = await asyncio.to_thread(sources_mod.get_space_source, root, source_id)
    if record is None:
        return {"error": "Source not found"}
    file_path = str(record.get("file_path") or "")
    if not file_path:
        return {"error": "This source has no indexed file yet."}
    result = await asyncio.to_thread(knowledge.reindex_file, root, file_path)
    return {"status": "success", "result": result}


# ── collections ──────────────────────────────────────────────────────────────


@router.get("/{space_id}/collections")
async def list_space_collections(space_id: str):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    return {"collections": await asyncio.to_thread(sources_mod.get_collections, root)}


@router.post("/{space_id}/collections")
async def create_space_collection(space_id: str, req: Request):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        record = await asyncio.to_thread(
            sources_mod.create_collection,
            root,
            str(body.get("name") or ""),
            str(body.get("description") or ""),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"status": "success", "collection": record}


@router.delete("/{space_id}/collections/{collection_id}")
async def delete_space_collection(space_id: str, collection_id: str):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    await asyncio.to_thread(sources_mod.delete_collection, root, collection_id)
    return {"status": "success", "removed": True}


@router.post("/{space_id}/sources/{source_id}/collections")
async def add_source_collection(space_id: str, source_id: str, req: Request):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    collection_id = str(body.get("collection_id") or "")
    if not collection_id:
        return {"error": "collection_id is required"}
    ok = await asyncio.to_thread(
        sources_mod.add_to_collection, root, source_id, collection_id
    )
    return {"status": "success" if ok else "error"}


@router.delete("/{space_id}/sources/{source_id}/collections/{collection_id}")
async def remove_source_collection(space_id: str, source_id: str, collection_id: str):
    from palimind.spaces import sources as sources_mod

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    await asyncio.to_thread(
        sources_mod.remove_from_collection, root, source_id, collection_id
    )
    return {"status": "success"}


# ── export ───────────────────────────────────────────────────────────────────


@router.get("/{space_id}/export")
async def export_space(space_id: str):
    """Download the space as an Obsidian-friendly Markdown vault."""
    import io
    import json
    import zipfile

    from palimind import spaces

    record = spaces.get_space(space_id)
    root = _space_root(space_id)
    if record is None or root is None:
        return {"error": "Space not found"}

    def _build() -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*.md")):
                rel = path.relative_to(root)
                if rel.parts and rel.parts[0] == ".palimind":
                    continue
                archive.write(path, str(rel))
            graph_file = root / ".palimind" / "doc_graph.json"
            if graph_file.is_file():
                archive.write(graph_file, "graph.json")
            manifest = {
                "space": record,
                "exported_at": __import__("time").time(),
                "files": [
                    str(path.relative_to(root))
                    for path in sorted(root.rglob("*.md"))
                    if not (path.relative_to(root).parts and path.relative_to(root).parts[0] == ".palimind")
                ],
            }
            archive.writestr("space.json", json.dumps(manifest, indent=2))
        return buffer.getvalue()

    payload = await asyncio.to_thread(_build)
    filename = f"{record.get('slug') or 'knowledge'}-export.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{space_id}/graph/export")
async def export_space_graph(space_id: str, format: str = "json"):
    """Export the graph as JSON or GraphML for external tools."""
    import json
    from xml.sax.saxutils import escape

    from palimind import knowledge

    root = _space_root(space_id)
    if root is None:
        return {"error": "Space not found"}
    payload = await asyncio.to_thread(knowledge.graph_payload, root, max_nodes=0, max_edges=0)
    if (format or "json").lower() == "graphml":
        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
            '<key id="label" for="node" attr.name="label" attr.type="string"/>',
            '<key id="type" for="node" attr.name="type" attr.type="string"/>',
            '<key id="relation" for="edge" attr.name="relation" attr.type="string"/>',
            '<graph edgedefault="undirected">',
        ]
        for node in nodes:
            lines.append(
                f'<node id="{escape(str(node.get("id")))}">'
                f'<data key="label">{escape(str(node.get("label") or ""))}</data>'
                f'<data key="type">{escape(str(node.get("type") or ""))}</data>'
                "</node>"
            )
        for edge in edges:
            lines.append(
                f'<edge source="{escape(str(edge.get("source")))}" '
                f'target="{escape(str(edge.get("target")))}">'
                f'<data key="relation">{escape(str(edge.get("relation") or ""))}</data>'
                "</edge>"
            )
        lines.append("</graph></graphml>")
        return Response(
            content="\n".join(lines),
            media_type="application/graphml+xml",
            headers={
                "Content-Disposition": 'attachment; filename="knowledge-graph.graphml"'
            },
        )
    return Response(
        content=json.dumps(payload, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="knowledge-graph.json"'},
    )
