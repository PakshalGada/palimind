# PaliMind Email Module — Database Schema

## Overview

The email database is a standalone SQLite file at `~/.palimind/email.db`, separate from the per-workspace `index.db`. This isolation ensures email data is global (not tied to any workspace) and the existing RAG pipeline is unaffected.

**Conventions adopted from `core/storage/db.py`:**

- WAL journal mode for concurrent reads
- `PRAGMA synchronous=NORMAL` for performance
- `PRAGMA foreign_keys = ON` enforced on every connection
- FTS5 with content-sync triggers
- Connection helper function returning `sqlite3.Connection`

---

## Entity-Relationship Diagram

```
┌──────────────┐       ┌──────────────────────────────┐
│   accounts   │       │           emails              │
├──────────────┤       ├──────────────────────────────┤
│ id (PK)      │◄──┐   │ id (PK)                      │
│ label        │   │   │ account_id (FK → accounts.id)│
│ email_address│   └───│ folder                       │
│ imap_host    │       │ uid                          │
│ imap_port    │       │ message_id (UNIQUE)          │
│ smtp_host    │       │ in_reply_to                  │
│ smtp_port    │       │ references                   │
│ username     │       │ thread_id                    │
│ password_enc │       │ subject                      │
│ use_ssl      │       │ sender                       │
│ created_at   │       │ sender_name                  │
│ updated_at   │       │ recipients                   │
└──────────────┘       │ cc                           │
                       │ date                         │
                       │ body_html                    │
                       │ body_text                    │
                       │ has_attachments              │
                       │ summary                      │
                       │ tags                         │
                       │ priority                     │
                       │ spam_score                   │
                       │ is_read                      │
                       │ is_sent                      │
                       │ fetched_at                   │
                       └──────────┬───────────────────┘
                                  │
                       ┌──────────▼───────────────────┐
                       │       attachments             │
                       ├──────────────────────────────┤
                       │ id (PK)                      │
                       │ email_id (FK → emails.id)    │
                       │ filename                     │
                       │ content_type                 │
                       │ size_bytes                   │
                       │ content_id                   │
                       └──────────────────────────────┘

┌──────────────────────────────────┐
│          sync_state              │
├──────────────────────────────────┤
│ id (PK)                         │
│ account_id (FK → accounts.id)   │
│ folder                          │
│ last_uid                        │
│ last_sync_at                    │
│ UNIQUE(account_id, folder)      │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│       emails_fts (FTS5)          │
├──────────────────────────────────┤
│ subject                         │
│ body_text                       │
│ sender                          │
│ (content-sync with emails)      │
└──────────────────────────────────┘
```

---

## Table Definitions

### `accounts`

Stores IMAP/SMTP server credentials. Passwords are encrypted at rest.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `label` | TEXT | NOT NULL UNIQUE | User-friendly name (e.g., "Work Gmail") |
| `email_address` | TEXT | NOT NULL | Full email address |
| `imap_host` | TEXT | NOT NULL | IMAP server hostname |
| `imap_port` | INTEGER | NOT NULL DEFAULT 993 | IMAP port (993 for SSL, 143 for STARTTLS) |
| `smtp_host` | TEXT | NOT NULL | SMTP server hostname |
| `smtp_port` | INTEGER | NOT NULL DEFAULT 587 | SMTP port (587 for STARTTLS, 465 for SSL) |
| `username` | TEXT | NOT NULL | Login username (often same as email) |
| `password_enc` | TEXT | NOT NULL | Fernet-encrypted password (base64 string) |
| `use_ssl` | INTEGER | NOT NULL DEFAULT 1 | 1 = SSL, 0 = STARTTLS |
| `created_at` | REAL | NOT NULL | Unix timestamp of creation |
| `updated_at` | REAL | NOT NULL | Unix timestamp of last update |

**Rationale**: Separate from emails so one account can hold many folders. `label` is UNIQUE to prevent accidental duplicates. `password_enc` stores the Fernet token as a base64 string — never plaintext.

---

### `emails`

Core table storing every fetched (or sent) email.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `account_id` | INTEGER | NOT NULL, FK → accounts(id) ON DELETE CASCADE | Owning account |
| `folder` | TEXT | NOT NULL DEFAULT 'INBOX' | IMAP folder name |
| `uid` | INTEGER | | IMAP UID within the folder |
| `message_id` | TEXT | UNIQUE | RFC 2822 Message-ID header |
| `in_reply_to` | TEXT | | Message-ID of parent email |
| `references` | TEXT | | Space-separated Message-IDs chain |
| `thread_id` | TEXT | | Computed thread grouping key |
| `subject` | TEXT | NOT NULL DEFAULT '' | Email subject line |
| `sender` | TEXT | NOT NULL | Sender email address |
| `sender_name` | TEXT | DEFAULT '' | Sender display name |
| `recipients` | TEXT | NOT NULL | Comma-separated To addresses |
| `cc` | TEXT | DEFAULT '' | Comma-separated CC addresses |
| `date` | REAL | NOT NULL | Email Date header as Unix timestamp |
| `body_html` | TEXT | DEFAULT '' | Original HTML body (if present) |
| `body_text` | TEXT | NOT NULL DEFAULT '' | Plaintext body (extracted or converted) |
| `has_attachments` | INTEGER | NOT NULL DEFAULT 0 | 1 if email has attachments |
| `summary` | TEXT | DEFAULT '' | AI-generated summary |
| `tags` | TEXT | DEFAULT '' | Comma-separated AI or user tags |
| `priority` | INTEGER | DEFAULT 0 | AI priority score (0-5, 5 = highest) |
| `spam_score` | INTEGER | DEFAULT 0 | AI spam confidence (0-100) |
| `is_read` | INTEGER | NOT NULL DEFAULT 0 | 1 if read by user |
| `is_sent` | INTEGER | NOT NULL DEFAULT 0 | 1 if sent by user (vs. fetched) |
| `fetched_at` | REAL | NOT NULL | Unix timestamp when inserted |

**Rationale:**

- `message_id` UNIQUE handles duplicate detection — `INSERT OR IGNORE` on sync.
- `thread_id` is computed from the `References` chain during parsing; enables thread-view grouping.
- `body_html` retained so the user can view the original rendering if needed; `body_text` is the working copy for AI and search.
- `tags` as comma-separated text (not a join table) keeps queries simple and avoids schema complexity for MVP. Phase 2 may normalize this.
- `priority` and `spam_score` are integers for easy sorting and filtering.
- `date` stored as REAL (Unix timestamp) for efficient range queries and sorting.

---

### `attachments`

Metadata-only — attachment content is NOT stored (Phase 1). Phase 2 may add content indexing.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `email_id` | INTEGER | NOT NULL, FK → emails(id) ON DELETE CASCADE | Owning email |
| `filename` | TEXT | NOT NULL DEFAULT 'unnamed' | Original filename |
| `content_type` | TEXT | NOT NULL DEFAULT 'application/octet-stream' | MIME type |
| `size_bytes` | INTEGER | DEFAULT 0 | Approximate size in bytes |
| `content_id` | TEXT | DEFAULT '' | Content-ID for inline images |

**Rationale**: Storing metadata enables `pm email read` to show attachment info and future Phase 2 content indexing. CASCADE ensures cleanup when emails are deleted.

---

### `sync_state`

Tracks the last synced IMAP UID per account+folder for incremental sync.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `account_id` | INTEGER | NOT NULL, FK → accounts(id) ON DELETE CASCADE | Account reference |
| `folder` | TEXT | NOT NULL | IMAP folder name |
| `last_uid` | INTEGER | NOT NULL DEFAULT 0 | Last fetched IMAP UID |
| `last_sync_at` | REAL | NOT NULL | Timestamp of last sync |

**Unique constraint**: `UNIQUE(account_id, folder)` — one row per account/folder pair, updated via `INSERT ... ON CONFLICT DO UPDATE`.

**Rationale**: IMAP UIDs are monotonically increasing within a folder. Storing the last UID enables `UID FETCH last_uid+1:*` for efficient incremental sync without re-fetching everything.

---

### `emails_fts` (FTS5 Virtual Table)

Full-text search index on email content.

```sql
CREATE VIRTUAL TABLE emails_fts USING fts5(
    subject,
    body_text,
    sender,
    content='emails',
    content_rowid='id'
);
```

**Triggers** (matching `core/storage/db.py` FTS pattern):

```sql
-- After INSERT
CREATE TRIGGER emails_fts_ai AFTER INSERT ON emails BEGIN
    INSERT INTO emails_fts(rowid, subject, body_text, sender)
    VALUES (new.id, new.subject, new.body_text, new.sender);
END;

-- After DELETE
CREATE TRIGGER emails_fts_ad AFTER DELETE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, body_text, sender)
    VALUES ('delete', old.id, old.subject, old.body_text, old.sender);
END;

-- After UPDATE
CREATE TRIGGER emails_fts_au AFTER UPDATE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, body_text, sender)
    VALUES ('delete', old.id, old.subject, old.body_text, old.sender);
    INSERT INTO emails_fts(rowid, subject, body_text, sender)
    VALUES (new.id, new.subject, new.body_text, new.sender);
END;
```

**Rationale**: Content-sync mode keeps FTS in lock-step with the `emails` table automatically. BM25 ranking provides relevance scoring. Indexing `sender` enables search by contact.

---

## Indexes

```sql
CREATE INDEX idx_emails_account_folder ON emails(account_id, folder);
CREATE INDEX idx_emails_date ON emails(date DESC);
CREATE INDEX idx_emails_thread_id ON emails(thread_id);
CREATE INDEX idx_emails_sender ON emails(sender);
CREATE INDEX idx_emails_is_read ON emails(is_read) WHERE is_read = 0;
CREATE INDEX idx_emails_priority ON emails(priority DESC) WHERE priority > 0;
CREATE INDEX idx_attachments_email ON attachments(email_id);
CREATE UNIQUE INDEX idx_sync_account_folder ON sync_state(account_id, folder);
```

**Rationale:**

- `idx_emails_account_folder`: Most queries filter by account + folder (e.g., "show INBOX for Work account").
- `idx_emails_date`: Sorting by date is the default list view.
- `idx_emails_thread_id`: Thread grouping queries.
- `idx_emails_is_read` (partial): Optimizes `pm email unread` which queries `WHERE is_read = 0`.
- `idx_emails_priority` (partial): Optimizes priority-sorted views in Phase 2.

---

## Migration Strategy

### Initial Setup

`init_email_db()` in `store.py` creates all tables, indexes, triggers, and FTS on first run. It is idempotent — safe to call on every command invocation.

### Schema Versioning

A `schema_version` table tracks the current schema version:

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
```

On startup, `init_email_db()`:

1. Reads current version (default 0 if table is empty/missing).
2. Applies migrations sequentially up to the latest version.
3. Updates the version number.

### Phase 2 Migrations

Phase 2 will add:

```sql
-- Migration v2: Contact statistics
CREATE TABLE contact_stats (
    email_address TEXT PRIMARY KEY,
    display_name TEXT,
    total_received INTEGER DEFAULT 0,
    total_sent INTEGER DEFAULT 0,
    last_contact_at REAL,
    avg_reply_time_hours REAL
);

-- Migration v3: Reminders
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id INTEGER NOT NULL,
    remind_at REAL NOT NULL,
    reason TEXT DEFAULT '',
    is_dismissed INTEGER DEFAULT 0,
    FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE CASCADE
);

-- Migration v4: Vector embeddings (future)
CREATE TABLE email_vectors (
    email_id INTEGER PRIMARY KEY,
    embedding BLOB NOT NULL,
    FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE CASCADE
);
```

Each migration is a Python function in `store.py` registered in a `_MIGRATIONS` list.

---

## Encryption Strategy

### What Is Encrypted

Only `accounts.password_enc` is encrypted. Email bodies, subjects, and metadata are stored in plaintext in the local SQLite file. Rationale: the DB is on the user's own disk — encrypting all content would add complexity without meaningful security gain (the user's filesystem permissions are the real boundary).

### Encryption Mechanism

1. **Key derivation**: Read machine UUID from `/etc/machine-id` (Linux), `IOPlatformUUID` (macOS), or `wmic csproduct get uuid` (Windows).
2. **Key transformation**: `hashlib.sha256(machine_uuid.encode()).digest()` → `base64.urlsafe_b64encode(hash[:32])` → `Fernet(key)`.
3. **Fallback**: If machine UUID is unavailable, generate a random key and store at `~/.palimind/email.key` with `0600` permissions.
4. **Encrypt**: `fernet.encrypt(password.encode())` → stored as base64 string in `password_enc`.
5. **Decrypt**: `fernet.decrypt(password_enc.encode()).decode()` → plaintext password for IMAP/SMTP login.

### Threat Model

- **Protects against**: Casual file browsing, database viewers, accidental exposure in backups.
- **Does not protect against**: Root access, memory inspection, dedicated attacker with disk access and machine UUID knowledge.
- **Machine-bound**: Credentials cannot be copied to another machine. This is intentional.

---

## Design Choices Summary

| Decision | Choice | Rationale |
|---|---|---|
| Separate DB file | `~/.palimind/email.db` | Email is global, not per-workspace |
| Tags as CSV string | `TEXT` column | Simpler queries for MVP; normalize in Phase 2 if needed |
| Attachment metadata only | No content blob | Keep DB small; Phase 2 may add content indexing |
| FTS5 content-sync | Triggers | Proven pattern from existing `core/storage/db.py` |
| Schema versioning | `schema_version` table | Enables safe Phase 2 migrations without data loss |
| WAL mode | `PRAGMA journal_mode=WAL` | Matches existing DB conventions; better concurrent read perf |
| Unix timestamps | REAL columns | Efficient range queries; consistent with existing `files.last_indexed` |
| Sender as TEXT | Not normalized | Avoids join-heavy queries; contact normalization deferred to Phase 2 |
