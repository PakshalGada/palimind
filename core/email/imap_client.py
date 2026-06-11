"""IMAP client wrapper for the PaliMind email module.

Uses stdlib imaplib — no external dependencies.

Usage:
    with IMAPClient(host, port, username, password, use_ssl=True) as client:
        messages = client.fetch_messages("INBOX", uid_start=100, limit=50)
"""
from __future__ import annotations

import email
import email.message
import imaplib
import re
import socket
from typing import Iterator

from core.email.exceptions import EmailAuthError, EmailConnectionError, EmailSyncError

_TIMEOUT_SECONDS = 30


class IMAPClient:
    """Context-managed IMAP client wrapping imaplib."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self._conn: imaplib.IMAP4 | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "IMAPClient":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open IMAP connection and authenticate."""
        try:
            if self._use_ssl:
                self._conn = imaplib.IMAP4_SSL(
                    self._host, self._port, timeout=_TIMEOUT_SECONDS
                )
            else:
                self._conn = imaplib.IMAP4(self._host, self._port)
                # STARTTLS
                self._conn.starttls()
        except (socket.timeout, TimeoutError) as exc:
            raise EmailConnectionError(
                f"Connection to {self._host}:{self._port} timed out."
            ) from exc
        except (ConnectionRefusedError, OSError) as exc:
            raise EmailConnectionError(
                f"Cannot connect to {self._host}:{self._port} — {exc}"
            ) from exc
        except Exception as exc:
            raise EmailConnectionError(
                f"Failed to connect to {self._host}:{self._port}: {exc}"
            ) from exc

        try:
            self._conn.login(self._username, self._password)
        except imaplib.IMAP4.error as exc:
            err_str = str(exc).lower()
            if "authentication" in err_str or "invalid" in err_str or "auth" in err_str:
                raise EmailAuthError(
                    f"Authentication failed for {self._username} on {self._host}."
                ) from exc
            raise EmailConnectionError(f"IMAP login error: {exc}") from exc

    def disconnect(self) -> None:
        """Close IMAP connection gracefully."""
        if self._conn is not None:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def _require_conn(self) -> imaplib.IMAP4:
        if self._conn is None:
            raise EmailConnectionError("Not connected — call connect() first.")
        return self._conn

    # ------------------------------------------------------------------
    # Folder listing
    # ------------------------------------------------------------------

    def list_folders(self) -> list[str]:
        """Return a list of IMAP folder names."""
        conn = self._require_conn()
        try:
            status, data = conn.list()
            if status != "OK":
                return ["INBOX"]
            folders: list[str] = []
            for item in data:
                if isinstance(item, bytes):
                    # Pattern: (\HasNoChildren) "/" "Folder Name"
                    m = re.search(r'"([^"]+)"\s*$|(\S+)\s*$', item.decode(errors="replace"))
                    if m:
                        folders.append((m.group(1) or m.group(2)).strip('"'))
            return folders or ["INBOX"]
        except imaplib.IMAP4.error as exc:
            raise EmailSyncError(f"Failed to list folders: {exc}") from exc

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def fetch_messages(
        self,
        folder: str,
        uid_start: int = 0,
        limit: int = 50,
    ) -> list[tuple[int, email.message.EmailMessage]]:
        """Fetch messages with UID > uid_start from folder.

        Returns list of (uid, EmailMessage) tuples, newest-last.
        """
        conn = self._require_conn()
        try:
            status, _ = conn.select(folder, readonly=True)
            if status != "OK":
                raise EmailSyncError(f"Cannot select folder {folder!r}")
        except imaplib.IMAP4.error as exc:
            raise EmailSyncError(f"Failed to select folder {folder!r}: {exc}") from exc

        # Build UID search range
        uid_range = f"{uid_start + 1}:*" if uid_start > 0 else "1:*"

        try:
            status, data = conn.uid("SEARCH", None, f"UID {uid_range}")  # type: ignore
            if status != "OK" or not data or data == [None]:
                return []

            uid_list_raw = data[0]
            if isinstance(uid_list_raw, bytes):
                uid_strs = uid_list_raw.decode().split()
            else:
                uid_strs = []

            # Apply limit — take the last N (most recent)
            uid_strs = uid_strs[-limit:]
            if not uid_strs:
                return []

            uid_set = ",".join(uid_strs)
            status, fetch_data = conn.uid("FETCH", uid_set, "(RFC822)")  # type: ignore
            if status != "OK":
                return []
        except imaplib.IMAP4.error as exc:
            raise EmailSyncError(f"IMAP fetch error: {exc}") from exc

        results: list[tuple[int, email.message.EmailMessage]] = []
        i = 0
        while i < len(fetch_data):
            item = fetch_data[i]
            if isinstance(item, tuple) and len(item) == 2:
                header_part, raw_bytes = item
                if isinstance(raw_bytes, bytes):
                    try:
                        msg = email.message_from_bytes(
                            raw_bytes, policy=email.policy.default
                        )
                        # Extract UID from the fetch response header
                        header_str = header_part.decode(errors="replace") if isinstance(header_part, bytes) else str(header_part)
                        uid_match = re.search(r"UID\s+(\d+)", header_str)
                        uid = int(uid_match.group(1)) if uid_match else 0
                        results.append((uid, msg))  # type: ignore[arg-type]
                    except Exception:
                        pass
            i += 1

        return results

    def test_connection(self) -> None:
        """Connect and immediately verify capability — for account setup validation."""
        conn = self._require_conn()
        try:
            conn.capability()
        except Exception as exc:
            raise EmailConnectionError(f"IMAP capability check failed: {exc}") from exc
