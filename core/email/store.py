"""SQLite database layer for the PaliMind email module.

Database location: ~/.palimind/email.db  (global — not per-workspace)

Design principles:
- WAL mode + synchronous=NORMAL for performance (matches core/storage/db.py)
- Foreign keys enforced on every connection
- FTS5 with content-sync triggers for keyword search
- Schema versioning via schema_version table
- All queries are parameterised — no string interpolation
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from core.config import app_data_dir
from core.email.exceptions import EmailError, EmailSyncError
from core.email.models import Account, Attachment, Email, SearchResult

_EMAIL_DB_PATH = app_data_dir() / "data" / "email.db"

# ---------------------------------------------------------------------------
# Schema version — increment when adding tables/columns
# ---------------------------------------------------------------------------
_SCHEMA_VERSION = 1


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Return a configured sqlite3 Connection to the email database."""
    path = db_path or _EMAIL_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------
_DDL = [
    # ---------------------------------------------------------------
    # accounts
    # ---------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        label         TEXT    NOT NULL UNIQUE,
        email_address TEXT    NOT NULL,
        imap_host     TEXT    NOT NULL,
        imap_port     INTEGER NOT NULL DEFAULT 993,
        smtp_host     TEXT    NOT NULL,
        smtp_port     INTEGER NOT NULL DEFAULT 587,
        username      TEXT    NOT NULL,
        password_enc  TEXT    NOT NULL,
        use_ssl       INTEGER NOT NULL DEFAULT 1,
        created_at    REAL    NOT NULL,
        updated_at    REAL    NOT NULL
    )
    """,
    # ---------------------------------------------------------------
    # emails
    # ---------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS emails (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        folder          TEXT    NOT NULL DEFAULT 'INBOX',
        uid             INTEGER,
        message_id      TEXT    UNIQUE,
        in_reply_to     TEXT    DEFAULT '',
        "references"    TEXT    DEFAULT '',
        thread_id       TEXT    DEFAULT '',
        subject         TEXT    NOT NULL DEFAULT '',
        sender          TEXT    NOT NULL DEFAULT '',
        sender_name     TEXT    DEFAULT '',
        recipients      TEXT    NOT NULL DEFAULT '',
        cc              TEXT    DEFAULT '',
        date            REAL    NOT NULL DEFAULT 0,
        body_html       TEXT    DEFAULT '',
        body_text       TEXT    NOT NULL DEFAULT '',
        has_attachments INTEGER NOT NULL DEFAULT 0,
        summary         TEXT    DEFAULT '',
        tags            TEXT    DEFAULT '',
        priority        INTEGER DEFAULT 0,
        spam_score      INTEGER DEFAULT 0,
        is_read         INTEGER NOT NULL DEFAULT 0,
        is_sent         INTEGER NOT NULL DEFAULT 0,
        fetched_at      REAL    NOT NULL
    )
    """,
    # ---------------------------------------------------------------
    # attachments
    # ---------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS attachments (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        email_id     INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
        filename     TEXT    NOT NULL DEFAULT 'unnamed',
        content_type TEXT    NOT NULL DEFAULT 'application/octet-stream',
        size_bytes   INTEGER DEFAULT 0,
        content_id   TEXT    DEFAULT ''
    )
    """,
    # ---------------------------------------------------------------
    # sync_state
    # ---------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        folder       TEXT    NOT NULL,
        last_uid     INTEGER NOT NULL DEFAULT 0,
        last_sync_at REAL    NOT NULL,
        UNIQUE(account_id, folder)
    )
    """,
    # ---------------------------------------------------------------
    # schema_version
    # ---------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    )
    """,
    # ---------------------------------------------------------------
    # FTS5 virtual table
    # ---------------------------------------------------------------
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
        subject,
        body_text,
        sender,
        content='emails',
        content_rowid='id'
    )
    """,
    # ---------------------------------------------------------------
    # Indexes
    # ---------------------------------------------------------------
    "CREATE INDEX IF NOT EXISTS idx_emails_account_folder ON emails(account_id, folder)",
    "CREATE INDEX IF NOT EXISTS idx_emails_date          ON emails(date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_emails_thread_id     ON emails(thread_id)",
    "CREATE INDEX IF NOT EXISTS idx_emails_sender        ON emails(sender)",
    "CREATE INDEX IF NOT EXISTS idx_emails_is_read       ON emails(is_read) WHERE is_read = 0",
    "CREATE INDEX IF NOT EXISTS idx_emails_priority      ON emails(priority DESC) WHERE priority > 0",
    "CREATE INDEX IF NOT EXISTS idx_attachments_email    ON attachments(email_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_account_folder ON sync_state(account_id, folder)",
    # ---------------------------------------------------------------
    # FTS5 content-sync triggers
    # ---------------------------------------------------------------
    """
    CREATE TRIGGER IF NOT EXISTS emails_fts_ai
    AFTER INSERT ON emails BEGIN
        INSERT INTO emails_fts(rowid, subject, body_text, sender)
        VALUES (new.id, new.subject, new.body_text, new.sender);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS emails_fts_ad
    AFTER DELETE ON emails BEGIN
        INSERT INTO emails_fts(emails_fts, rowid, subject, body_text, sender)
        VALUES ('delete', old.id, old.subject, old.body_text, old.sender);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS emails_fts_au
    AFTER UPDATE ON emails BEGIN
        INSERT INTO emails_fts(emails_fts, rowid, subject, body_text, sender)
        VALUES ('delete', old.id, old.subject, old.body_text, old.sender);
        INSERT INTO emails_fts(rowid, subject, body_text, sender)
        VALUES (new.id, new.subject, new.body_text, new.sender);
    END
    """,
]


def init_email_db(db_path: Optional[Path] = None) -> None:
    """Idempotent DB initialisation — safe to call on every command invocation."""
    path = db_path or _EMAIL_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # Ensure restrictive permissions on a new file
    if not path.exists():
        path.touch(mode=0o600)

    try:
        conn = get_connection(path)
        with conn:
            for stmt in _DDL:
                conn.execute(stmt)
            # Seed schema_version if empty
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_version(version) VALUES (?)", (_SCHEMA_VERSION,)
                )
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to initialise email database: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Account CRUD
# ---------------------------------------------------------------------------

def save_account(
    *,
    label: str,
    email_address: str,
    imap_host: str,
    imap_port: int,
    smtp_host: str,
    smtp_port: int,
    username: str,
    password_enc: str,
    use_ssl: bool,
    db_path: Optional[Path] = None,
) -> int:
    """Insert a new account row; return the new account ID."""
    now = time.time()
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO accounts
                    (label, email_address, imap_host, imap_port,
                     smtp_host, smtp_port, username, password_enc,
                     use_ssl, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    label, email_address, imap_host, imap_port,
                    smtp_host, smtp_port, username, password_enc,
                    1 if use_ssl else 0, now, now,
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]
    except sqlite3.IntegrityError as exc:
        raise EmailError(
            f'Account "{label}" already exists. Use a different label.'
        ) from exc
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to save account: {exc}") from exc
    finally:
        conn.close()


def get_accounts(db_path: Optional[Path] = None) -> list[Account]:
    """Return all configured accounts, joined with last sync time."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT a.*,
                   MAX(ss.last_sync_at) AS last_sync_at
            FROM accounts a
            LEFT JOIN sync_state ss ON ss.account_id = a.id
            GROUP BY a.id
            ORDER BY a.label
            """
        ).fetchall()
        return [_row_to_account(r) for r in rows]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load accounts: {exc}") from exc
    finally:
        conn.close()


def get_account_by_label(label: str, db_path: Optional[Path] = None) -> Account:
    """Return the account with the given label, or raise EmailAccountNotFoundError."""
    from core.email.exceptions import EmailAccountNotFoundError

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT a.*,
                   MAX(ss.last_sync_at) AS last_sync_at
            FROM accounts a
            LEFT JOIN sync_state ss ON ss.account_id = a.id
            WHERE a.label = ?
            GROUP BY a.id
            """,
            (label,),
        ).fetchone()
        if row is None:
            raise EmailAccountNotFoundError(
                f'Account "{label}" not found. Run "pm email accounts" to see available accounts.'
            )
        return _row_to_account(row)
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load account: {exc}") from exc
    finally:
        conn.close()


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        label=row["label"],
        email_address=row["email_address"],
        imap_host=row["imap_host"],
        imap_port=row["imap_port"],
        smtp_host=row["smtp_host"],
        smtp_port=row["smtp_port"],
        username=row["username"],
        password_enc=row["password_enc"],
        use_ssl=bool(row["use_ssl"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_sync_at=row["last_sync_at"] if "last_sync_at" in row.keys() else None,
    )


# ---------------------------------------------------------------------------
# Email CRUD
# ---------------------------------------------------------------------------

def upsert_email(
    *,
    account_id: int,
    folder: str,
    uid: Optional[int],
    message_id: str,
    in_reply_to: str,
    references: str,
    thread_id: str,
    subject: str,
    sender: str,
    sender_name: str,
    recipients: str,
    cc: str,
    date: float,
    body_html: str,
    body_text: str,
    has_attachments: bool,
    is_sent: bool = False,
    db_path: Optional[Path] = None,
) -> Optional[int]:
    """INSERT OR IGNORE the email; return new row ID, or None if duplicate."""
    now = time.time()
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO emails
                    (account_id, folder, uid, message_id, in_reply_to,
                     "references", thread_id, subject, sender, sender_name,
                     recipients, cc, date, body_html, body_text,
                     has_attachments, is_sent, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    account_id, folder, uid, message_id, in_reply_to,
                    references, thread_id, subject, sender, sender_name,
                    recipients, cc, date, body_html, body_text,
                    1 if has_attachments else 0,
                    1 if is_sent else 0,
                    now,
                ),
            )
            if cur.lastrowid and cur.rowcount > 0:
                return cur.lastrowid
            return None  # duplicate
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to save email: {exc}") from exc
    finally:
        conn.close()


def save_attachment(
    *,
    email_id: int,
    filename: str,
    content_type: str,
    size_bytes: int,
    content_id: str,
    db_path: Optional[Path] = None,
) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO attachments
                    (email_id, filename, content_type, size_bytes, content_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (email_id, filename, content_type, size_bytes, content_id),
            )
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to save attachment: {exc}") from exc
    finally:
        conn.close()


def update_ai_fields(
    email_id: int,
    *,
    summary: str = "",
    tags: str = "",
    priority: int = 0,
    spam_score: int = 0,
    db_path: Optional[Path] = None,
) -> None:
    """Update the AI-generated fields for an email row."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE emails
                SET summary = ?, tags = ?, priority = ?, spam_score = ?
                WHERE id = ?
                """,
                (summary, tags, priority, spam_score, email_id),
            )
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to update AI fields: {exc}") from exc
    finally:
        conn.close()


def get_emails(
    *,
    account_id: Optional[int] = None,
    folder: Optional[str] = None,
    unread_only: bool = False,
    tag: Optional[str] = None,
    after: Optional[float] = None,
    before: Optional[float] = None,
    sort: str = "date",
    limit: int = 20,
    offset: int = 0,
    db_path: Optional[Path] = None,
) -> list[Email]:
    """Fetch emails from the local store with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if account_id is not None:
        conditions.append("e.account_id = ?")
        params.append(account_id)
    if folder:
        conditions.append("e.folder = ?")
        params.append(folder)
    if unread_only:
        conditions.append("e.is_read = 0")
    if tag:
        conditions.append("(',' || e.tags || ',') LIKE ?")
        params.append(f"%,{tag},%")
    if after is not None:
        conditions.append("e.date >= ?")
        params.append(after)
    if before is not None:
        conditions.append("e.date <= ?")
        params.append(before)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    sort_col = {
        "date": "e.date DESC",
        "priority": "e.priority DESC, e.date DESC",
        "sender": "e.sender ASC, e.date DESC",
    }.get(sort, "e.date DESC")

    params.extend([limit, offset])
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT e.* FROM emails e
            {where_clause}
            ORDER BY {sort_col}
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        emails = [_row_to_email(r) for r in rows]
        _attach_attachments(conn, emails)
        return emails
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load emails: {exc}") from exc
    finally:
        conn.close()


def get_email_by_id(email_id: int, db_path: Optional[Path] = None) -> Email:
    """Return a single email by its local ID, or raise EmailNotFoundError."""
    from core.email.exceptions import EmailNotFoundError

    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if row is None:
            raise EmailNotFoundError(f"Email #{email_id} not found.")
        emails = [_row_to_email(row)]
        _attach_attachments(conn, emails)
        return emails[0]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Database error: {exc}") from exc
    finally:
        conn.close()


def mark_read(email_id: int, db_path: Optional[Path] = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("UPDATE emails SET is_read = 1 WHERE id = ?", (email_id,))
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to mark email as read: {exc}") from exc
    finally:
        conn.close()


def get_unread_count(
    account_id: Optional[int] = None,
    folder: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    conditions = ["is_read = 0"]
    params: list[Any] = []
    if account_id is not None:
        conditions.append("account_id = ?")
        params.append(account_id)
    if folder:
        conditions.append("folder = ?")
        params.append(folder)
    where = "WHERE " + " AND ".join(conditions)
    conn = get_connection(db_path)
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM emails {where}", params).fetchone()
        return row[0]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to count unread: {exc}") from exc
    finally:
        conn.close()


def _row_to_email(row: sqlite3.Row) -> Email:
    d = dict(row)
    return Email(
        id=d["id"],
        account_id=d["account_id"],
        folder=d["folder"],
        uid=d.get("uid"),
        message_id=d.get("message_id") or "",
        in_reply_to=d.get("in_reply_to") or "",
        references=d.get("references") or "",
        thread_id=d.get("thread_id") or "",
        subject=d.get("subject") or "",
        sender=d.get("sender") or "",
        sender_name=d.get("sender_name") or "",
        recipients=d.get("recipients") or "",
        cc=d.get("cc") or "",
        date=d.get("date") or 0.0,
        body_html=d.get("body_html") or "",
        body_text=d.get("body_text") or "",
        has_attachments=bool(d.get("has_attachments")),
        summary=d.get("summary") or "",
        tags=d.get("tags") or "",
        priority=d.get("priority") or 0,
        spam_score=d.get("spam_score") or 0,
        is_read=bool(d.get("is_read")),
        is_sent=bool(d.get("is_sent")),
        fetched_at=d.get("fetched_at") or 0.0,
    )


def _attach_attachments(conn: sqlite3.Connection, emails: list[Email]) -> None:
    """Mutate Email objects in-place with their attachment lists.

    Since Email is frozen we rebuild each object — this is acceptable for the
    list sizes involved in Phase 1.
    """
    if not emails:
        return
    ids = [e.id for e in emails]
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM attachments WHERE email_id IN ({placeholders})",
        ids,
    ).fetchall()

    att_map: dict[int, list[Attachment]] = {}
    for r in rows:
        a = Attachment(
            id=r["id"],
            email_id=r["email_id"],
            filename=r["filename"] or "unnamed",
            content_type=r["content_type"] or "application/octet-stream",
            size_bytes=r["size_bytes"] or 0,
            content_id=r["content_id"] or "",
        )
        att_map.setdefault(r["email_id"], []).append(a)

    # Rebuild frozen dataclasses with attachments populated
    for i, email in enumerate(emails):
        atts = tuple(att_map.get(email.id, []))
        if atts:
            import dataclasses
            emails[i] = dataclasses.replace(email, attachments=atts)


# ---------------------------------------------------------------------------
# Sync state
# ---------------------------------------------------------------------------

def get_sync_state(
    account_id: int,
    folder: str,
    db_path: Optional[Path] = None,
) -> int:
    """Return last synced UID for account+folder (0 if never synced)."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT last_uid FROM sync_state WHERE account_id = ? AND folder = ?",
            (account_id, folder),
        ).fetchone()
        return row["last_uid"] if row else 0
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to load sync state: {exc}") from exc
    finally:
        conn.close()


def update_sync_state(
    account_id: int,
    folder: str,
    last_uid: int,
    db_path: Optional[Path] = None,
) -> None:
    now = time.time()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO sync_state(account_id, folder, last_uid, last_sync_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id, folder)
                DO UPDATE SET last_uid = excluded.last_uid,
                              last_sync_at = excluded.last_sync_at
                """,
                (account_id, folder, last_uid, now),
            )
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Failed to update sync state: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------------

def _sanitize_fts_query(query: str) -> str:
    """Strip FTS5 special characters to prevent injection / parse errors."""
    import re
    # FTS5 treats many chars specially (*, -, ", ^, NOT, AND, OR, etc.)
    # Keep only alphanumerics and whitespace for safety
    sanitized = re.sub(r'[^\w\s]', ' ', query, flags=re.UNICODE)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized or "zzz_no_match"  # FTS5 dislikes empty queries


def search_fts(
    query: str,
    *,
    account_id: Optional[int] = None,
    folder: Optional[str] = None,
    after: Optional[float] = None,
    before: Optional[float] = None,
    limit: int = 10,
    db_path: Optional[Path] = None,
) -> list[SearchResult]:
    """BM25-ranked full-text search using the emails_fts virtual table."""
    safe_query = _sanitize_fts_query(query)
    conditions = []
    params: list[Any] = [safe_query]

    if account_id is not None:
        conditions.append("e.account_id = ?")
        params.append(account_id)
    if folder:
        conditions.append("e.folder = ?")
        params.append(folder)
    if after is not None:
        conditions.append("e.date >= ?")
        params.append(after)
    if before is not None:
        conditions.append("e.date <= ?")
        params.append(before)

    extra_where = ("AND " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT e.id,
                   bm25(emails_fts)      AS score,
                   e.subject,
                   e.sender,
                   e.date,
                   e.is_read,
                   snippet(emails_fts, 1, '[', ']', '…', 20) AS snippet
            FROM emails_fts
            JOIN emails e ON e.id = emails_fts.rowid
            WHERE emails_fts MATCH ?
            {extra_where}
            ORDER BY score
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            SearchResult(
                email_id=r["id"],
                score=abs(r["score"]),  # bm25 returns negative values
                subject=r["subject"],
                sender=r["sender"],
                snippet=r["snippet"] or "",
                date=r["date"],
                is_read=bool(r["is_read"]),
            )
            for r in rows
        ]
    except sqlite3.Error as exc:
        raise EmailSyncError(f"Search failed: {exc}") from exc
    finally:
        conn.close()
