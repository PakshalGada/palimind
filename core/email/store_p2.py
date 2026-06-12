"""Phase 2 database layer for the PaliMind email module.

Extends the existing schema with new tables and helper functions.
All migrations are idempotent — safe to run on existing Phase 1 databases.

New tables:
  - email_p2_meta      : Phase-2 per-email metadata (needs_reply, is_newsletter, etc.)
  - reminders          : User-created email reminders
  - spam_prefs         : Whitelist / blacklist sender preferences
  - contact_stats_cache: Cached contact analytics (rebuilt on demand)
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from core.email.exceptions import EmailSyncError
from core.email.store import get_connection

# ---------------------------------------------------------------------------
# Phase 2 schema DDL — all CREATE TABLE IF NOT EXISTS
# ---------------------------------------------------------------------------

_P2_DDL = [
    # Per-email Phase-2 metadata
    """
    CREATE TABLE IF NOT EXISTS email_p2_meta (
        email_id          INTEGER PRIMARY KEY REFERENCES emails(id) ON DELETE CASCADE,
        needs_reply       INTEGER NOT NULL DEFAULT 0,
        reply_confidence  INTEGER NOT NULL DEFAULT 0,
        reply_reason      TEXT    DEFAULT '',
        is_newsletter     INTEGER NOT NULL DEFAULT 0,
        newsletter_conf   INTEGER NOT NULL DEFAULT 0,
        spam_status       TEXT    NOT NULL DEFAULT 'safe',
        spam_confidence   INTEGER NOT NULL DEFAULT 0,
        spam_reason       TEXT    DEFAULT '',
        spam_reviewed     INTEGER NOT NULL DEFAULT 0,
        is_replied        INTEGER NOT NULL DEFAULT 0,
        updated_at        REAL    NOT NULL DEFAULT 0
    )
    """,
    # User-defined reminders
    """
    CREATE TABLE IF NOT EXISTS reminders (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        email_id    INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
        note        TEXT    NOT NULL DEFAULT '',
        due_at      REAL,
        is_done     INTEGER NOT NULL DEFAULT 0,
        created_at  REAL    NOT NULL,
        done_at     REAL
    )
    """,
    # Spam whitelist / blacklist preferences
    """
    CREATE TABLE IF NOT EXISTS spam_prefs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sender      TEXT    NOT NULL UNIQUE,
        list_type   TEXT    NOT NULL CHECK(list_type IN ('whitelist', 'blacklist')),
        created_at  REAL    NOT NULL
    )
    """,
    # Cached contact analytics (rebuilt on demand)
    """
    CREATE TABLE IF NOT EXISTS contact_stats_cache (
        sender          TEXT    PRIMARY KEY,
        sender_name     TEXT    DEFAULT '',
        emails_received INTEGER NOT NULL DEFAULT 0,
        emails_sent     INTEGER NOT NULL DEFAULT 0,
        last_received   REAL,
        last_sent       REAL,
        replied_count   INTEGER NOT NULL DEFAULT 0,
        updated_at      REAL    NOT NULL
    )
    """,
    # Spam scan metadata (last scan timestamp, count)
    """
    CREATE TABLE IF NOT EXISTS spam_scan_meta (
        key    TEXT PRIMARY KEY,
        value  TEXT NOT NULL
    )
    """,
    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_p2_needs_reply     ON email_p2_meta(needs_reply) WHERE needs_reply = 1",
    "CREATE INDEX IF NOT EXISTS idx_p2_newsletter      ON email_p2_meta(is_newsletter) WHERE is_newsletter = 1",
    "CREATE INDEX IF NOT EXISTS idx_p2_spam_status     ON email_p2_meta(spam_status)",
    "CREATE INDEX IF NOT EXISTS idx_p2_reviewed        ON email_p2_meta(spam_reviewed) WHERE spam_reviewed = 0",
    "CREATE INDEX IF NOT EXISTS idx_reminders_email    ON reminders(email_id)",
    "CREATE INDEX IF NOT EXISTS idx_reminders_due      ON reminders(due_at) WHERE is_done = 0",
    "CREATE INDEX IF NOT EXISTS idx_spam_prefs_sender  ON spam_prefs(sender)",
]


def apply_p2_migrations(db_path: Optional[Path] = None) -> None:
    """Idempotently apply Phase 2 schema to an existing or new database."""
    conn = get_connection(db_path)
    try:
        with conn:
            for stmt in _P2_DDL:
                conn.execute(stmt)
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to apply Phase 2 migrations: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# email_p2_meta CRUD
# ---------------------------------------------------------------------------

def get_p2_meta(email_id: int, db_path: Optional[Path] = None) -> Optional[dict]:
    """Return Phase-2 metadata dict for an email, or None if absent."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM email_p2_meta WHERE email_id = ?", (email_id,)
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def upsert_p2_meta(
    email_id: int,
    *,
    needs_reply: Optional[bool] = None,
    reply_confidence: Optional[int] = None,
    reply_reason: Optional[str] = None,
    is_newsletter: Optional[bool] = None,
    newsletter_conf: Optional[int] = None,
    spam_status: Optional[str] = None,
    spam_confidence: Optional[int] = None,
    spam_reason: Optional[str] = None,
    spam_reviewed: Optional[bool] = None,
    is_replied: Optional[bool] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Insert or update Phase-2 metadata for an email. Only provided fields are updated."""
    now = time.time()
    conn = get_connection(db_path)
    try:
        with conn:
            # Ensure row exists
            conn.execute(
                "INSERT OR IGNORE INTO email_p2_meta(email_id, updated_at) VALUES (?, ?)",
                (email_id, now),
            )
            # Build dynamic UPDATE
            updates: list[str] = ["updated_at = ?"]
            params: list[Any] = [now]
            if needs_reply is not None:
                updates.append("needs_reply = ?"); params.append(1 if needs_reply else 0)
            if reply_confidence is not None:
                updates.append("reply_confidence = ?"); params.append(reply_confidence)
            if reply_reason is not None:
                updates.append("reply_reason = ?"); params.append(reply_reason)
            if is_newsletter is not None:
                updates.append("is_newsletter = ?"); params.append(1 if is_newsletter else 0)
            if newsletter_conf is not None:
                updates.append("newsletter_conf = ?"); params.append(newsletter_conf)
            if spam_status is not None:
                updates.append("spam_status = ?"); params.append(spam_status)
            if spam_confidence is not None:
                updates.append("spam_confidence = ?"); params.append(spam_confidence)
            if spam_reason is not None:
                updates.append("spam_reason = ?"); params.append(spam_reason)
            if spam_reviewed is not None:
                updates.append("spam_reviewed = ?"); params.append(1 if spam_reviewed else 0)
            if is_replied is not None:
                updates.append("is_replied = ?"); params.append(1 if is_replied else 0)
            params.append(email_id)
            conn.execute(
                f"UPDATE email_p2_meta SET {', '.join(updates)} WHERE email_id = ?",
                params,
            )
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to update p2 metadata: {exc}") from exc
    finally:
        conn.close()


def get_emails_needing_reply(
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return emails flagged as needing reply, ordered by reply confidence."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT e.id, e.subject, e.sender, e.sender_name, e.date,
                   e.is_read, e.priority, e.summary,
                   m.reply_confidence, m.reply_reason
            FROM email_p2_meta m
            JOIN emails e ON e.id = m.email_id
            WHERE m.needs_reply = 1 AND m.is_replied = 0
              AND e.is_sent = 0
            ORDER BY e.priority DESC, m.reply_confidence DESC, e.date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load needs-reply emails: {exc}") from exc
    finally:
        conn.close()


def get_newsletters(
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return emails classified as newsletters."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT e.id, e.subject, e.sender, e.sender_name, e.date,
                   e.is_read, m.newsletter_conf
            FROM email_p2_meta m
            JOIN emails e ON e.id = m.email_id
            WHERE m.is_newsletter = 1
            ORDER BY e.date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load newsletters: {exc}") from exc
    finally:
        conn.close()


def get_spam_emails(
    status: Optional[str] = None,
    reviewed: Optional[bool] = None,
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return emails with spam metadata. Filter by status ('spam'/'suspicious'/'safe') or review state."""
    conditions = ["m.spam_status != 'safe'"]
    params: list[Any] = []
    if status:
        conditions = ["m.spam_status = ?"]
        params.append(status)
    if reviewed is not None:
        conditions.append("m.spam_reviewed = ?")
        params.append(1 if reviewed else 0)
    where = "WHERE " + " AND ".join(conditions)
    params.append(limit)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT e.id, e.subject, e.sender, e.sender_name, e.date,
                   m.spam_status, m.spam_confidence, m.spam_reason, m.spam_reviewed
            FROM email_p2_meta m
            JOIN emails e ON e.id = m.email_id
            {where}
            ORDER BY m.spam_confidence DESC, e.date DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load spam emails: {exc}") from exc
    finally:
        conn.close()


def get_spam_stats(db_path: Optional[Path] = None) -> dict:
    """Return aggregate spam statistics."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN spam_status = 'spam'        THEN 1 ELSE 0 END) AS spam_count,
                SUM(CASE WHEN spam_status = 'suspicious'  THEN 1 ELSE 0 END) AS suspicious_count,
                SUM(CASE WHEN spam_reviewed = 0 AND spam_status != 'safe' THEN 1 ELSE 0 END) AS unreviewed_count
            FROM email_p2_meta
            """
        ).fetchone()
        top_senders = conn.execute(
            """
            SELECT e.sender, COUNT(*) AS cnt
            FROM email_p2_meta m
            JOIN emails e ON e.id = m.email_id
            WHERE m.spam_status IN ('spam', 'suspicious')
            GROUP BY e.sender
            ORDER BY cnt DESC
            LIMIT 5
            """
        ).fetchall()
        # Confidence distribution
        dist = conn.execute(
            """
            SELECT
                SUM(CASE WHEN spam_status != 'safe' AND spam_confidence >= 90 THEN 1 ELSE 0 END) AS high,
                SUM(CASE WHEN spam_status != 'safe' AND spam_confidence >= 60 AND spam_confidence < 90 THEN 1 ELSE 0 END) AS medium,
                SUM(CASE WHEN spam_status != 'safe' AND spam_confidence < 60 THEN 1 ELSE 0 END) AS low
            FROM email_p2_meta
            """
        ).fetchone()
        # Last scan metadata
        try:
            last_scan = conn.execute(
                "SELECT value FROM spam_scan_meta WHERE key = 'last_scan_at'"
            ).fetchone()
            scanned_total = conn.execute(
                "SELECT value FROM spam_scan_meta WHERE key = 'scanned_total'"
            ).fetchone()
            last_scan_at = float(last_scan["value"]) if last_scan else None
            scanned_total_n = int(scanned_total["value"]) if scanned_total else 0
        except Exception:
            last_scan_at = None
            scanned_total_n = 0
        return {
            "spam_count": row["spam_count"] or 0,
            "suspicious_count": row["suspicious_count"] or 0,
            "unreviewed_count": row["unreviewed_count"] or 0,
            "top_spam_senders": [(r["sender"], r["cnt"]) for r in top_senders],
            "dist_high": dist["high"] or 0 if dist else 0,
            "dist_medium": dist["medium"] or 0 if dist else 0,
            "dist_low": dist["low"] or 0 if dist else 0,
            "last_scan_at": last_scan_at,
            "scanned_total": scanned_total_n,
        }
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to get spam stats: {exc}") from exc
    finally:
        conn.close()


def set_spam_scan_meta(last_scan_at: float, scanned_total: int, db_path: Optional[Path] = None) -> None:
    """Persist spam scan metadata (last run time + count)."""
    conn = get_connection(db_path)
    try:
        with conn:
            for key, value in [
                ("last_scan_at", str(last_scan_at)),
                ("scanned_total", str(scanned_total)),
            ]:
                conn.execute(
                    "INSERT INTO spam_scan_meta(key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to save spam scan meta: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reminders CRUD
# ---------------------------------------------------------------------------

def create_reminder(
    email_id: int,
    note: str,
    due_at: Optional[float] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Create a reminder for an email. Returns the reminder ID."""
    now = time.time()
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO reminders(email_id, note, due_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (email_id, note, due_at, now),
            )
            return cur.lastrowid  # type: ignore[return-value]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to create reminder: {exc}") from exc
    finally:
        conn.close()


def get_reminders(
    include_done: bool = False,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return all reminders with their associated email subject/sender."""
    where = "" if include_done else "WHERE r.is_done = 0"
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT r.id, r.email_id, r.note, r.due_at, r.is_done,
                   r.created_at, r.done_at,
                   e.subject, e.sender, e.sender_name
            FROM reminders r
            JOIN emails e ON e.id = r.email_id
            {where}
            ORDER BY r.is_done ASC, r.due_at ASC NULLS LAST, r.created_at ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load reminders: {exc}") from exc
    finally:
        conn.close()


def dismiss_reminder(reminder_id: int, db_path: Optional[Path] = None) -> None:
    """Mark a reminder as done."""
    now = time.time()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE reminders SET is_done = 1, done_at = ? WHERE id = ?",
                (now, reminder_id),
            )
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to dismiss reminder: {exc}") from exc
    finally:
        conn.close()


def get_due_reminders(db_path: Optional[Path] = None) -> list[dict]:
    """Return overdue and due-today reminders."""
    now = time.time()
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.email_id, r.note, r.due_at,
                   e.subject, e.sender, e.sender_name
            FROM reminders r
            JOIN emails e ON e.id = r.email_id
            WHERE r.is_done = 0 AND (r.due_at IS NULL OR r.due_at <= ?)
            ORDER BY r.due_at ASC NULLS LAST
            """,
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load due reminders: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Spam Preferences (whitelist / blacklist)
# ---------------------------------------------------------------------------

def add_spam_pref(
    sender: str,
    list_type: str,
    db_path: Optional[Path] = None,
) -> None:
    """Add or update a sender in the whitelist or blacklist."""
    if list_type not in ("whitelist", "blacklist"):
        raise ValueError(f"list_type must be 'whitelist' or 'blacklist', got {list_type!r}")
    now = time.time()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO spam_prefs(sender, list_type, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(sender) DO UPDATE SET list_type = excluded.list_type,
                                                  created_at = excluded.created_at
                """,
                (sender.lower().strip(), list_type, now),
            )
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to save spam preference: {exc}") from exc
    finally:
        conn.close()


def get_spam_pref(sender: str, db_path: Optional[Path] = None) -> Optional[str]:
    """Return 'whitelist', 'blacklist', or None for a sender."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT list_type FROM spam_prefs WHERE sender = ?",
            (sender.lower().strip(),),
        ).fetchone()
        return row["list_type"] if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def get_all_spam_prefs(db_path: Optional[Path] = None) -> list[dict]:
    """Return all whitelist / blacklist entries."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT sender, list_type, created_at FROM spam_prefs ORDER BY list_type, sender"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load spam prefs: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Contact Analytics
# ---------------------------------------------------------------------------

def rebuild_contact_stats(db_path: Optional[Path] = None) -> None:
    """Rebuild the contact_stats_cache table from the emails table."""
    now = time.time()
    conn = get_connection(db_path)
    try:
        with conn:
            # Received emails grouped by sender
            received = conn.execute(
                """
                SELECT sender, sender_name,
                       COUNT(*) AS cnt,
                       MAX(date) AS last_date
                FROM emails
                WHERE is_sent = 0 AND sender != ''
                GROUP BY sender
                """
            ).fetchall()
            # Sent emails (proxy: is_sent=1 and recipient is contact)
            # Count outgoing emails by recipient (approximate contact analytics)
            sent = conn.execute(
                """
                SELECT recipients AS sender,
                       COUNT(*) AS cnt,
                       MAX(date) AS last_date
                FROM emails
                WHERE is_sent = 1 AND recipients != ''
                GROUP BY recipients
                """
            ).fetchall()
            # Count replies: sent emails that have a non-empty thread_id
            # that also appears in received emails
            replied = conn.execute(
                """
                SELECT e2.sender, COUNT(*) AS cnt
                FROM emails e1
                JOIN emails e2 ON e1.thread_id = e2.thread_id
                WHERE e1.is_sent = 1 AND e2.is_sent = 0
                  AND e1.thread_id != ''
                  AND e2.sender != ''
                GROUP BY e2.sender
                """
            ).fetchall()
            replied_map: dict[str, int] = {r["sender"]: r["cnt"] for r in replied}

            conn.execute("DELETE FROM contact_stats_cache")
            for r in received:
                sender = r["sender"]
                conn.execute(
                    """
                    INSERT INTO contact_stats_cache
                        (sender, sender_name, emails_received, last_received, replied_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sender) DO UPDATE
                        SET emails_received = excluded.emails_received,
                            last_received   = excluded.last_received,
                            replied_count   = excluded.replied_count,
                            updated_at      = excluded.updated_at
                    """,
                    (sender, r["sender_name"], r["cnt"], r["last_date"],
                     replied_map.get(sender, 0), now),
                )
            for s in sent:
                # Sent-to stats — best effort, recipients can be multi-address
                sender = s["sender"].split(",")[0].strip()
                if sender:
                    conn.execute(
                        """
                        INSERT INTO contact_stats_cache(sender, emails_sent, last_sent, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(sender) DO UPDATE
                            SET emails_sent = excluded.emails_sent,
                                last_sent   = excluded.last_sent,
                                updated_at  = excluded.updated_at
                        """,
                        (sender, s["cnt"], s["last_date"], now),
                    )
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to rebuild contact stats: {exc}") from exc
    finally:
        conn.close()


def get_contact_stats(
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return top contacts by total email volume."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT sender, sender_name,
                   emails_received, emails_sent,
                   (emails_received + emails_sent) AS total,
                   last_received, last_sent, replied_count
            FROM contact_stats_cache
            ORDER BY total DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load contact stats: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Enhanced Statistics
# ---------------------------------------------------------------------------

def get_email_stats(db_path: Optional[Path] = None) -> dict:
    """Return enhanced email statistics for pm email stats."""
    conn = get_connection(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        unread = conn.execute("SELECT COUNT(*) FROM emails WHERE is_read = 0").fetchone()[0]
        sent = conn.execute("SELECT COUNT(*) FROM emails WHERE is_sent = 1").fetchone()[0]
        has_att = conn.execute(
            "SELECT COUNT(*) FROM emails WHERE has_attachments = 1"
        ).fetchone()[0]

        # Phase 2 stats
        try:
            spam_count = conn.execute(
                "SELECT COUNT(*) FROM email_p2_meta WHERE spam_status = 'spam'"
            ).fetchone()[0]
            suspicious_count = conn.execute(
                "SELECT COUNT(*) FROM email_p2_meta WHERE spam_status = 'suspicious'"
            ).fetchone()[0]
            newsletter_count = conn.execute(
                "SELECT COUNT(*) FROM email_p2_meta WHERE is_newsletter = 1"
            ).fetchone()[0]
            needs_reply_count = conn.execute(
                "SELECT COUNT(*) FROM email_p2_meta WHERE needs_reply = 1 AND is_replied = 0"
            ).fetchone()[0]
            reminder_count = conn.execute(
                "SELECT COUNT(*) FROM reminders WHERE is_done = 0"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            spam_count = suspicious_count = newsletter_count = 0
            needs_reply_count = reminder_count = 0

        # Storage usage
        try:
            db_path_obj = db_path or Path.home() / ".palimind" / "email.db"
            storage_bytes = db_path_obj.stat().st_size if db_path_obj.exists() else 0
        except OSError:
            storage_bytes = 0

        # Last sync
        last_sync = conn.execute(
            "SELECT MAX(last_sync_at) FROM sync_state"
        ).fetchone()[0]

        # Top contacts (from cache)
        try:
            top_contacts_rows = conn.execute(
                """
                SELECT sender, sender_name, (emails_received + emails_sent) AS total
                FROM contact_stats_cache
                ORDER BY total DESC LIMIT 5
                """
            ).fetchall()
            top_contacts = [(r["sender"], r["sender_name"], r["total"]) for r in top_contacts_rows]
        except sqlite3.OperationalError:
            top_contacts = []

        return {
            "total": total,
            "unread": unread,
            "sent": sent,
            "has_attachments": has_att,
            "spam_count": spam_count,
            "suspicious_count": suspicious_count,
            "newsletter_count": newsletter_count,
            "needs_reply_count": needs_reply_count,
            "reminder_count": reminder_count,
            "storage_bytes": storage_bytes,
            "last_sync_at": last_sync,
            "top_contacts": top_contacts,
        }
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to get email stats: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Today's inbox data
# ---------------------------------------------------------------------------

def get_today_emails(
    account_id: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """Return structured data for pm email today."""
    now = time.time()
    day_start = now - 86400  # last 24 hours

    conditions = ["e.date >= ?"]
    params: list[Any] = [day_start]
    if account_id is not None:
        conditions.append("e.account_id = ?")
        params.append(account_id)
    where = "WHERE " + " AND ".join(conditions)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT e.*,
                   COALESCE(m.needs_reply, 0)    AS needs_reply,
                   COALESCE(m.is_newsletter, 0)  AS is_newsletter,
                   COALESCE(m.spam_status, 'safe') AS spam_status,
                   COALESCE(m.spam_confidence, 0) AS spam_confidence
            FROM emails e
            LEFT JOIN email_p2_meta m ON m.email_id = e.id
            {where}
              AND e.is_sent = 0
            ORDER BY e.date DESC
            """,
            params,
        ).fetchall()

        all_emails = [dict(r) for r in rows]
        unread = [e for e in all_emails if not e.get("is_read")]
        high_priority = [e for e in all_emails if (e.get("priority") or 0) >= 3]
        needs_reply = [e for e in all_emails if e.get("needs_reply")]
        meetings = [
            e for e in all_emails
            if any(kw in (e.get("tags") or "").lower() for kw in ("meeting", "interview", "calendar"))
            or any(kw in (e.get("subject") or "").lower() for kw in ("meeting", "interview", "invite", "calendar"))
        ]
        finance = [
            e for e in all_emails
            if any(kw in (e.get("tags") or "").lower() for kw in ("invoice", "payment", "finance", "billing"))
            or any(kw in (e.get("subject") or "").lower() for kw in ("invoice", "payment", "receipt", "billing"))
        ]
        newsletters = [e for e in all_emails if e.get("is_newsletter")]
        spam = [e for e in all_emails if e.get("spam_status") in ("spam", "suspicious")]

        # Due reminders today
        try:
            due_reminders = get_due_reminders(db_path)
        except Exception:
            due_reminders = []

        return {
            "all": all_emails,
            "unread": unread,
            "high_priority": high_priority,
            "needs_reply": needs_reply,
            "meetings": meetings,
            "finance": finance,
            "newsletters": newsletters,
            "spam": spam,
            "due_reminders": due_reminders,
        }
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load today's emails: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sent email style samples (for style-aware drafting)
# ---------------------------------------------------------------------------

def get_sent_samples(
    limit: int = 10,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return recent sent emails as style examples."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT subject, recipients, body_text
            FROM emails
            WHERE is_sent = 1 AND body_text != ''
            ORDER BY date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load sent samples: {exc}") from exc
    finally:
        conn.close()
