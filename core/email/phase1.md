# PaliMind Email Module — Phase 1 (MVP)

## Objectives

Deliver a fully functional, local-first email assistant that works entirely from the command line without background services. Phase 1 must be independently usable and production-worthy.

**Key goals:**

1. Add, manage, and sync multiple IMAP email accounts
2. Fetch, list, read, and search emails locally
3. Compose and reply via SMTP with optional AI-assisted drafting
4. AI-powered summarization, tagging, priority scoring, and spam detection
5. Encrypted credential storage
6. Full-text keyword search via FTS5
7. All operations are stateless CLI commands — no daemons

---

## Folder Structure

```
core/email/
├── __init__.py          # Public re-exports: EmailError, add_account, sync, ...
├── api.py               # Facade layer — orchestrates all operations
├── cli.py               # Typer sub-app: pm email <command>
├── imap_client.py       # IMAP fetch logic (imaplib wrapper)
├── smtp_client.py       # SMTP send logic (smtplib wrapper)
├── store.py             # SQLite DB init, CRUD, FTS queries
├── parser.py            # email.message → structured dict, HTML→plaintext
├── ai.py                # Ollama AI: summarise, tag, priority, spam, draft
├── crypto.py            # Fernet credential encryption
├── exceptions.py        # EmailError hierarchy (extends PalimindError)
├── models.py            # Dataclasses: Email, Account, Attachment, SyncResult
└── prompts/
    ├── summarise.md     # "Summarise this email in 2-3 sentences..."
    ├── classify.md      # "Classify this email with tags from: ..."
    ├── priority.md      # "Rate the priority of this email 0-5..."
    ├── spam.md          # "Score the spam likelihood 0-100..."
    ├── draft_reply.md   # "Draft a reply to this email. Intent: {intent}..."
    └── draft_compose.md # "Draft an email. Intent: {intent}..."
```

---

## Database Schema (Summary)

> Full schema details in [email_database.md](./email_database.md)

| Table | Purpose |
|---|---|
| `accounts` | IMAP/SMTP credentials (password encrypted) |
| `emails` | All fetched/sent emails with AI metadata |
| `attachments` | Attachment metadata (filename, type, size) |
| `sync_state` | Last IMAP UID per account/folder |
| `emails_fts` | FTS5 index on subject + body_text + sender |
| `schema_version` | Migration tracking |

---

## Data Flow Diagrams

### Sync Pipeline

```
pm email sync
      │
      ▼
┌─── Facade (api.py) ───────────────────────────────────────────┐
│                                                                │
│  1. Load account credentials from store                        │
│  2. Decrypt password via crypto.py                             │
│  3. Connect to IMAP server                                     │
│  4. Get last_uid from sync_state                               │
│  5. Fetch messages with UID > last_uid                         │
│  6. For each raw message:                                      │
│     a. Parse headers + body via parser.py                      │
│     b. Convert HTML → plaintext                                │
│     c. Extract attachment metadata                             │
│     d. Compute thread_id from References/In-Reply-To chain     │
│     e. INSERT OR IGNORE into emails table (dedup on message_id)│
│     f. INSERT attachment metadata                              │
│  7. If AI enabled:                                             │
│     a. Summarise each new email                                │
│     b. Classify tags                                           │
│     c. Score priority (0-5)                                    │
│     d. Score spam (0-100)                                      │
│     e. UPDATE emails with AI fields                            │
│  8. Update sync_state with new last_uid                        │
│  9. Return SyncResult                                          │
└────────────────────────────────────────────────────────────────┘
```

### Compose/Send Pipeline

```
pm email compose --ai-draft "..."
      │
      ▼
┌─── Facade (api.py) ───────────────────────────┐
│                                                │
│  1. If --ai-draft: call ai.draft_compose()     │
│  2. Present draft to user for confirmation     │
│  3. On confirm:                                │
│     a. Decrypt SMTP password                   │
│     b. Connect to SMTP server                  │
│     c. Build MIME message with proper headers   │
│     d. Send via SMTP                           │
│     e. Save to emails table (is_sent=1)        │
│  4. Return SendResult                          │
└────────────────────────────────────────────────┘
```

### Search Pipeline

```
pm email search "query"
      │
      ▼
┌─── Facade (api.py) ──────────────────────┐
│                                           │
│  1. Sanitize query for FTS5 safety        │
│  2. Execute FTS5 MATCH against emails_fts │
│  3. JOIN with emails for metadata         │
│  4. Apply account/folder/date filters     │
│  5. Return ranked results with snippets   │
└───────────────────────────────────────────┘
```

---

## CLI Command Specifications

> Full command reference in [email_cli.md](./email_cli.md)

| Command | Description |
|---|---|
| `pm email add` | Add email account (interactive password, test connection) |
| `pm email accounts` | List all configured accounts with last-sync time |
| `pm email sync` | Incremental IMAP fetch + AI processing |
| `pm email list` | Tabular email listing with filters and sort |
| `pm email unread` | Unread email list or count |
| `pm email read` | Full email display with metadata |
| `pm email search` | FTS5 keyword search with BM25 ranking |
| `pm email compose` | New email with optional AI draft |
| `pm email reply` | Reply (or reply-all) with optional AI draft |

---

## Module Responsibilities

### `api.py` — Facade

- **Public functions**: `add_account()`, `list_accounts()`, `sync_account()`, `list_emails()`, `get_email()`, `search_emails()`, `unread_emails()`, `compose_email()`, `reply_to_email()`, `send_email()`
- Loads config via `core.config.load_config()`
- Coordinates IMAP, SMTP, Store, AI, Parser, Crypto
- Never raises raw exceptions — wraps in `EmailError` hierarchy

### `imap_client.py` — IMAP Fetch

- **Public API**: `IMAPClient` context manager with `connect()`, `list_folders()`, `fetch_messages(folder, uid_start)`, `fetch_all(folder, limit)`
- Uses `imaplib.IMAP4_SSL` (or `IMAP4` with STARTTLS)
- Returns list of `email.message.EmailMessage`
- Handles UID-based incremental fetch: `UID FETCH {last_uid+1}:*`
- Connection timeout: 30 seconds
- Graceful cleanup on context exit

### `smtp_client.py` — SMTP Send

- **Public API**: `send_message(host, port, username, password, message, use_ssl)`
- Accepts a constructed `email.mime.multipart.MIMEMultipart` or `MIMEText`
- Handles STARTTLS and direct SSL
- Sets proper `Message-ID`, `Date`, `In-Reply-To`, `References` headers
- Connection timeout: 30 seconds

### `store.py` — Database

- **Public API**: `init_email_db()`, `get_connection()`, `save_account()`, `get_accounts()`, `upsert_email()`, `get_emails()`, `get_email_by_id()`, `search_fts()`, `update_ai_fields()`, `update_sync_state()`, `get_sync_state()`, `mark_read()`, `get_unread_count()`
- Schema init is idempotent
- Uses `INSERT OR IGNORE` on `message_id` for dedup
- FTS5 with content-sync triggers

### `parser.py` — Email Parsing

- **Public API**: `parse_message(msg: EmailMessage) -> dict`, `html_to_text(html: str) -> str`, `compute_thread_id(references: str, in_reply_to: str, message_id: str) -> str`
- Extracts all header fields into structured dict
- Handles multipart/alternative (prefers text/plain, falls back to HTML→text)
- Extracts attachment metadata without saving content
- Character encoding normalization (handles UTF-8, ISO-8859-1, etc.)
- `html_to_text()` uses `html.parser.HTMLParser` subclass — no external dependency

### `ai.py` — AI Engine

- **Public API**: `summarise_email(body_text) -> str`, `classify_tags(subject, body_text) -> list[str]`, `score_priority(subject, body_text, sender) -> int`, `score_spam(subject, body_text, sender) -> int`, `draft_reply(original, intent) -> str`, `draft_compose(intent, recipient) -> str`
- Uses `httpx.post()` to Ollama `/api/chat` (matching `core/generative/summariser.py`)
- `stream: False` for all calls
- Loads config: `ollama_base_url` and `chat_model` from `core.config`
- Loads prompt templates from `core/email/prompts/`
- **Graceful degradation**: Returns empty/default on Ollama failure (never raises)

### `crypto.py` — Credential Encryption

- **Public API**: `encrypt_password(plaintext) -> str`, `decrypt_password(ciphertext) -> str`
- Fernet encryption with machine-bound key
- Key sources: `/etc/machine-id` → SHA-256 → base64 → Fernet key
- Fallback: file-based key at `~/.palimind/email.key`

### `exceptions.py` — Error Hierarchy

- All inherit from `PalimindError` → `EmailError`
- Specific subclasses: `EmailConnectionError`, `EmailAuthError`, `EmailSyncError`, `EmailSendError`, `EmailNotFoundError`, `EmailCryptoError`, `EmailParseError`

### `models.py` — Data Models

- `@dataclass(frozen=True)` style matching `core/models.py`
- Classes: `Account`, `Email`, `Attachment`, `SyncResult`, `SendResult`, `SearchResult`

---

## Error Handling

| Layer | Strategy |
|---|---|
| `imap_client.py` | Catches `imaplib.IMAP4.error`, `socket.timeout`, `ConnectionRefusedError` → raises `EmailConnectionError` or `EmailAuthError` |
| `smtp_client.py` | Catches `smtplib.SMTPException` family → raises `EmailSendError` |
| `store.py` | Catches `sqlite3.Error` → raises `EmailSyncError` |
| `parser.py` | Catches encoding errors, malformed MIME → raises `EmailParseError` |
| `ai.py` | Catches `httpx.HTTPError`, `json.JSONDecodeError` → returns default (never raises) |
| `crypto.py` | Catches `cryptography.fernet.InvalidToken` → raises `EmailCryptoError` |
| `api.py` | Catches component exceptions, wraps in `EmailError` with context |
| `cli.py` | Catches `EmailError` → `print_error()` + `typer.Exit(1)` |

---

## Security Considerations

1. **Password handling**: Never logged, never printed. `--password` option is hidden in `--help` output. Prefer interactive prompt.
2. **Credential storage**: Fernet AES encryption keyed from machine UUID. DB file `0600` permissions.
3. **Network security**: TLS/SSL enforced by default. `--no-ssl` flag requires explicit opt-in.
4. **Prompt injection**: AI prompts are system-role messages. Email content goes in user-role. AI output is displayed, never executed.
5. **SQL injection**: All queries use parameterized statements. FTS query sanitization strips special characters.
6. **File permissions**: `email.db` and `email.key` created with restrictive permissions.

---

## Step-by-Step Implementation Order

| Step | Module | Depends On | Complexity |
|---|---|---|---|
| 1 | `exceptions.py` | — | Low |
| 2 | `models.py` | — | Low |
| 3 | `crypto.py` | — | Medium |
| 4 | `store.py` (schema + CRUD) | exceptions, models, crypto | High |
| 5 | `parser.py` | models | Medium |
| 6 | `imap_client.py` | exceptions | Medium |
| 7 | `smtp_client.py` | exceptions | Medium |
| 8 | `prompts/*.md` | — | Low |
| 9 | `ai.py` | prompts | Medium |
| 10 | `api.py` (facade) | all above | High |
| 11 | `cli.py` | api | Medium |
| 12 | `__init__.py` + main.py registration | cli | Low |

---

## Testing Checklist

> Full testing details in [email_testing.md](./email_testing.md)

- [ ] `crypto.py`: encrypt/decrypt round-trip, invalid key handling
- [ ] `store.py`: schema creation, CRUD, FTS, dedup, migrations
- [ ] `parser.py`: multipart emails, HTML→text, encoding edge cases
- [ ] `imap_client.py`: mock IMAP server, incremental fetch, timeout
- [ ] `smtp_client.py`: mock SMTP server, STARTTLS, SSL
- [ ] `ai.py`: Ollama available, Ollama unavailable (graceful fallback)
- [ ] `api.py`: full sync pipeline, compose pipeline, search
- [ ] `cli.py`: all 9 commands end-to-end

---

## Manual Verification

```bash
# 1. Add a test account
pm email add -l "Test" -e test@example.com \
  --imap-host imap.example.com --smtp-host smtp.example.com

# 2. Verify account persists
pm email accounts

# 3. Sync inbox
pm email sync -a "Test"

# 4. List emails
pm email list

# 5. Read an email
pm email read 1

# 6. Check unread count
pm email unread -c

# 7. Search
pm email search "meeting"

# 8. AI-assisted reply
pm email reply 1 --ai-draft "confirm attendance"

# 9. Compose new email
pm email compose -a "Test" --to "friend@example.com" -s "Hello" \
  --ai-draft "casual greeting, ask how they're doing" --dry-run
```

---

## Success Criteria

| Criterion | Measurement |
|---|---|
| Account management | Add, list, delete accounts with encrypted credentials |
| Incremental sync | Only fetches emails newer than last UID |
| Duplicate detection | Re-syncing the same folder produces zero duplicates |
| HTML → plaintext | Complex HTML emails render as readable text |
| FTS search | Keyword search returns relevant results ranked by BM25 |
| AI summaries | Each synced email gets a 2-3 sentence summary (when Ollama is available) |
| AI tags | Each email gets 1-5 relevant tags |
| AI priority | Score 0-5 assigned based on content analysis |
| AI spam score | Score 0-100 assigned based on content analysis |
| AI draft | Compose/reply generates coherent draft matching intent |
| Graceful degradation | All features work without Ollama (AI fields remain empty) |
| Error recovery | Connection failures, auth errors, and parse errors produce clear messages |
| Security | Passwords encrypted at rest, DB file has restrictive permissions |
| Performance | Sync of 50 emails completes in under 60 seconds (excluding AI) |
| CLI output | All commands produce Rich-formatted, readable output |
