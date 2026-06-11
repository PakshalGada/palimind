"""Facade layer for the PaliMind email module.

All public functions orchestrate imap_client, smtp_client, store, parser,
ai, and crypto. Never raises raw exceptions — wraps everything in EmailError.

This is the only module that CLI and tests should call directly.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from core.email import ai, store
from core.email.crypto import decrypt_password, encrypt_password
from core.email.exceptions import (
    EmailAccountNotFoundError,
    EmailError,
    EmailNotFoundError,
    EmailSyncError,
)
from core.email.imap_client import IMAPClient
from core.email.models import Account, Email, SearchResult, SendResult, SyncResult
from core.email.parser import parse_message
from core.email.smtp_client import build_message, send_message, test_smtp_connection


# ---------------------------------------------------------------------------
# DB initialisation — call on every command
# ---------------------------------------------------------------------------

def ensure_db(db_path: Optional[Path] = None) -> None:
    """Idempotently initialise the email DB (safe to call every invocation)."""
    store.init_email_db(db_path)


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------

def add_account(
    *,
    label: str,
    email_address: str,
    imap_host: str,
    imap_port: int,
    smtp_host: str,
    smtp_port: int,
    username: Optional[str] = None,
    password: str,
    use_ssl: bool = True,
    test_connection: bool = True,
    db_path: Optional[Path] = None,
) -> Account:
    """Add a new email account with encrypted credentials.

    Optionally tests IMAP and SMTP connectivity before saving.
    """
    ensure_db(db_path)
    resolved_username = username or email_address

    if test_connection:
        # Test IMAP
        with IMAPClient(imap_host, imap_port, resolved_username, password, use_ssl=use_ssl) as client:
            client.test_connection()
        # Test SMTP
        test_smtp_connection(smtp_host, smtp_port, resolved_username, password, use_ssl=use_ssl)

    enc_password = encrypt_password(password)
    account_id = store.save_account(
        label=label,
        email_address=email_address,
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=resolved_username,
        password_enc=enc_password,
        use_ssl=use_ssl,
        db_path=db_path,
    )
    accounts = store.get_accounts(db_path)
    for acc in accounts:
        if acc.id == account_id:
            return acc
    raise EmailError("Account saved but could not be retrieved.")


def list_accounts(db_path: Optional[Path] = None) -> list[Account]:
    """Return all configured accounts."""
    ensure_db(db_path)
    return store.get_accounts(db_path)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def sync_account(
    account_label: str,
    *,
    folder: str = "INBOX",
    limit: int = 50,
    full_resync: bool = False,
    run_ai: bool = True,
    db_path: Optional[Path] = None,
    progress_callback=None,
) -> SyncResult:
    """Fetch new emails for an account+folder and optionally run AI processing.

    progress_callback(phase, current, total) is called during fetch and AI phases.
    """
    ensure_db(db_path)
    account = store.get_account_by_label(account_label, db_path)
    password = decrypt_password(account.password_enc)

    last_uid = 0 if full_resync else store.get_sync_state(account.id, folder, db_path)

    # --- IMAP fetch ---
    with IMAPClient(
        account.imap_host,
        account.imap_port,
        account.username,
        password,
        use_ssl=account.use_ssl,
    ) as client:
        raw_messages = client.fetch_messages(folder, uid_start=last_uid, limit=limit)

    fetched = len(raw_messages)
    stored = 0
    duplicates = 0
    parse_errors = 0
    new_email_ids: list[int] = []
    max_uid = last_uid

    if progress_callback:
        progress_callback("fetch", 0, fetched)

    for i, (uid, raw_msg) in enumerate(raw_messages):
        if uid > max_uid:
            max_uid = uid
        try:
            parsed = parse_message(raw_msg)  # type: ignore[arg-type]
        except Exception:
            parse_errors += 1
            if progress_callback:
                progress_callback("fetch", i + 1, fetched)
            continue

        email_id = store.upsert_email(
            account_id=account.id,
            folder=folder,
            uid=uid,
            message_id=parsed["message_id"],
            in_reply_to=parsed["in_reply_to"],
            references=parsed["references"],
            thread_id=parsed["thread_id"],
            subject=parsed["subject"],
            sender=parsed["sender"],
            sender_name=parsed["sender_name"],
            recipients=parsed["recipients"],
            cc=parsed["cc"],
            date=parsed["date"],
            body_html=parsed["body_html"],
            body_text=parsed["body_text"],
            has_attachments=parsed["has_attachments"],
            db_path=db_path,
        )

        if email_id is not None:
            stored += 1
            new_email_ids.append(email_id)
            for att in parsed.get("attachments", []):
                store.save_attachment(
                    email_id=email_id,
                    filename=att["filename"],
                    content_type=att["content_type"],
                    size_bytes=att["size_bytes"],
                    content_id=att["content_id"],
                    db_path=db_path,
                )
        else:
            duplicates += 1

        if progress_callback:
            progress_callback("fetch", i + 1, fetched)

    # Update sync state
    if max_uid > last_uid:
        store.update_sync_state(account.id, folder, max_uid, db_path)

    # --- AI processing ---
    ai_processed = 0
    if run_ai and new_email_ids:
        if progress_callback:
            progress_callback("ai", 0, len(new_email_ids))
        for j, eid in enumerate(new_email_ids):
            try:
                em = store.get_email_by_id(eid, db_path)
                summary = ai.summarise_email(em.body_text)
                tags_list = ai.classify_tags(em.subject, em.body_text)
                priority = ai.score_priority(em.subject, em.body_text, em.sender)
                spam = ai.score_spam(em.subject, em.body_text, em.sender)
                store.update_ai_fields(
                    eid,
                    summary=summary,
                    tags=", ".join(tags_list),
                    priority=priority,
                    spam_score=spam,
                    db_path=db_path,
                )
                if summary or tags_list:
                    ai_processed += 1
            except Exception:
                pass
            if progress_callback:
                progress_callback("ai", j + 1, len(new_email_ids))

    return SyncResult(
        account_label=account_label,
        folder=folder,
        fetched=fetched,
        stored=stored,
        duplicates=duplicates,
        parse_errors=parse_errors,
        ai_processed=ai_processed,
    )


# ---------------------------------------------------------------------------
# Listing / reading
# ---------------------------------------------------------------------------

def list_emails(
    *,
    account_label: Optional[str] = None,
    folder: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    sort: str = "date",
    tag: Optional[str] = None,
    after_str: Optional[str] = None,
    before_str: Optional[str] = None,
    unread_only: bool = False,
    db_path: Optional[Path] = None,
) -> list[Email]:
    """Return emails from the local store with optional filters."""
    ensure_db(db_path)
    account_id: Optional[int] = None
    if account_label:
        account = store.get_account_by_label(account_label, db_path)
        account_id = account.id

    after = _parse_date_str(after_str)
    before = _parse_date_str(before_str)

    return store.get_emails(
        account_id=account_id,
        folder=folder,
        unread_only=unread_only,
        tag=tag,
        after=after,
        before=before,
        sort=sort,
        limit=limit,
        offset=offset,
        db_path=db_path,
    )


def get_email(email_id: int, db_path: Optional[Path] = None) -> Email:
    """Return a single email by ID and mark it as read."""
    ensure_db(db_path)
    em = store.get_email_by_id(email_id, db_path)
    store.mark_read(email_id, db_path)
    return em


def unread_emails(
    account_label: Optional[str] = None,
    folder: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """Return unread counts per account and a list of unread emails."""
    ensure_db(db_path)
    accounts = store.get_accounts(db_path)
    counts: dict[str, int] = {}
    total = 0
    for acc in accounts:
        if account_label and acc.label != account_label:
            continue
        c = store.get_unread_count(acc.id, folder, db_path)
        counts[acc.label] = c
        total += c

    emails = store.get_emails(
        account_id=None if not account_label else _account_id_for_label(accounts, account_label),
        folder=folder,
        unread_only=True,
        limit=50,
        db_path=db_path,
    )
    return {"total": total, "by_account": counts, "emails": emails}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_emails(
    query: str,
    *,
    account_label: Optional[str] = None,
    folder: Optional[str] = None,
    limit: int = 10,
    after_str: Optional[str] = None,
    before_str: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> list[SearchResult]:
    """Full-text keyword search using FTS5."""
    ensure_db(db_path)
    account_id: Optional[int] = None
    if account_label:
        account = store.get_account_by_label(account_label, db_path)
        account_id = account.id

    return store.search_fts(
        query,
        account_id=account_id,
        folder=folder,
        after=_parse_date_str(after_str),
        before=_parse_date_str(before_str),
        limit=limit,
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# Compose / reply
# ---------------------------------------------------------------------------

def compose_email(
    *,
    account_label: str,
    to_addresses: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    dry_run: bool = False,
    db_path: Optional[Path] = None,
) -> SendResult:
    """Send a new email via SMTP and record it in the local store."""
    ensure_db(db_path)
    account = store.get_account_by_label(account_label, db_path)
    password = decrypt_password(account.password_enc)

    msg = build_message(
        from_addr=account.email_address,
        to_addrs=to_addresses,
        subject=subject,
        body=body,
        cc=cc,
    )
    message_id: str = msg.get("Message-ID", "")

    if not dry_run:
        send_message(
            host=account.smtp_host,
            port=account.smtp_port,
            username=account.username,
            password=password,
            message=msg,
            use_ssl=account.use_ssl,
        )
        # Save sent email to local store
        store.upsert_email(
            account_id=account.id,
            folder="Sent",
            uid=None,
            message_id=message_id,
            in_reply_to="",
            references="",
            thread_id="",
            subject=subject,
            sender=account.email_address,
            sender_name="",
            recipients=", ".join(to_addresses),
            cc=", ".join(cc or []),
            date=time.time(),
            body_html="",
            body_text=body,
            has_attachments=False,
            is_sent=True,
            db_path=db_path,
        )

    return SendResult(
        message_id=message_id,
        recipient=", ".join(to_addresses),
        subject=subject,
        smtp_host=account.smtp_host,
    )


def reply_to_email(
    email_id: int,
    *,
    body: str,
    reply_all: bool = False,
    dry_run: bool = False,
    db_path: Optional[Path] = None,
) -> SendResult:
    """Reply to an existing email."""
    ensure_db(db_path)
    original = store.get_email_by_id(email_id, db_path)

    # Determine account by account_id
    accounts = store.get_accounts(db_path)
    account = next((a for a in accounts if a.id == original.account_id), None)
    if account is None:
        raise EmailError("Cannot determine sending account for this email.")

    password = decrypt_password(account.password_enc)
    to_addrs = [original.sender]
    if reply_all:
        for addr in original.recipients.split(","):
            addr = addr.strip()
            if addr and addr != account.email_address:
                to_addrs.append(addr)

    reply_subject = (
        original.subject if original.subject.startswith("Re:")
        else f"Re: {original.subject}"
    )
    # Build References chain
    refs = original.references
    if original.message_id:
        refs = (refs + " " + original.message_id).strip()

    msg = build_message(
        from_addr=account.email_address,
        to_addrs=to_addrs,
        subject=reply_subject,
        body=body,
        in_reply_to=original.message_id,
        references=refs,
        original_message_id=original.message_id,
    )
    message_id: str = msg.get("Message-ID", "")

    if not dry_run:
        send_message(
            host=account.smtp_host,
            port=account.smtp_port,
            username=account.username,
            password=password,
            message=msg,
            use_ssl=account.use_ssl,
        )
        store.upsert_email(
            account_id=account.id,
            folder="Sent",
            uid=None,
            message_id=message_id,
            in_reply_to=original.message_id,
            references=refs,
            thread_id=original.thread_id,
            subject=reply_subject,
            sender=account.email_address,
            sender_name="",
            recipients=", ".join(to_addrs),
            cc="",
            date=time.time(),
            body_html="",
            body_text=body,
            has_attachments=False,
            is_sent=True,
            db_path=db_path,
        )

    return SendResult(
        message_id=message_id,
        recipient=", ".join(to_addrs),
        subject=reply_subject,
        smtp_host=account.smtp_host,
    )


# ---------------------------------------------------------------------------
# AI drafting helpers (used by CLI)
# ---------------------------------------------------------------------------

def ai_draft_compose(intent: str, recipient: str) -> str:
    return ai.draft_compose(intent=intent, recipient=recipient)


def ai_draft_reply(email_id: int, intent: str, db_path: Optional[Path] = None) -> str:
    original = store.get_email_by_id(email_id, db_path)
    return ai.draft_reply(
        sender=original.sender,
        subject=original.subject,
        body_text=original.body_text,
        intent=intent,
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _parse_date_str(date_str: Optional[str]) -> Optional[float]:
    if not date_str:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _account_id_for_label(accounts: list[Account], label: str) -> Optional[int]:
    for acc in accounts:
        if acc.label == label:
            return acc.id
    return None
