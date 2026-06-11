# PaliMind Email Module — Architecture

## Overview

The Email Module extends PaliMind with a local-first, AI-augmented email assistant. All email functionality lives under `core/email/`, isolated from the existing RAG pipeline. It reuses PaliMind's Ollama integration, configuration conventions, CLI framework (Typer + Rich), and prompt template system.

**Design principles:**

- **Local-first**: All data stays on-disk in SQLite. No cloud services beyond the user's own IMAP/SMTP servers.
- **Stateless CLI**: Every command runs to completion — no background daemons required (Phase 1). Phase 2 adds optional polling.
- **AI-optional**: Core fetch/send/search works without Ollama. AI features (summaries, tags, priority, spam scoring) degrade gracefully.
- **Incremental**: Phase 1 delivers a fully usable MVP. Phase 2 layers advanced AI on top without breaking Phase 1.

---

## High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                     CLI Layer (Typer)                    │
│  pm email add | sync | list | read | search | compose   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  Email Facade (api.py)                   │
│  Orchestrates calls between components. Public API for  │
│  CLI commands. Handles error wrapping and config loading.│
└───┬──────────┬──────────┬──────────┬───────────┬────────┘
    │          │          │          │           │
    ▼          ▼          ▼          ▼           ▼
┌───────┐ ┌───────┐ ┌─────────┐ ┌───────┐ ┌─────────┐
│ IMAP  │ │ SMTP  │ │  Store  │ │  AI   │ │ Parser  │
│Client │ │Client │ │ (SQLite)│ │Engine │ │(HTML→   │
│       │ │       │ │         │ │       │ │ text)   │
└───┬───┘ └───┬───┘ └────┬────┘ └───┬───┘ └────┬────┘
    │         │          │          │           │
    ▼         ▼          │          ▼           │
┌───────┐ ┌───────┐     │    ┌──────────┐      │
│Remote │ │Remote │     │    │  Ollama   │      │
│IMAP   │ │SMTP   │     │    │  (local)  │      │
│Server │ │Server │     │    └──────────┘      │
└───────┘ └───────┘     │                      │
                        ▼                      │
                  ┌───────────┐                │
                  │ SQLite DB │◄───────────────┘
                  │ ~/.palimind/               │
                  │  email.db  │               │
                  └───────────┘
```

---

## Component Responsibilities

### 1. CLI Layer — `core/email/cli.py`

- Registers `pm email` as a Typer sub-app on the main `app`
- Each subcommand maps 1:1 to a facade function in `api.py`
- Uses `core/cli/ui.py` helpers (`print_header`, `print_success`, `print_error`, `console`)
- Handles `typer.Exit` codes; never catches domain exceptions silently
- Rich table/panel formatting for `list`, `read`, `search` output

### 2. Email Facade — `core/email/api.py`

- Single entry point for all email operations
- Loads config via `core/config.load_config()`
- Coordinates IMAP → Parser → Store → AI pipeline
- Wraps all failures in domain exceptions (`EmailError` hierarchy)
- Stateless — no module-level mutable state

### 3. IMAP Client — `core/email/imap_client.py`

- Wraps `imaplib.IMAP4_SSL` / `IMAP4`
- Context-manager interface (`with IMAPClient(...) as client:`)
- Methods: `connect()`, `list_folders()`, `fetch_messages()`, `fetch_since()`
- Handles IMAP UID tracking for incremental sync
- Returns raw `email.message.EmailMessage` objects
- Timeout and reconnection handling

### 4. SMTP Client — `core/email/smtp_client.py`

- Wraps `smtplib.SMTP_SSL` / `SMTP` with STARTTLS
- `send_message(to, subject, body, cc=None, bcc=None, reply_to_msg_id=None, references=None)`
- Constructs proper `email.mime` messages with headers
- Sets `In-Reply-To` and `References` for threading

### 5. Email Store — `core/email/store.py`

- Manages `~/.palimind/email.db` (global, not per-workspace)
- SQLite with WAL mode (matching `core/storage/db.py` pattern)
- Tables: `accounts`, `emails`, `emails_fts`, `attachments`, `sync_state`
- CRUD operations for accounts, emails, attachments
- FTS5 full-text search on subject + body_text
- Credential encryption via `core/email/crypto.py`
- Duplicate detection via `message_id` UNIQUE constraint

### 6. AI Engine — `core/email/ai.py`

- Non-streaming LLM calls via `httpx.post` (matching `summariser.py` pattern)
- Functions: `summarise_email()`, `classify_tags()`, `score_priority()`, `score_spam()`, `draft_reply()`, `draft_compose()`
- Loads prompts via `core/email/prompts/` templates
- Graceful degradation: returns empty/default on Ollama failure
- Each function is independently callable

### 7. Parser — `core/email/parser.py`

- Converts `email.message.EmailMessage` → structured dict
- HTML → plaintext via `html.parser.HTMLParser` subclass (stdlib only)
- Extracts: subject, from, to, cc, date, message_id, in_reply_to, references
- Extracts attachment metadata (filename, content_type, size) without saving content
- Handles multipart/alternative, multipart/mixed, nested multipart
- Character encoding detection and normalization

### 8. Crypto — `core/email/crypto.py`

- Encrypts/decrypts IMAP/SMTP passwords at rest
- Uses `cryptography.fernet.Fernet`
- Key derived from machine UUID (`/etc/machine-id` on Linux, platform equivalents)
- Fallback to file-based key at `~/.palimind/email.key`
- Key is machine-bound (intentional — credentials not portable)

---

## Sequence Diagrams

### Account Setup (`pm email add`)

```
User          CLI           Facade         Crypto         Store
 │             │              │              │              │
 │──add ──────▶│              │              │              │
 │             │──add_account▶│              │              │
 │             │              │──encrypt────▶│              │
 │             │              │◀─encrypted───│              │
 │             │              │──save_account────────────▶│
 │             │              │◀─────────ok──────────────│
 │             │──test conn──▶│              │              │
 │             │              │──IMAP login─▶│(IMAP Server) │
 │             │              │◀─ok──────────│              │
 │◀─success────│              │              │              │
```

### Email Sync (`pm email sync`)

```
User     CLI      Facade     Store      IMAP       Parser     AI
 │        │         │          │          │           │         │
 │─sync──▶│         │          │          │           │         │
 │        │─sync───▶│          │          │           │         │
 │        │         │─get_uid─▶│          │           │         │
 │        │         │◀─last_uid│          │           │         │
 │        │         │─fetch_since(uid)───▶│           │         │
 │        │         │◀──raw messages──────│           │         │
 │        │         │─────parse──────────────────────▶│         │
 │        │         │◀────parsed emails──────────────│         │
 │        │         │─────upsert_emails─▶│           │         │
 │        │         │─────summarise/tag/score────────────────▶│
 │        │         │◀────AI results─────────────────────────│
 │        │         │─────update_ai_fields▶│          │         │
 │        │         │─────update_sync_uid──▶│         │         │
 │◀─stats─│         │          │          │           │         │
```

### Compose & Send (`pm email compose` / `pm email reply`)

```
User     CLI      Facade     AI        SMTP       Store
 │        │         │         │          │           │
 │─compose▶│        │         │          │           │
 │        │─draft──▶│         │          │           │
 │        │         │─draft──▶│          │           │
 │        │         │◀─text───│          │           │
 │◀─draft──│        │         │          │           │
 │─confirm▶│        │         │          │           │
 │        │─send───▶│         │          │           │
 │        │         │─send_message──────▶│           │
 │        │         │◀────ok─────────────│           │
 │        │         │─save_sent──────────────────▶│
 │◀─sent───│        │         │          │           │
```

### Search (`pm email search`)

```
User     CLI      Facade     Store
 │        │         │          │
 │─search▶│         │          │
 │        │─search─▶│          │
 │        │         │─FTS5────▶│
 │        │         │◀─results─│
 │◀─table──│        │          │
```

---

## Folder Structure

```
core/email/
├── __init__.py          # Public re-exports
├── api.py               # Facade — orchestrates all operations
├── cli.py               # Typer sub-app for `pm email`
├── imap_client.py       # IMAP connection and fetch
├── smtp_client.py       # SMTP connection and send
├── store.py             # SQLite database layer
├── parser.py            # Email parsing and HTML→text
├── ai.py                # Ollama-powered AI features
├── crypto.py            # Credential encryption
├── exceptions.py        # Email-specific exception hierarchy
├── models.py            # Dataclasses for email domain objects
└── prompts/
    ├── summarise.md     # Email summarisation prompt
    ├── classify.md      # Tag classification prompt
    ├── priority.md      # Priority scoring prompt
    ├── spam.md          # Spam scoring prompt
    ├── draft_reply.md   # Reply drafting prompt
    └── draft_compose.md # Composition drafting prompt
```

---

## Interaction with Existing PaliMind Components

| PaliMind Component | Email Module Usage |
|---|---|
| `core/config.py` | `load_config()` for `ollama_base_url`, `chat_model` |
| `core/cli/main.py` | Register `email_app` sub-command via `app.add_typer()` |
| `core/cli/ui.py` | Reuse `console`, `print_header`, `print_success`, `print_error`, `create_progress` |
| `core/exceptions.py` | `EmailError` extends `PalimindError` |
| `core/prompts/loader.py` | Pattern reference — email uses own prompt dir at `core/email/prompts/` |
| `core/generative/summariser.py` | Pattern reference — `httpx.post` + `stream: False` to Ollama |
| `core/storage/db.py` | Pattern reference — WAL mode, `get_connection()` style, FTS5 triggers |

**Not touched**: `core/storage/db.py`, `core/indexing.py`, `core/retrieval/`, `core/ingestion/`, `core/api_server.py`, `ui/`

---

## Extension Points for Phase 2

1. **`ai.py`** — Add new functions: `detect_needs_reply()`, `daily_digest()`, `semantic_search()`, `analyze_contact()`
2. **`store.py`** — Add tables: `email_vectors`, `contact_stats`, `reminders`; add migration functions
3. **`cli.py`** — Add new subcommands: `pm email watch`, `pm email ask`
4. **`api.py`** — Add facade methods for new AI features
5. **`prompts/`** — Add new prompt templates for advanced AI
6. **`watcher.py`** — New module for background IMAP polling (optional daemon)

---

## Configuration

Email config is stored in the global PaliMind config at `~/.palimind/config.json` under an `"email"` key:

```json
{
  "email": {
    "db_path": "~/.palimind/email.db",
    "sync_batch_size": 50,
    "ai_on_sync": true,
    "default_folder": "INBOX"
  }
}
```

Falls back to sensible defaults if the key is absent — zero configuration needed to start.

---

## Error Handling Strategy

All email exceptions inherit from `PalimindError` via `EmailError`:

```
PalimindError
└── EmailError
    ├── EmailConnectionError     # IMAP/SMTP connection failures
    ├── EmailAuthError           # Authentication failures
    ├── EmailSyncError           # Sync pipeline failures
    ├── EmailSendError           # SMTP send failures
    ├── EmailNotFoundError       # Email ID not in store
    ├── EmailCryptoError         # Credential encryption failures
    └── EmailParseError          # Malformed email parsing failures
```

CLI layer catches `EmailError` subclasses and calls `print_error()` + `typer.Exit(1)`.

---

## Security Model

1. **Credentials at rest**: AES-128 encryption via Fernet. Key derived from machine UUID + SHA-256 + base64.
2. **Credentials in transit**: Direct TLS/SSL to user's IMAP/SMTP servers. No intermediaries.
3. **No cloud dependency**: All processing happens locally. Ollama runs locally.
4. **DB permissions**: `email.db` created with `0600` permissions (owner read/write only).
5. **Key rotation**: Not in Phase 1. Phase 2 may add `pm email rotate-key`.
