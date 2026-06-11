"""Email-specific exceptions for PaliMind.

All exceptions inherit from PalimindError so the top-level CLI can catch them.
Email-specific subclasses let individual layers raise precise errors.
"""
from __future__ import annotations

from core.exceptions import PalimindError


class EmailError(PalimindError):
    """Base exception for all email-module failures."""


class EmailConnectionError(EmailError):
    """Raised when IMAP or SMTP connection cannot be established."""


class EmailAuthError(EmailError):
    """Raised when IMAP or SMTP authentication fails."""


class EmailSyncError(EmailError):
    """Raised when an error occurs during email synchronisation."""


class EmailSendError(EmailError):
    """Raised when sending an email fails."""


class EmailNotFoundError(EmailError):
    """Raised when a requested email does not exist in the local store."""


class EmailCryptoError(EmailError):
    """Raised when credential encryption or decryption fails."""


class EmailParseError(EmailError):
    """Raised when a raw MIME message cannot be parsed."""


class EmailAccountExistsError(EmailError):
    """Raised when an account with the given label already exists."""


class EmailAccountNotFoundError(EmailError):
    """Raised when no account matches the given label or ID."""
