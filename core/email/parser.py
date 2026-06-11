"""Email parsing utilities for the PaliMind email module.

Handles:
- Multipart MIME message decomposition
- HTML → plaintext conversion (stdlib HTMLParser — no external dep)
- Character encoding normalisation
- Attachment metadata extraction (content not stored)
- Thread ID computation from References / In-Reply-To headers
"""
from __future__ import annotations

import email
import email.header
import email.message
import email.policy
import email.utils
import hashlib
import re
import time
from html.parser import HTMLParser
from typing import Any

from core.email.exceptions import EmailParseError


# ---------------------------------------------------------------------------
# HTML → plaintext
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text converter using the stdlib HTMLParser."""

    # Tags that introduce a newline before content
    _BLOCK_TAGS = {
        "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "article", "section", "header", "footer",
    }
    # Tags whose content should be skipped entirely
    _SKIP_TAGS = {"script", "style", "head", "meta", "link"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS and self._skip_depth == 0:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        # Collapse excessive whitespace
        lines = [line.rstrip() for line in raw.splitlines()]
        # Collapse multiple consecutive blank lines to one
        compressed: list[str] = []
        blank_run = 0
        for line in lines:
            if line == "":
                blank_run += 1
                if blank_run <= 1:
                    compressed.append(line)
            else:
                blank_run = 0
                compressed.append(line)
        return "\n".join(compressed).strip()


def html_to_text(html: str) -> str:
    """Convert HTML to readable plaintext using the stdlib HTMLParser."""
    if not html:
        return ""
    try:
        parser = _TextExtractor()
        parser.feed(html)
        return parser.get_text()
    except Exception as exc:
        # Fallback: strip all tags with regex (better than nothing)
        return re.sub(r"<[^>]+>", " ", html).strip()


# ---------------------------------------------------------------------------
# Thread ID
# ---------------------------------------------------------------------------

def compute_thread_id(
    references: str,
    in_reply_to: str,
    message_id: str,
) -> str:
    """Derive a stable thread identifier from the References chain.

    Strategy:
    1. Use the *first* Message-ID in the References header (root of thread).
    2. Fallback to In-Reply-To (one-level thread).
    3. Fallback to the email's own Message-ID (standalone thread).

    Returns an MD5 hash of the root message ID for a compact, indexable key.
    """
    root: str = ""
    if references:
        ids = re.findall(r"<[^>]+>", references)
        if ids:
            root = ids[0]
    if not root and in_reply_to:
        ids = re.findall(r"<[^>]+>", in_reply_to)
        if ids:
            root = ids[0]
    if not root:
        root = message_id or ""
    return hashlib.md5(root.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Header decoding
# ---------------------------------------------------------------------------

def _decode_header(value: str | None) -> str:
    """Decode RFC 2047-encoded header value to a plain Unicode string."""
    if not value:
        return ""
    try:
        parts = email.header.decode_header(value)
        decoded: list[str] = []
        for part, charset in parts:
            if isinstance(part, bytes):
                try:
                    decoded.append(part.decode(charset or "utf-8", errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    decoded.append(part.decode("utf-8", errors="replace"))
            else:
                decoded.append(str(part))
        return "".join(decoded)
    except Exception:
        return str(value)


def _parse_address(raw: str) -> tuple[str, str]:
    """Return (display_name, email_address) from a raw address header."""
    if not raw:
        return "", ""
    try:
        name, addr = email.utils.parseaddr(raw)
        return _decode_header(name), addr.lower()
    except Exception:
        return "", raw.strip()


def _parse_address_list(raw: str) -> str:
    """Return a comma-separated list of email addresses."""
    if not raw:
        return ""
    try:
        pairs = email.utils.getaddresses([raw])
        return ", ".join(addr for _, addr in pairs if addr)
    except Exception:
        return raw


def _parse_date(raw: str | None) -> float:
    """Parse an RFC 2822 date string to a Unix timestamp."""
    if not raw:
        return time.time()
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
        return parsed.timestamp()
    except Exception:
        return time.time()


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_message(msg: email.message.EmailMessage) -> dict[str, Any]:
    """Parse a raw EmailMessage into a structured dict.

    Returns a dict with keys matching the emails table schema.
    'attachments' is a list of dicts with filename/content_type/size_bytes/content_id.
    """
    try:
        # ---- Headers ----
        raw_from = _decode_header(msg.get("From", ""))
        sender_name, sender = _parse_address(raw_from)
        raw_to = _decode_header(msg.get("To", ""))
        raw_cc = _decode_header(msg.get("Cc", ""))
        subject = _decode_header(msg.get("Subject", "")) or "(no subject)"
        message_id = (msg.get("Message-ID") or "").strip()
        in_reply_to = (msg.get("In-Reply-To") or "").strip()
        references = (msg.get("References") or "").strip()
        date = _parse_date(msg.get("Date"))

        recipients = _parse_address_list(raw_to)
        cc = _parse_address_list(raw_cc)
        thread_id = compute_thread_id(references, in_reply_to, message_id)

        # ---- Body ----
        body_text = ""
        body_html = ""
        attachments: list[dict] = []

        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                cd = str(part.get("Content-Disposition") or "")
                is_attachment = "attachment" in cd.lower()
                is_inline_non_text = "inline" in cd.lower() and not ct.startswith("text/")

                if is_attachment or is_inline_non_text:
                    filename = _decode_header(
                        part.get_filename() or part.get_param("name") or ""
                    ) or "unnamed"
                    content_id = (part.get("Content-ID") or "").strip("<>")
                    payload = part.get_payload(decode=True) or b""
                    attachments.append(
                        {
                            "filename": filename,
                            "content_type": ct,
                            "size_bytes": len(payload),
                            "content_id": content_id,
                        }
                    )
                elif ct == "text/plain" and not body_text:
                    body_text = _decode_part(part)
                elif ct == "text/html" and not body_html:
                    body_html = _decode_part(part)
        else:
            ct = msg.get_content_type()
            if ct == "text/html":
                body_html = _decode_part(msg)
            else:
                body_text = _decode_part(msg)

        # Prefer plaintext; convert HTML if no plaintext available
        if not body_text and body_html:
            body_text = html_to_text(body_html)

        has_attachments = bool(attachments)

        return {
            "message_id": message_id,
            "in_reply_to": in_reply_to,
            "references": references,
            "thread_id": thread_id,
            "subject": subject,
            "sender": sender,
            "sender_name": sender_name,
            "recipients": recipients,
            "cc": cc,
            "date": date,
            "body_html": body_html,
            "body_text": body_text,
            "has_attachments": has_attachments,
            "attachments": attachments,
        }
    except Exception as exc:
        raise EmailParseError(f"Failed to parse email message: {exc}") from exc


def _decode_part(part: email.message.EmailMessage) -> str:
    """Decode a MIME part payload to a Unicode string."""
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return payload.decode("utf-8", errors="replace")
    except Exception:
        return ""
