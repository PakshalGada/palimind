"""Data models for the PaliMind email module.

All dataclasses use frozen=True to match the convention in core/models.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Account:
    """Represents a configured IMAP/SMTP email account."""

    id: int
    label: str
    email_address: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    username: str
    password_enc: str  # Fernet-encrypted — never expose plaintext
    use_ssl: bool
    created_at: float
    updated_at: float
    last_sync_at: Optional[float] = None  # Joined from sync_state


@dataclass(frozen=True)
class Attachment:
    """Metadata for a single email attachment (content is NOT stored)."""

    id: int
    email_id: int
    filename: str
    content_type: str
    size_bytes: int
    content_id: str


@dataclass(frozen=True)
class Email:
    """Represents a single email message stored locally."""

    id: int
    account_id: int
    folder: str
    uid: Optional[int]
    message_id: str
    in_reply_to: str
    references: str
    thread_id: str
    subject: str
    sender: str
    sender_name: str
    recipients: str
    cc: str
    date: float
    body_html: str
    body_text: str
    has_attachments: bool
    summary: str
    tags: str
    priority: int
    spam_score: int
    is_read: bool
    is_sent: bool
    fetched_at: float
    attachments: tuple[Attachment, ...] = ()

    @property
    def tag_list(self) -> list[str]:
        """Return tags as a list, filtering empty strings."""
        return [t.strip() for t in self.tags.split(",") if t.strip()]


@dataclass(frozen=True)
class SyncResult:
    """Result of a single account+folder sync operation."""

    account_label: str
    folder: str
    fetched: int
    stored: int
    duplicates: int
    parse_errors: int
    ai_processed: int


@dataclass(frozen=True)
class SendResult:
    """Result of a send (compose or reply) operation."""

    message_id: str
    recipient: str
    subject: str
    smtp_host: str


@dataclass(frozen=True)
class SearchResult:
    """A single full-text search hit."""

    email_id: int
    score: float
    subject: str
    sender: str
    snippet: str
    date: float
    is_read: bool
