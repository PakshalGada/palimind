"""Phase 2 API facade for the PaliMind email module.

Orchestrates store_p2, ai_p2, and existing store/ai modules.
All functions are safe to call — wraps errors in EmailError.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.email import store
from core.email import ai_p2, store_p2
from core.email.api import ensure_db, list_emails, search_emails
from core.email.exceptions import EmailError, EmailSyncError
from core.email.models import Email


# ---------------------------------------------------------------------------
# Initialise Phase 2 DB schema
# ---------------------------------------------------------------------------

def ensure_p2_db(db_path: Optional[Path] = None) -> None:
    """Ensure both Phase 1 and Phase 2 schemas are initialised."""
    ensure_db(db_path)
    store_p2.apply_p2_migrations(db_path)


# ---------------------------------------------------------------------------
# Watch mode
# ---------------------------------------------------------------------------

def watch_accounts(
    interval: int = 300,
    folder: str = "INBOX",
    limit: int = 20,
    run_ai: bool = True,
    notify: bool = True,
    db_path: Optional[Path] = None,
    on_new_email=None,     # callback(account_label, email_id, subject, sender)
    on_cycle_complete=None,  # callback(account_label, stored_count)
) -> None:
    """Continuously poll all accounts. Blocks until KeyboardInterrupt.

    Reuses sync_account from Phase 1 API — no new sync pipeline.
    """
    from core.email.api import list_accounts, sync_account

    ensure_p2_db(db_path)

    while True:
        try:
            accounts = list_accounts(db_path)
        except EmailError:
            accounts = []

        for acc in accounts:
            try:
                result = sync_account(
                    acc.label,
                    folder=folder,
                    limit=limit,
                    run_ai=run_ai,
                    db_path=db_path,
                )
                if on_cycle_complete:
                    on_cycle_complete(acc.label, result.stored)

                if result.stored > 0 and on_new_email:
                    # Notify about new emails (latest few)
                    new_emails = store.get_emails(
                        account_id=acc.id,
                        folder=folder,
                        limit=min(result.stored, 5),
                        db_path=db_path,
                    )
                    for em in new_emails:
                        on_new_email(acc.label, em.id, em.subject, em.sender)

                    if notify:
                        _try_desktop_notify(result.stored, acc.label, new_emails)
            except Exception:
                pass  # Never crash the watch loop

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return


def _try_desktop_notify(count: int, account_label: str, emails: list[Email]) -> None:
    """Attempt a desktop notification for new emails. Silent failure."""
    try:
        import subprocess
        subjects = ", ".join(e.subject[:30] for e in emails[:3])
        message = f"{count} new email(s) — {subjects}"
        # Try notify-send (Linux), then osascript (macOS)
        try:
            subprocess.run(
                ["notify-send", f"PaliMind: {account_label}", message],
                check=True,
                capture_output=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{message}" with title "PaliMind: {account_label}"'],
                check=True,
                capture_output=True,
                timeout=5,
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Natural Language Email Q&A
# ---------------------------------------------------------------------------

def ask_email_question(
    question: str,
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> tuple[str, list[dict]]:
    """Answer a natural language question about emails.

    Returns (answer_text, list of relevant email dicts for citation).
    Reuses FTS search + metadata retrieval; no separate pipeline.
    """
    ensure_p2_db(db_path)

    # Extract keywords from question for FTS retrieval
    keywords = _extract_search_keywords(question)
    email_results = []

    if keywords:
        try:
            results = search_emails(keywords, limit=limit, db_path=db_path)
            email_ids = [r.email_id for r in results]
        except Exception:
            email_ids = []
    else:
        email_ids = []

    # Also get recent emails if keyword search returned few results
    if len(email_ids) < 5:
        try:
            recent = list_emails(limit=20, db_path=db_path)
            recent_ids = [e.id for e in recent if e.id not in email_ids]
            email_ids = email_ids + recent_ids[:10]
        except Exception:
            pass

    # Build context string
    context_parts = []
    refs = []
    for eid in email_ids[:15]:
        try:
            em = store.get_email_by_id(eid, db_path)
            date_str = datetime.fromtimestamp(em.date, tz=timezone.utc).strftime("%Y-%m-%d") if em.date else "unknown"
            context_parts.append(
                f"[#{em.id}] From: {em.sender_name or em.sender} | "
                f"Date: {date_str} | Subject: {em.subject}\n"
                f"Summary: {em.summary or em.body_text[:200]}"
            )
            refs.append({
                "id": em.id,
                "subject": em.subject,
                "sender": em.sender,
                "sender_name": em.sender_name,
                "date": em.date,
            })
        except Exception:
            pass

    context = "\n\n".join(context_parts)
    answer = ai_p2.answer_email_question(question, context)
    return answer, refs


def _extract_search_keywords(question: str) -> str:
    """Extract meaningful keywords from a question for FTS search."""
    import re
    # Remove common question words
    stop_words = {
        "which", "who", "what", "when", "where", "how", "why", "is", "are",
        "was", "were", "do", "does", "did", "have", "has", "had", "can", "could",
        "show", "find", "list", "me", "my", "the", "a", "an", "from", "to", "of",
        "in", "on", "at", "by", "for", "with", "about", "last", "week", "month",
        "emails", "email", "any", "all", "some", "those",
    }
    words = re.findall(r"\b\w+\b", question.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    return " ".join(keywords[:8])


# ---------------------------------------------------------------------------
# Needs-reply detection
# ---------------------------------------------------------------------------

def scan_needs_reply(
    limit: int = 100,
    run_ai: bool = True,
    db_path: Optional[Path] = None,
) -> int:
    """Scan recent unread emails for reply requirements. Returns count flagged."""
    ensure_p2_db(db_path)

    try:
        emails = list_emails(limit=limit, db_path=db_path)
    except EmailError:
        return 0

    flagged = 0
    for em in emails:
        if em.is_sent:
            continue
        try:
            # Check spam pref for sender
            sender_pref = store_p2.get_spam_pref(em.sender, db_path)
            if sender_pref == "blacklist":
                continue  # Skip blacklisted senders

            needs, conf, reason = ai_p2.detect_needs_reply(
                em.subject, em.sender, em.body_text
            )
            store_p2.upsert_p2_meta(
                em.id,
                needs_reply=needs,
                reply_confidence=conf,
                reply_reason=reason,
                db_path=db_path,
            )
            if needs:
                flagged += 1
        except Exception:
            pass
    return flagged


def get_needs_reply_emails(db_path: Optional[Path] = None) -> list[dict]:
    """Return emails that need a reply."""
    ensure_p2_db(db_path)
    return store_p2.get_emails_needing_reply(db_path=db_path)


# ---------------------------------------------------------------------------
# Daily inbox summary
# ---------------------------------------------------------------------------

def get_today_summary(
    account_label: Optional[str] = None,
    run_ai: bool = True,
    db_path: Optional[Path] = None,
) -> dict:
    """Return today's inbox data with an optional AI summary."""
    ensure_p2_db(db_path)

    account_id: Optional[int] = None
    if account_label:
        try:
            acc = store.get_account_by_label(account_label, db_path)
            account_id = acc.id
        except Exception:
            pass

    data = store_p2.get_today_emails(account_id=account_id, db_path=db_path)

    ai_summary = ""
    if run_ai and data["all"]:
        # Build concise context for AI
        context_parts = []
        for e in data["all"][:20]:
            context_parts.append(
                f"From: {e.get('sender_name') or e.get('sender')} | "
                f"Subject: {e.get('subject')} | "
                f"Priority: {e.get('priority', 0)}"
            )
        ai_summary = ai_p2.summarise_today("\n".join(context_parts))

    data["ai_summary"] = ai_summary
    return data


# ---------------------------------------------------------------------------
# Contact analytics
# ---------------------------------------------------------------------------

def get_contacts(
    rebuild: bool = False,
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return contact analytics. Rebuilds cache if requested or empty."""
    ensure_p2_db(db_path)

    contacts = store_p2.get_contact_stats(limit=limit, db_path=db_path)
    if rebuild or not contacts:
        store_p2.rebuild_contact_stats(db_path)
        contacts = store_p2.get_contact_stats(limit=limit, db_path=db_path)

    return contacts


# ---------------------------------------------------------------------------
# Style-aware drafting
# ---------------------------------------------------------------------------

def draft_compose_styled(
    intent: str,
    recipient: str,
    db_path: Optional[Path] = None,
) -> str:
    """Draft a new email using the user's personal writing style."""
    ensure_p2_db(db_path)

    samples = store_p2.get_sent_samples(limit=8, db_path=db_path)
    if not samples:
        # Fall back to plain drafting
        from core.email.ai import draft_compose
        return draft_compose(intent=intent, recipient=recipient)

    style_examples = "\n\n---\n\n".join(
        f"To: {s['recipients']}\nSubject: {s['subject']}\n\n{s['body_text'][:800]}"
        for s in samples
    )
    return ai_p2.draft_with_style(intent, recipient, style_examples)


def draft_reply_styled(
    email_id: int,
    intent: str,
    db_path: Optional[Path] = None,
) -> str:
    """Draft a reply email using the user's personal writing style."""
    ensure_p2_db(db_path)

    try:
        original = store.get_email_by_id(email_id, db_path)
    except Exception:
        return ""

    samples = store_p2.get_sent_samples(limit=5, db_path=db_path)
    if not samples:
        from core.email.ai import draft_reply
        return draft_reply(
            sender=original.sender,
            subject=original.subject,
            body_text=original.body_text,
            intent=intent,
        )

    style_examples = "\n\n---\n\n".join(
        f"To: {s['recipients']}\nSubject: {s['subject']}\n\n{s['body_text'][:600]}"
        for s in samples
    )
    full_intent = (
        f"Reply to: {original.sender} about '{original.subject}'. "
        f"Intent: {intent}\n\n"
        f"Original email:\n{original.body_text[:2000]}"
    )
    return ai_p2.draft_with_style(full_intent, original.sender, style_examples)


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

def create_reminder(
    email_id: int,
    note: Optional[str] = None,
    due_str: Optional[str] = None,
    auto_note: bool = True,
    db_path: Optional[Path] = None,
) -> dict:
    """Create a reminder for an email. Auto-generates note if not provided."""
    ensure_p2_db(db_path)

    try:
        em = store.get_email_by_id(email_id, db_path)
    except Exception as exc:
        raise EmailError(f"Email #{email_id} not found.") from exc

    if not note and auto_note:
        note = ai_p2.auto_summarise_reminder(em.subject, em.sender, em.body_text)
        if not note:
            note = f"Follow up on: {em.subject[:80]}"

    due_at = _parse_due_date(due_str)

    reminder_id = store_p2.create_reminder(
        email_id=email_id,
        note=note or "",
        due_at=due_at,
        db_path=db_path,
    )
    return {
        "id": reminder_id,
        "email_id": email_id,
        "note": note,
        "due_at": due_at,
        "subject": em.subject,
        "sender": em.sender,
    }


def list_reminders(
    include_done: bool = False,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return all active (or all) reminders."""
    ensure_p2_db(db_path)
    return store_p2.get_reminders(include_done=include_done, db_path=db_path)


def dismiss_reminder(reminder_id: int, db_path: Optional[Path] = None) -> None:
    """Mark a reminder as done."""
    ensure_p2_db(db_path)
    store_p2.dismiss_reminder(reminder_id, db_path)


def _parse_due_date(due_str: Optional[str]) -> Optional[float]:
    """Parse 'YYYY-MM-DD' or relative terms ('tomorrow', 'next week')."""
    if not due_str:
        return None
    due_str = due_str.strip().lower()
    now = time.time()
    if due_str == "tomorrow":
        return now + 86400
    if due_str in ("next week", "nextweek"):
        return now + 7 * 86400
    try:
        dt = datetime.strptime(due_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Newsletters
# ---------------------------------------------------------------------------

def scan_newsletters(
    limit: int = 100,
    db_path: Optional[Path] = None,
) -> int:
    """Scan emails and mark newsletters. Returns count marked."""
    ensure_p2_db(db_path)

    try:
        emails = list_emails(limit=limit, db_path=db_path)
    except EmailError:
        return 0

    marked = 0
    for em in emails:
        if em.is_sent:
            continue
        try:
            is_nl, conf = ai_p2.detect_newsletter(
                em.subject, em.sender, em.body_text
            )
            if is_nl or conf >= 50:
                store_p2.upsert_p2_meta(
                    em.id,
                    is_newsletter=is_nl,
                    newsletter_conf=conf,
                    db_path=db_path,
                )
                if is_nl:
                    marked += 1
        except Exception:
            pass
    return marked


def get_newsletters(db_path: Optional[Path] = None) -> list[dict]:
    """Return emails classified as newsletters."""
    ensure_p2_db(db_path)
    return store_p2.get_newsletters(db_path=db_path)


# ---------------------------------------------------------------------------
# Spam management
# ---------------------------------------------------------------------------

def scan_spam(
    limit: int = 100,
    db_path: Optional[Path] = None,
) -> int:
    """Scan emails and compute enhanced spam scores. Returns count flagged."""
    ensure_p2_db(db_path)

    try:
        emails = list_emails(limit=limit, db_path=db_path)
    except EmailError:
        return 0

    flagged = 0
    for em in emails:
        if em.is_sent:
            continue
        try:
            sender_pref = store_p2.get_spam_pref(em.sender, db_path)
            status, conf, reason = ai_p2.compute_enhanced_spam_score(
                em.subject, em.sender, em.body_text,
                sender_pref=sender_pref,
            )
            store_p2.upsert_p2_meta(
                em.id,
                spam_status=status,
                spam_confidence=conf,
                spam_reason=reason,
                db_path=db_path,
            )
            if status in ("spam", "suspicious"):
                flagged += 1
        except Exception:
            pass
    return flagged


def get_spam_dashboard(db_path: Optional[Path] = None) -> dict:
    """Return spam statistics for the dashboard."""
    ensure_p2_db(db_path)
    return store_p2.get_spam_stats(db_path=db_path)


def get_spam_list(
    status: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return spam/suspicious emails."""
    ensure_p2_db(db_path)
    return store_p2.get_spam_emails(status=status, limit=limit, db_path=db_path)


def get_spam_for_review(db_path: Optional[Path] = None) -> list[dict]:
    """Return unreviewed borderline (suspicious) emails."""
    ensure_p2_db(db_path)
    return store_p2.get_spam_emails(status="suspicious", reviewed=False, db_path=db_path)


def mark_spam_reviewed(
    email_id: int,
    is_spam: bool,
    db_path: Optional[Path] = None,
) -> None:
    """Mark a spam-review decision for an email."""
    ensure_p2_db(db_path)
    new_status = "spam" if is_spam else "safe"
    store_p2.upsert_p2_meta(
        email_id,
        spam_status=new_status,
        spam_reviewed=True,
        db_path=db_path,
    )


def add_spam_whitelist(sender: str, db_path: Optional[Path] = None) -> None:
    ensure_p2_db(db_path)
    store_p2.add_spam_pref(sender, "whitelist", db_path)


def add_spam_blacklist(sender: str, db_path: Optional[Path] = None) -> None:
    ensure_p2_db(db_path)
    store_p2.add_spam_pref(sender, "blacklist", db_path)


def get_spam_prefs(db_path: Optional[Path] = None) -> list[dict]:
    ensure_p2_db(db_path)
    return store_p2.get_all_spam_prefs(db_path=db_path)


# ---------------------------------------------------------------------------
# Enhanced statistics
# ---------------------------------------------------------------------------

def get_enhanced_stats(db_path: Optional[Path] = None) -> dict:
    """Return enhanced statistics combining Phase 1 and Phase 2 data."""
    ensure_p2_db(db_path)
    return store_p2.get_email_stats(db_path=db_path)
