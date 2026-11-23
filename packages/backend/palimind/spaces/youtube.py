"""YouTube URLs → timestamped transcript sources.

Uses YouTube's public watch page caption metadata and timedtext endpoint. No
API key and no extra dependency: stdlib XML parsing plus httpx.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from palimind.spaces import web_source
from palimind.storage.db import get_connection, get_source, upsert_source

logger = logging.getLogger(__name__)

_ID_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=)([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{6,})"),
)


class YouTubeError(RuntimeError):
    pass


def video_id(url: str) -> str:
    for pattern in _ID_PATTERNS:
        match = pattern.search(url or "")
        if match:
            return match.group(1)
    parsed = urlparse(url or "")
    if parsed.netloc.endswith("youtube.com"):
        return (parse_qs(parsed.query).get("v") or [""])[0]
    return ""


def is_youtube(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return False
    return host in ("youtube.com", "youtu.be", "m.youtube.com")


def parse_transcript_xml(xml_text: str) -> str:
    """Turn YouTube's timedtext XML into readable timestamped paragraphs."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as exc:
        raise YouTubeError(f"Could not parse the transcript: {exc}") from exc
    lines: list[str] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() != "text":
            continue
        text = html_lib.unescape("".join(node.itertext())).strip()
        if not text:
            continue
        try:
            start = float(node.get("start") or 0)
        except ValueError:
            start = 0.0
        minutes, seconds = divmod(int(start), 60)
        hours, minutes = divmod(minutes, 60)
        stamp = (
            f"{hours}:{minutes:02d}:{seconds:02d}"
            if hours
            else f"{minutes}:{seconds:02d}"
        )
        lines.append(f"[{stamp}] {text}")
    return "\n".join(lines)


def _caption_tracks(watch_html: str) -> list[dict]:
    match = re.search(r'"captionTracks":\s*(\[.*?\])', watch_html, re.DOTALL)
    if not match:
        return []
    try:
        tracks = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    return [track for track in tracks if isinstance(track, dict) and track.get("baseUrl")]


def _fetch(url: str, *, headers: dict | None = None) -> str:
    import httpx

    response = httpx.get(
        url,
        timeout=25.0,
        follow_redirects=False,
        headers=headers or {"User-Agent": web_source.USER_AGENT, "Accept-Language": "en"},
    )
    if response.status_code >= 400:
        raise YouTubeError(f"YouTube returned HTTP {response.status_code}.")
    return response.text


def fetch_transcript(url: str) -> dict:
    vid = video_id(url)
    if not vid:
        raise YouTubeError("That is not a recognizable YouTube link.")
    watch = f"https://www.youtube.com/watch?v={vid}&hl=en"
    if not web_source._safe_url(watch, allow_private=False):
        raise YouTubeError("That address is not allowed.")
    page = _fetch(watch)
    tracks = _caption_tracks(page)
    if not tracks:
        raise YouTubeError("No captions are available for this video.")
    track = next(
        (
            item
            for item in tracks
            if str(item.get("languageCode") or "").lower().startswith("en")
        ),
        tracks[0],
    )
    base = str(track.get("baseUrl") or "").replace("\\u0026", "&")
    xml_text = _fetch(base, headers={"User-Agent": web_source.USER_AGENT})
    transcript = parse_transcript_xml(xml_text)
    if not transcript:
        raise YouTubeError("The transcript is empty.")

    title = ""
    author = ""
    try:
        meta = json.loads(
            _fetch(
                "https://www.youtube.com/oembed?"
                + urlencode({"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
            )
        )
        title = str(meta.get("title") or "")
        author = str(meta.get("author_name") or "")
    except Exception:  # noqa: BLE001 - title metadata is optional
        pass
    return {
        "id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "title": title or f"YouTube {vid}",
        "author": author,
        "transcript": transcript,
    }


def ingest_youtube(root: Path, source_id: str) -> dict:
    root = Path(root)
    conn = get_connection(root)
    try:
        row = get_source(conn, source_id)
    finally:
        conn.close()
    if row is None:
        return {"error": "Source not found"}
    if not is_youtube(str(row.get("url") or "")):
        return {"error": "Not a YouTube URL"}
    from palimind.spaces import policy

    allowed, reason = policy.domain_allowed(root, str(row["url"]))
    if not allowed:
        return _fail(root, source_id, reason)
    try:
        data = fetch_transcript(str(row["url"]))
    except YouTubeError as exc:
        return _fail(root, source_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("YouTube transcript failed")
        return _fail(root, source_id, f"Could not load the transcript: {exc}")

    try:
        policy.check_quota(root, len(data["transcript"].encode("utf-8")))
    except policy.PolicyError as exc:
        return _fail(root, source_id, str(exc))

    page = web_source.FetchedPage(
        url=data["url"],
        canonical_url=web_source.canonicalise(data["url"]),
        title=data["title"],
        author=data["author"],
        site="youtube.com",
        text=data["transcript"],
        content_hash=hashlib.sha256(data["transcript"].encode("utf-8")).hexdigest(),
    )
    rel = str(row.get("file_path") or "")
    if not rel:
        rel = str(
            Path("sources")
            / "web"
            / f"{web_source.slug_for(page.title, page.url)}-{source_id[:8]}.md"
        )
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(web_source.render_markdown(page, source_id=source_id), encoding="utf-8")

    conn = get_connection(root)
    try:
        row.update(
            {
                "kind": "video",
                "title": page.title,
                "author": page.author,
                "site": "youtube.com",
                "fetched_at": time.time(),
                "content_hash": page.content_hash,
                "file_path": rel,
                "status": "ready",
                "error": "",
                "updated_at": time.time(),
            }
        )
        return _public(upsert_source(conn, row))
    finally:
        conn.close()


def _fail(root: Path, source_id: str, message: str) -> dict:
    conn = get_connection(root)
    try:
        row = get_source(conn, source_id)
        if row is None:
            return {"error": message}
        row["status"] = "failed"
        row["error"] = message
        row["updated_at"] = time.time()
        return _public(upsert_source(conn, row))
    finally:
        conn.close()


def _public(row: dict) -> dict:
    out = dict(row)
    try:
        out["tags"] = json.loads(row.get("tags") or "[]")
    except (TypeError, json.JSONDecodeError):
        out["tags"] = []
    out["favorite"] = bool(row.get("favorite"))
    return out
