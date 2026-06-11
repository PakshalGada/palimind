"""Public re-exports for the PaliMind email module.

Import from here, not from submodules directly, to keep the public surface stable.
"""
from __future__ import annotations

from core.email.exceptions import (
    EmailAccountExistsError,
    EmailAccountNotFoundError,
    EmailAuthError,
    EmailConnectionError,
    EmailCryptoError,
    EmailError,
    EmailNotFoundError,
    EmailParseError,
    EmailSendError,
    EmailSyncError,
)
from core.email.models import Account, Attachment, Email, SearchResult, SendResult, SyncResult

__all__ = [
    # Exceptions
    "EmailError",
    "EmailConnectionError",
    "EmailAuthError",
    "EmailSyncError",
    "EmailSendError",
    "EmailNotFoundError",
    "EmailCryptoError",
    "EmailParseError",
    "EmailAccountExistsError",
    "EmailAccountNotFoundError",
    # Models
    "Account",
    "Email",
    "Attachment",
    "SyncResult",
    "SendResult",
    "SearchResult",
]
