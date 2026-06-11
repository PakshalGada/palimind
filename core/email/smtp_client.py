"""SMTP client for the PaliMind email module.

Uses stdlib smtplib — no external dependencies.

Usage:
    send_message(
        host="smtp.gmail.com", port=587,
        username="me@gmail.com", password="...",
        message=mime_message, use_ssl=False
    )
"""
from __future__ import annotations

import email.mime.multipart
import email.mime.text
import email.utils
import smtplib
import socket
import time
import uuid
from email.message import Message

from core.email.exceptions import EmailAuthError, EmailConnectionError, EmailSendError

_TIMEOUT_SECONDS = 30


def build_message(
    *,
    from_addr: str,
    to_addrs: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    in_reply_to: str = "",
    references: str = "",
    original_message_id: str = "",
) -> email.mime.multipart.MIMEMultipart:
    """Build a MIMEMultipart email message with proper headers.

    Returns the constructed message object (not yet sent).
    """
    msg = email.mime.multipart.MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = f"<{uuid.uuid4()}@palimind>"

    if cc:
        msg["Cc"] = ", ".join(cc)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    elif original_message_id:
        msg["References"] = original_message_id

    msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))
    return msg


def send_message(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    message: Message,
    use_ssl: bool = True,
) -> None:
    """Send a constructed MIME message via SMTP.

    Handles both SSL (port 465) and STARTTLS (port 587).
    """
    try:
        if use_ssl and port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT_SECONDS)
        else:
            smtp = smtplib.SMTP(host, port, timeout=_TIMEOUT_SECONDS)
            smtp.ehlo()
            if smtp.has_extn("STARTTLS"):
                smtp.starttls()
                smtp.ehlo()
    except (socket.timeout, TimeoutError) as exc:
        raise EmailConnectionError(
            f"SMTP connection to {host}:{port} timed out."
        ) from exc
    except (ConnectionRefusedError, OSError) as exc:
        raise EmailConnectionError(
            f"Cannot connect to SMTP server {host}:{port} — {exc}"
        ) from exc
    except smtplib.SMTPException as exc:
        raise EmailConnectionError(f"SMTP connection error: {exc}") from exc

    try:
        smtp.login(username, password)
    except smtplib.SMTPAuthenticationError as exc:
        smtp.quit()
        raise EmailAuthError(
            f"SMTP authentication failed for {username} on {host}."
        ) from exc
    except smtplib.SMTPException as exc:
        smtp.quit()
        raise EmailSendError(f"SMTP login error: {exc}") from exc

    try:
        smtp.send_message(message)
    except smtplib.SMTPRecipientsRefused as exc:
        raise EmailSendError(f"Recipient refused: {exc.recipients}") from exc
    except smtplib.SMTPException as exc:
        raise EmailSendError(f"Failed to send message: {exc}") from exc
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def test_smtp_connection(
    host: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool = True,
) -> None:
    """Verify SMTP credentials without sending a message."""
    try:
        if use_ssl and port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT_SECONDS)
        else:
            smtp = smtplib.SMTP(host, port, timeout=_TIMEOUT_SECONDS)
            smtp.ehlo()
            if smtp.has_extn("STARTTLS"):
                smtp.starttls()
                smtp.ehlo()
    except (socket.timeout, TimeoutError) as exc:
        raise EmailConnectionError(
            f"SMTP connection to {host}:{port} timed out."
        ) from exc
    except (ConnectionRefusedError, OSError) as exc:
        raise EmailConnectionError(
            f"Cannot connect to SMTP server {host}:{port} — {exc}"
        ) from exc
    except smtplib.SMTPException as exc:
        raise EmailConnectionError(f"SMTP error: {exc}") from exc

    try:
        smtp.login(username, password)
        smtp.quit()
    except smtplib.SMTPAuthenticationError as exc:
        smtp.quit()
        raise EmailAuthError(
            f"SMTP authentication failed for {username} on {host}."
        ) from exc
    except smtplib.SMTPException as exc:
        smtp.quit()
        raise EmailConnectionError(f"SMTP error: {exc}") from exc
