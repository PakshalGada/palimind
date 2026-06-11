"""Public re-exports for the PaliMind email module.

Import from here, not from submodules directly, to keep the public surface stable.

Phase 2: cli_p2 and cli_p2b are imported here to register new CLI commands
onto the shared Typer app (core.email.cli.app) without modifying Phase 1 code.
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

# Phase 2: register new CLI commands by importing the modules.
# The import side-effect attaches @app.command decorators to the shared app.
import core.email.cli_p2   # noqa: F401  — watch, ask, needs-reply, today, contacts, remind, reminders
import core.email.cli_p2b  # noqa: F401  — newsletters, spam-*, stats

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
