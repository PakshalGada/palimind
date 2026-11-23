"""External capture endpoints for a browser extension, bookmarklet or share sheet.

The global auth middleware accepts the bearer token from the query string, so a
bookmarklet or mobile share target can call these without custom headers. The
endpoint saves into the active space unless ``space_id`` is supplied.
"""

from __future__ import annotations

import asyncio
from html import escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/capture", tags=["capture"])


def _target_root(space_id: str = "") -> tuple[Path | None, dict | None]:
    from palimind import api_server as server
    from palimind import spaces

    if space_id:
        record = spaces.get_space(space_id)
        return (Path(str(record["root"])) if record else None), record
    record = spaces.ensure_active_space()
    if record:
        return Path(str(record["root"])), record
    return server.state.active_field, None


def _save(url: str, title: str, space_id: str = "") -> dict:
    from palimind.spaces import ingest as ingest_mod
    from palimind.spaces import sources as sources_mod

    root, record = _target_root(space_id)
    if root is None:
        return {"error": "No knowledge space selected."}
    try:
        source = sources_mod.create_web_source(root, url, title=title)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    if source.get("error"):
        return source
    if source.get("status") in ("queued", "failed", "blocked"):
        ingest_mod.schedule_ingest(root, str(source["id"]))
    return {
        "status": "success",
        "source": source,
        "space_id": (record or {}).get("id"),
        "space_name": (record or {}).get("name"),
    }


@router.post("/note")
async def capture_note(req: Request):
    from palimind import knowledge
    from palimind.spaces import sources as sources_mod

    try:
        body = await req.json()
    except Exception:
        body = {}
    text = str(body.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}
    root, record = _target_root(str(body.get("space_id") or ""))
    if root is None:
        return {"error": "No knowledge space selected."}
    result = await asyncio.to_thread(
        sources_mod.create_text_source,
        root,
        text,
        title=str(body.get("title") or ""),
        tags=body.get("tags"),
    )
    if result.get("error"):
        return result
    asyncio.create_task(asyncio.to_thread(knowledge.run_index, root, wait=False))
    return {
        "status": "success",
        "source": result,
        "space_id": (record or {}).get("id"),
        "space_name": (record or {}).get("name"),
    }


@router.post("/sources")
async def capture_sources(req: Request):
    from palimind import knowledge
    from palimind.spaces import sources as sources_mod

    try:
        body = await req.json()
    except Exception:
        body = {}
    urls = body.get("urls")
    if isinstance(urls, str):
        urls = [urls]
    urls = [str(item).strip() for item in (urls or []) if str(item).strip()]
    raw_items = body.get("items")
    items_in = [item for item in raw_items or [] if isinstance(item, dict) and item.get("url")]
    if not urls and not items_in:
        return {"error": "urls is required"}
    root, record = _target_root(str(body.get("space_id") or ""))
    if root is None:
        return {"error": "No knowledge space selected."}
    created = []
    errors = []
    ids = []
    targets = items_in or [{"url": url} for url in urls]
    for item in targets[:50]:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        result = await asyncio.to_thread(
            sources_mod.create_web_source,
            root,
            url,
            title=str(item.get("title") or body.get("title") or ""),
            tags=body.get("tags"),
        )
        if result.get("error"):
            errors.append({"url": url, "error": result["error"]})
            continue
        created.append(result)
        if result.get("status") in ("queued", "failed", "blocked"):
            ids.append(str(result["id"]))
    if ids:
        from palimind.spaces import ingest as ingest_mod

        ingest_mod.schedule_ingest(root, ids)
    else:
        asyncio.create_task(asyncio.to_thread(knowledge.run_index, root, wait=False))
    return {
        "status": "success",
        "sources": created,
        "errors": errors,
        "space_id": (record or {}).get("id"),
        "space_name": (record or {}).get("name"),
    }


@router.post("/link")
async def capture_link(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    url = str(body.get("url") or "").strip()
    if not url:
        return {"error": "url is required"}
    return _save(url, str(body.get("title") or ""), str(body.get("space_id") or ""))


@router.get("/link")
async def capture_link_shared(url: str, title: str = "", space_id: str = "", format: str = "html"):
    """Share-sheet/bookmarklet target: save immediately, then show a receipt."""
    result = _save(url, title, space_id)
    if format == "json":
        return result
    if result.get("error"):
        return HTMLResponse(
            f"<html><body style='font-family:system-ui;padding:32px'>"
            f"<h2>Could not save</h2><p>{escape(result['error'])}</p></body></html>",
            status_code=400,
        )
    source = result.get("source") or {}
    return HTMLResponse(
        "<html><body style='font-family:system-ui;padding:32px'>"
        "<h2>Saved to PaliMind</h2>"
        f"<p>{escape(str(source.get('title') or url))}</p>"
        f"<p style='color:#666'>Space: {escape(str(result.get('space_name') or 'Knowledge'))}</p>"
        "</body></html>"
    )
