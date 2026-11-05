"""Local attachment store for multimodal chat.

Uploads are intentionally simple and local-only: the browser sends base64 JSON
(no extra multipart dependency), the bytes are content-addressed on disk under
``~/.palimind/uploads``, and metadata lives in the state database. Files are
deduplicated by SHA-256, so re-uploading the same image or PDF costs nothing.

This module also turns attachments into model inputs:

* images -> local file paths for the vision model
* text/PDF/CSV/JSON -> extracted text context
* audio/video -> a clear "not supported yet" note (transcription is a later
  phase and would require ffmpeg)
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

from palimind.security.tokens import palimind_home
from palimind.settings import UPLOAD_MAX_MB, UPLOAD_TEXT_LIMIT
from palimind.storage import state_store

_NAMESPACE = "uploads"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".xml",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".sql",
    ".log",
    ".rst",
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".opus", ".aac"}
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


def uploads_dir() -> Path:
    path = palimind_home() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    base = Path(str(name or "attachment")).name
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._")
    return cleaned[:180] or "attachment"


def _kind_for(name: str, mime: str) -> str:
    suffix = Path(name).suffix.lower()
    mime = (mime or "").lower()
    if mime.startswith("image/") or suffix in _IMAGE_SUFFIXES:
        return "image"
    if mime == "application/pdf" or suffix == ".pdf":
        return "pdf"
    if mime.startswith("audio/") or suffix in _AUDIO_SUFFIXES:
        return "audio"
    if mime.startswith("video/") or suffix in _VIDEO_SUFFIXES:
        return "video"
    if mime.startswith("text/") or suffix in _TEXT_SUFFIXES:
        return "text"
    return "file"


def _public(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        key: meta.get(key)
        for key in (
            "id",
            "name",
            "mime",
            "size",
            "kind",
            "sha256",
            "created_at",
        )
        if key in meta
    }


def save_upload(name: str, data_b64: str, mime: str = "") -> dict[str, Any]:
    """Decode, validate, store and index one attachment.

    Raises ``ValueError`` with a user-readable message for bad input.
    """
    raw_name = _safe_name(name)
    try:
        payload = base64.b64decode(str(data_b64 or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("attachment data is not valid base64") from exc
    if not payload:
        raise ValueError("attachment is empty")
    limit = max(1, int(UPLOAD_MAX_MB or 25)) * 1024 * 1024
    if len(payload) > limit:
        raise ValueError(f"attachment is too large (max {UPLOAD_MAX_MB} MB)")

    digest = hashlib.sha256(payload).hexdigest()
    suffix = Path(raw_name).suffix.lower()
    guessed = mime or mimetypes.guess_type(raw_name)[0] or "application/octet-stream"
    kind = _kind_for(raw_name, guessed)

    target_dir = uploads_dir() / digest[:2]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest}{suffix}"
    if not target.exists():
        target.write_bytes(payload)

    meta = {
        "id": digest,
        "name": raw_name,
        "mime": guessed,
        "size": len(payload),
        "kind": kind,
        "sha256": digest,
        "path": str(target),
        "created_at": time.time(),
    }
    state_store.set_json(_NAMESPACE, digest, meta)
    return _public(meta)


def get_upload(upload_id: str) -> dict[str, Any] | None:
    value = state_store.get_json(_NAMESPACE, str(upload_id or ""), default=None)
    return value if isinstance(value, dict) else None


def list_uploads(limit: int = 100) -> list[dict[str, Any]]:
    return [_public(item) for item in state_store.list_json(_NAMESPACE, limit=limit)]


def delete_upload(upload_id: str) -> bool:
    meta = get_upload(upload_id)
    if meta is None:
        return False
    path = Path(str(meta.get("path") or ""))
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass
    state_store.delete_json(_NAMESPACE, str(upload_id))
    return True


def _extract_pdf(path: Path) -> str:
    try:
        import fitz  # pymupdf

        parts: list[str] = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                text = page.get_text("text") or ""
                if text.strip():
                    parts.append(text)
        return "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001 - attachments must never crash chat
        return f"[Could not extract PDF text: {exc}]"


def _extract_text(path: Path) -> str:
    try:
        raw = path.read_bytes()[: UPLOAD_TEXT_LIMIT * 4]
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"[Could not read attachment text: {exc}]"


def resolve_attachments(ids: str | list[str] | None) -> dict[str, Any]:
    """Resolve attachment ids into model inputs.

    Returns ``{"image_paths": [...], "text_blocks": [...], "notes": [...],
    "attachments": [...]}``. Missing/unsupported attachments become notes
    rather than errors so a chat turn never dies because of one bad file.
    """
    if isinstance(ids, str):
        raw_ids = [part.strip() for part in ids.split(",") if part.strip()]
    else:
        raw_ids = [str(part).strip() for part in (ids or []) if str(part).strip()]

    image_paths: list[str] = []
    text_blocks: list[str] = []
    notes: list[str] = []
    attachments: list[dict[str, Any]] = []
    for upload_id in raw_ids[:8]:
        meta = get_upload(upload_id)
        if meta is None:
            notes.append(f"Attachment {upload_id} was not found.")
            continue
        path = Path(str(meta.get("path") or ""))
        if not path.is_file():
            notes.append(f"Attachment '{meta.get('name')}' is missing from local storage.")
            continue
        attachments.append(_public(meta))
        kind = str(meta.get("kind") or "file")
        if kind == "image":
            image_paths.append(str(path))
        elif kind == "pdf":
            text = _extract_pdf(path)
            if text.strip():
                text_blocks.append(f"[Attachment: {meta.get('name')}]\n{text[:UPLOAD_TEXT_LIMIT]}")
        elif kind == "text":
            text = _extract_text(path)
            if text.strip():
                text_blocks.append(f"[Attachment: {meta.get('name')}]\n{text[:UPLOAD_TEXT_LIMIT]}")
        elif kind in ("audio", "video"):
            notes.append(
                f"Attachment '{meta.get('name')}' is {kind}; transcription is not enabled yet."
            )
        else:
            notes.append(
                f"Attachment '{meta.get('name')}' has an unsupported type ({meta.get('mime')})."
            )
    return {
        "image_paths": image_paths,
        "text_blocks": text_blocks,
        "notes": notes,
        "attachments": attachments,
    }


def build_attachment_context(resolved: dict[str, Any]) -> str:
    blocks = [str(b) for b in resolved.get("text_blocks") or [] if str(b).strip()]
    notes = [str(n) for n in resolved.get("notes") or [] if str(n).strip()]
    if not blocks and not notes:
        return ""
    parts = ["[ATTACHMENTS]"]
    if blocks:
        parts.append("\n\n".join(blocks))
    if notes:
        parts.append("\n".join(f"- {n}" for n in notes))
    return "\n\n".join(parts)
