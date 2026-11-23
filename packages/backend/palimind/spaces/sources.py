"""Source lifecycle for knowledge spaces.

A source is one saved item: a web page, a pasted note, or a file. Each source
owns exactly one Markdown file inside the space, so the existing crawler,
chunker, vector store and graph builder index it without special cases.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from palimind.spaces import web_source
from palimind.spaces import policy
from palimind.storage.db import (
    attach_collection,
    delete_source,
    detach_collection,
    find_source,
    get_connection,
    get_source,
    list_collections,
    list_sources,
    upsert_source,
)

logger = logging.getLogger(__name__)

WEB_STATUSES = (
    "queued",
    "fetching",
    "extracting",
    "writing",
    "ready",
    "failed",
    "blocked",
    "not_modified",
)


def _now() -> float:
    return time.time()


def _tags(value: Any) -> str:
    if isinstance(value, str):
        parts = [item.strip() for item in value.split(",") if item.strip()]
        return json.dumps(parts, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return json.dumps([str(item) for item in value if str(item).strip()], ensure_ascii=False)
    return "[]"


def _source_dir(root: Path) -> str:
    """Read the space's configured source folder, defaulting to ``sources``."""
    try:
        from palimind import spaces

        match = spaces.find_by_root(root)
        if match:
            return str(match.get("source_dir") or "sources")
    except Exception:  # noqa: BLE001
        pass
    return "sources"


def _auto_tags(row: dict, page: web_source.FetchedPage) -> str:
    current = str(row.get("tags") or "").strip()
    if current and current != "[]":
        return current
    return json.dumps(
        web_source.derive_tags(page.text, site=page.site), ensure_ascii=False
    )


def _public(row: dict) -> dict:
    out = dict(row)
    try:
        out["tags"] = json.loads(row.get("tags") or "[]")
    except (TypeError, json.JSONDecodeError):
        out["tags"] = []
    out["favorite"] = bool(row.get("favorite"))
    out["local_only"] = row.get("local_only") in (None, "", 1, "1", True)
    out["redacted"] = bool(row.get("redacted"))
    return out


# ── web ──────────────────────────────────────────────────────────────────────


def create_web_source(
    root: Path,
    url: str,
    *,
    title: str = "",
    tags: Any = None,
    note: str = "",
    parent_id: str = "",
) -> dict:
    """Create (or reuse) a queued web source row."""
    root = Path(root)
    raw = web_source.normalise_url(url)
    allowed, reason = policy.domain_allowed(root, raw)
    if not allowed:
        return {"error": reason}
    try:
        canonical = web_source.canonicalise(raw)
    except web_source.FetchError:
        canonical = raw

    conn = get_connection(root)
    try:
        existing = find_source(conn, canonical_url=canonical)
        if existing is None:
            existing = find_source(conn, canonical_url=raw)
        if existing is not None:
            return _public(existing)

        source_id = uuid.uuid4().hex[:12]
        record = {
            "id": source_id,
            "kind": "web",
            "url": raw,
            "canonical_url": canonical,
            "title": title or "",
            "status": "queued",
            "tags": _tags(tags),
            "note": note or "",
            "reading_state": "unread",
            "favorite": 0,
            "refresh_interval": 0,
            "parent_id": parent_id or "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        saved = upsert_source(conn, record)
        return _public(saved)
    finally:
        conn.close()


def ingest_web_source(
    root: Path,
    source_id: str,
    *,
    allow_private: bool = False,
) -> dict:
    """Fetch, extract, write and mark a web source ready for indexing."""
    root = Path(root)
    conn = get_connection(root)
    try:
        row = get_source(conn, source_id)
        if row is None:
            return {"error": "Source not found"}
        row["status"] = "fetching"
        row["error"] = ""
        row["updated_at"] = _now()
        upsert_source(conn, row)
    finally:
        conn.close()

    try:
        from palimind.spaces import youtube

        if youtube.is_youtube(str(row.get("url") or "")):
            return youtube.ingest_youtube(root, source_id)
        allowed, reason = policy.domain_allowed(root, str(row.get("url") or ""))
        if not allowed:
            return _fail(root, source_id, reason)
        from palimind.spaces import profiles

        profile = profiles.profile_for(root, str(row.get("url") or ""))
        space = policy._space(root) or {}
        page = web_source.fetch_page(
            row["url"],
            etag=str(row.get("etag") or ""),
            last_modified=str(row.get("last_modified") or ""),
            allow_private=allow_private,
            extra_headers=profiles.headers_for(profile),
            respect_robots=space.get("respect_robots") is not False,
        )
        allowed, reason = policy.domain_allowed(root, page.url)
        if not allowed:
            return _fail(root, source_id, reason)
        policy.check_quota(root, len(page.text) + len(page.html) + len(page.raw))
    except policy.PolicyError as exc:
        return _fail(root, source_id, str(exc))
    except web_source.FetchError as exc:
        page = None
        if web_source.fallback_eligible(str(exc)):
            page = web_source.fetch_wayback(row["url"], allow_private=allow_private)
        if page is None:
            return _fail(root, source_id, str(exc))
        if not row.get("note"):
            row["note"] = "Archived copy"
    except Exception as exc:  # noqa: BLE001 - a bad page must not crash the worker
        logger.exception("Unexpected fetch failure for %s", row.get("url"))
        return _fail(root, source_id, f"Unexpected error: {exc}")

    if page.not_modified:
        conn = get_connection(root)
        try:
            row["status"] = "ready"
            row["last_checked"] = _now()
            row["updated_at"] = _now()
            upsert_source(conn, row)
        finally:
            conn.close()
        return _public(row)

    if page.content_type == "application/pdf" and page.raw:
        try:
            policy.check_quota(root, len(page.raw))
        except policy.PolicyError as exc:
            return _fail(root, source_id, str(exc))
        rel = str(row.get("file_path") or "")
        if not rel:
            rel = str(
                Path(_source_dir(root))
                / "files"
                / f"{web_source.slug_for(page.title, page.url)}-{source_id[:8]}.pdf"
            )
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(page.raw)
        conn = get_connection(root)
        try:
            row.update(
                {
                    "kind": "file",
                    "url": page.url,
                    "canonical_url": page.canonical_url or row.get("canonical_url") or "",
                    "title": page.title or row.get("title") or target.name,
                    "site": page.site,
                    "fetched_at": _now(),
                    "etag": page.etag,
                    "last_modified": page.last_modified,
                    "content_hash": page.content_hash,
                    "file_path": rel,
                    "snapshot_path": "",
                    "status": "ready",
                    "error": "",
                    "tags": _auto_tags(row, page),
                    "last_checked": _now(),
                    "updated_at": _now(),
                }
            )
            return _public(upsert_source(conn, row))
        finally:
            conn.close()

    # A redirect or canonical link can point at a page we already saved.
    conn = get_connection(root)
    try:
        duplicate = find_source(conn, canonical_url=page.canonical_url)
        if duplicate is not None and duplicate["id"] != source_id:
            duplicate.update(
                {
                    "title": page.title or duplicate.get("title") or "",
                    "author": page.author or duplicate.get("author") or "",
                    "site": page.site or duplicate.get("site") or "",
                    "published_at": page.published_at
                    or duplicate.get("published_at")
                    or "",
                    "etag": page.etag,
                    "last_modified": page.last_modified,
                    "content_hash": page.content_hash,
                    "fetched_at": _now(),
                    "last_checked": _now(),
                    "updated_at": _now(),
                }
            )
            path, snapshot = web_source.write_source_file(
                root,
                page,
                source_id=str(duplicate["id"]),
                source_dir=_source_dir(root),
                existing_path=str(duplicate.get("file_path") or ""),
            )
            duplicate["file_path"] = path
            duplicate["snapshot_path"] = snapshot or duplicate.get("snapshot_path") or ""
            duplicate["status"] = "ready"
            duplicate["tags"] = _auto_tags(duplicate, page)
            upsert_source(conn, duplicate)
            delete_source(conn, source_id)
            return _public(duplicate)

        conn.execute("UPDATE sources SET status=? WHERE id=?", ("writing", source_id))
        conn.commit()
        old_text = ""
        if row.get("file_path"):
            try:
                old_text = (root / str(row["file_path"])).read_text("utf-8", errors="replace")
            except OSError:
                old_text = ""
        path, snapshot = web_source.write_source_file(
            root,
            page,
            source_id=source_id,
            source_dir=_source_dir(root),
            existing_path=str(row.get("file_path") or ""),
        )
        changed = web_source.summarise_change(old_text, page.text) if old_text else ""
        row.update(
            {
                "url": page.url,
                "canonical_url": page.canonical_url or row.get("canonical_url") or "",
                "title": page.title or row.get("title") or "",
                "author": page.author,
                "site": page.site,
                "published_at": page.published_at,
                "fetched_at": _now(),
                "etag": page.etag,
                "last_modified": page.last_modified,
                "content_hash": page.content_hash,
                "file_path": path,
                "snapshot_path": snapshot or "",
                "status": "ready",
                "error": "",
                "tags": _auto_tags(row, page),
                "change_summary": changed,
                "last_checked": _now(),
                "updated_at": _now(),
            }
        )
        saved = upsert_source(conn, row)
        return _public(saved)
    finally:
        conn.close()


def _fail(root: Path, source_id: str, message: str) -> dict:
    conn = get_connection(root)
    try:
        row = get_source(conn, source_id)
        if row is None:
            return {"error": message}
        row["status"] = (
            "blocked"
            if any(
                token in message.lower()
                for token in ("robots", "quota", "allow list", "deny list", "policy")
            )
            else "failed"
        )
        row["error"] = message
        row["updated_at"] = _now()
        return _public(upsert_source(conn, row))
    finally:
        conn.close()


def refresh_source(root: Path, source_id: str, *, allow_private: bool = False) -> dict:
    conn = get_connection(Path(root))
    try:
        row = get_source(conn, source_id)
    finally:
        conn.close()
    if row is None:
        return {"error": "Source not found"}
    if row.get("kind") == "feed":
        from palimind.spaces import feeds as feeds_mod

        result = feeds_mod.refresh_feed(Path(root), source_id, allow_private=allow_private)
        return result
    if row.get("kind") == "web":
        return ingest_web_source(Path(root), source_id, allow_private=allow_private)
    conn = get_connection(Path(root))
    try:
        row["last_checked"] = _now()
        return _public(upsert_source(conn, row))
    finally:
        conn.close()


# ── text ─────────────────────────────────────────────────────────────────────


def create_text_source(
    root: Path,
    text: str,
    *,
    title: str = "",
    tags: Any = None,
    note: str = "",
) -> dict:
    root = Path(root)
    body = (text or "").strip()
    if not body:
        return {"error": "Nothing to save."}
    try:
        policy.check_quota(root, len(body.encode("utf-8")))
    except policy.PolicyError as exc:
        return {"error": str(exc)}
    source_id = uuid.uuid4().hex[:12]
    heading = (title or body.splitlines()[0][:80] or "Note").strip()
    rel = (
        Path(_source_dir(root))
        / "text"
        / f"{web_source.slug_for(heading, '')}-{source_id[:8]}.md"
    )
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    saved_at = time.time()
    front = {
        "source_id": source_id,
        "source_type": "text",
        "title": heading,
        "created_at": saved_at,
    }
    lines = ["---"]
    for key, value in front.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.extend(["---", "", f"# {heading}", "", body, ""])
    target.write_text("\n".join(lines), encoding="utf-8")

    conn = get_connection(root)
    try:
        saved = upsert_source(
            conn,
            {
                "id": source_id,
                "kind": "text",
                "title": heading,
                "file_path": str(rel),
                "status": "ready",
                "tags": _tags(tags),
                "note": note or "",
                "fetched_at": saved_at,
                "created_at": saved_at,
                "updated_at": saved_at,
            },
        )
        return _public(saved)
    finally:
        conn.close()


# ── CRUD ─────────────────────────────────────────────────────────────────────


def get_space_source(root: Path, source_id: str) -> dict | None:
    conn = get_connection(Path(root))
    try:
        row = get_source(conn, source_id)
        return _public(row) if row else None
    finally:
        conn.close()


def list_space_sources(
    root: Path,
    *,
    q: str = "",
    kind: str = "",
    status: str = "",
    reading_state: str = "",
    collection_id: str = "",
    favorite: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    conn = get_connection(Path(root))
    try:
        rows, total = list_sources(
            conn,
            q=q,
            kind=kind,
            status=status,
            reading_state=reading_state,
            collection_id=collection_id,
            favorite=favorite,
            limit=limit,
            offset=offset,
        )
        return {
            "sources": [_public(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        conn.close()


def update_space_source(root: Path, source_id: str, changes: dict) -> dict | None:
    allowed = {
        "title",
        "note",
        "tags",
        "reading_state",
        "favorite",
        "refresh_interval",
        "redacted",
    }
    conn = get_connection(Path(root))
    try:
        row = get_source(conn, source_id)
        if row is None:
            return None
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == "tags":
                row["tags"] = _tags(value)
            elif key == "favorite":
                row["favorite"] = int(bool(value))
            elif key == "redacted":
                row["redacted"] = int(bool(value))
            elif key == "refresh_interval":
                row["refresh_interval"] = max(0, int(value or 0))
            elif key == "reading_state":
                value = str(value or "unread")
                if value not in ("unread", "reading", "read", "archived"):
                    value = "unread"
                row[key] = value
            else:
                row[key] = str(value or "")
        if "collection_id" in changes and changes.get("collection_id"):
            attach_collection(conn, source_id, str(changes["collection_id"]))
        row["updated_at"] = _now()
        return _public(upsert_source(conn, row))
    finally:
        conn.close()


def delete_space_source(
    root: Path,
    source_id: str,
    *,
    delete_file: bool = False,
    remove_from_index: bool = True,
) -> bool:
    root = Path(root)
    conn = get_connection(root)
    try:
        row = get_source(conn, source_id)
    finally:
        conn.close()
    if row is None:
        return False

    file_path = str(row.get("file_path") or "")
    if remove_from_index and file_path:
        try:
            from palimind import knowledge

            knowledge.remove_file(root, file_path)
        except Exception:  # noqa: BLE001 - source deletion must still proceed
            logger.exception("Could not remove %s from the index", file_path)
    if delete_file:
        for candidate in (file_path, str(row.get("snapshot_path") or "")):
            if candidate:
                try:
                    (root / candidate).unlink(missing_ok=True)
                except OSError:
                    logger.debug("Could not delete %s", candidate, exc_info=True)

    conn = get_connection(root)
    try:
        return delete_source(conn, source_id)
    finally:
        conn.close()


def related_sources(root: Path, source_id: str, limit: int = 5) -> list[dict]:
    """Find saved sources that share tags or title terms (no embeddings needed)."""
    root = Path(root)
    conn = get_connection(root)
    try:
        current = get_source(conn, source_id)
        if current is None:
            return []
        try:
            current_tags = {str(tag).lower() for tag in json.loads(current.get("tags") or "[]")}
        except (TypeError, json.JSONDecodeError):
            current_tags = set()
        words = {
            word.lower()
            for word in re.findall(
                r"[A-Za-z][A-Za-z0-9-]{3,}", str(current.get("title") or "")
            )
        }
        rows, _total = list_sources(conn, limit=500)
    finally:
        conn.close()

    scored: list[tuple[float, dict]] = []
    for row in rows:
        if row["id"] == source_id:
            continue
        try:
            tags = {str(tag).lower() for tag in json.loads(row.get("tags") or "[]")}
        except (TypeError, json.JSONDecodeError):
            tags = set()
        score = 3.0 * len(tags & current_tags)
        if words:
            title_words = {
                word.lower()
                for word in re.findall(
                    r"[A-Za-z][A-Za-z0-9-]{3,}", str(row.get("title") or "")
                )
            }
            score += float(len(words & title_words))
        if score > 0:
            scored.append((score, _public(row)))
    scored.sort(key=lambda item: (-item[0], item[1].get("title") or ""))
    return [item[1] for item in scored[: max(1, min(int(limit or 5), 20))]]


def source_content(root: Path, source_id: str) -> dict | None:
    root = Path(root)
    conn = get_connection(root)
    try:
        row = get_source(conn, source_id)
    finally:
        conn.close()
    if row is None:
        return None
    rel = str(row.get("file_path") or "")
    text = ""
    if rel and not row.get("redacted"):
        target = root / rel
        try:
            text = target.read_text("utf-8", errors="replace")
        except OSError:
            text = ""
    elif row.get("redacted"):
        text = "This source is marked redacted. Its content is hidden from readers and exports."
    return {
        "source": _public(row),
        "content": text,
        "related": related_sources(root, source_id),
    }


# ── collections ──────────────────────────────────────────────────────────────


def get_collections(root: Path) -> list[dict]:
    conn = get_connection(Path(root))
    try:
        return list_collections(conn)
    finally:
        conn.close()


def create_collection(root: Path, name: str, description: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Collection name is required.")
    collection_id = uuid.uuid4().hex[:12]
    conn = get_connection(Path(root))
    try:
        conn.execute(
            "INSERT INTO collections(id, name, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (collection_id, name[:120], (description or "")[:500], _now(), _now()),
        )
        conn.commit()
        return {
            "id": collection_id,
            "name": name[:120],
            "description": (description or "")[:500],
            "source_count": 0,
        }
    finally:
        conn.close()


def delete_collection(root: Path, collection_id: str) -> bool:
    conn = get_connection(Path(root))
    try:
        conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        conn.execute(
            "DELETE FROM source_collections WHERE collection_id = ?", (collection_id,)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def add_to_collection(root: Path, source_id: str, collection_id: str) -> bool:
    conn = get_connection(Path(root))
    try:
        if get_source(conn, source_id) is None:
            return False
        attach_collection(conn, source_id, collection_id)
        return True
    finally:
        conn.close()


def remove_from_collection(root: Path, source_id: str, collection_id: str) -> bool:
    conn = get_connection(Path(root))
    try:
        detach_collection(conn, source_id, collection_id)
        return True
    finally:
        conn.close()
