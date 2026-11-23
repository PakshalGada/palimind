"""Per-domain capture profiles (headers, cookies, user agent).

Profiles let a user save pages that require a session cookie or an API token
without sending those secrets to any third party. They are stored in the
space's local SQLite database and only attached to matching hosts.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from palimind.storage.db import get_connection

_COLUMNS = ("id", "name", "domain", "headers", "cookies", "user_agent", "created_at", "updated_at")


def _row_dict(row) -> dict:
    return {name: row[index] for index, name in enumerate(_COLUMNS)}


def _public(row: dict) -> dict:
    out = dict(row)
    try:
        out["headers"] = json.loads(row.get("headers") or "{}")
    except (TypeError, json.JSONDecodeError):
        out["headers"] = {}
    return out


def _normalise_domain(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        raise ValueError("Profile domain is required.")
    if "://" in raw:
        raw = urlparse(raw).netloc
    raw = raw.split("/")[0].split(":")[0].removeprefix("www.").strip(".")
    if not raw or "." not in raw:
        raise ValueError("Use a domain such as example.com.")
    return raw


def list_profiles(root: Path) -> list[dict]:
    conn = get_connection(Path(root))
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM capture_profiles ORDER BY domain, name"
        ).fetchall()
    finally:
        conn.close()
    return [_public(_row_dict(row)) for row in rows]


def upsert_profile(root: Path, data: dict) -> dict:
    domain = _normalise_domain(str(data.get("domain") or ""))
    name = str(data.get("name") or domain).strip()[:120]
    headers = data.get("headers") or {}
    if isinstance(headers, str):
        parsed: dict[str, str] = {}
        for line in headers.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                parsed[key.strip()] = value.strip()
        headers = parsed
    if not isinstance(headers, dict):
        raise ValueError("headers must be an object or 'Name: value' lines.")
    clean_headers = {
        str(key).strip(): str(value)
        for key, value in headers.items()
        if str(key).strip() and "\n" not in str(key) and "\n" not in str(value)
    }
    cookies = str(data.get("cookies") or "")
    if cookies.lower().startswith("cookie:"):
        cookies = cookies.split(":", 1)[1].strip()
    user_agent = str(data.get("user_agent") or "")
    profile_id = str(data.get("id") or "") or uuid.uuid4().hex[:12]
    now = time.time()
    conn = get_connection(Path(root))
    try:
        conn.execute(
            f"""
            INSERT INTO capture_profiles ({", ".join(_COLUMNS)})
            VALUES ({", ".join("?" * len(_COLUMNS))})
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, domain=excluded.domain,
                headers=excluded.headers, cookies=excluded.cookies,
                user_agent=excluded.user_agent, updated_at=excluded.updated_at
            """,
            (
                profile_id,
                name,
                domain,
                json.dumps(clean_headers),
                cookies,
                user_agent,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM capture_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
    finally:
        conn.close()
    return _public(_row_dict(row))


def delete_profile(root: Path, profile_id: str) -> bool:
    conn = get_connection(Path(root))
    try:
        cur = conn.execute("DELETE FROM capture_profiles WHERE id = ?", (profile_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def profile_for(root: Path, url: str) -> dict | None:
    try:
        host = urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
    except Exception:
        return None
    if not host:
        return None
    best: dict | None = None
    best_len = -1
    for profile in list_profiles(root):
        domain = str(profile.get("domain") or "")
        if host == domain or host.endswith("." + domain):
            if len(domain) > best_len:
                best = profile
                best_len = len(domain)
    return best


def headers_for(profile: dict | None) -> dict[str, str]:
    if not profile:
        return {}
    headers = {str(k): str(v) for k, v in (profile.get("headers") or {}).items()}
    if profile.get("cookies"):
        headers["Cookie"] = str(profile["cookies"])
    if profile.get("user_agent"):
        headers["User-Agent"] = str(profile["user_agent"])
    return headers
