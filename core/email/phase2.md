# PaliMind Email Module — Phase 2 (Advanced AI)

## Objectives

Phase 2 layers advanced AI capabilities and automation on top of the Phase 1 MVP. All Phase 1 functionality continues to work unchanged. Phase 2 features are additive — they introduce new modules, new CLI commands, and new database tables without modifying existing Phase 1 code beyond surgical additions.

**Key goals:**

1. Background email polling with optional notifications
2. Semantic Q&A over entire email history (RAG-style)
3. Intelligent inbox prioritization and "needs reply" detection
4. Daily digest summaries and follow-up reminders
5. Contact statistics and relationship analytics
6. Newsletter detection and advanced filtering
7. Smarter drafting based on historical sent mail style analysis
8. Foundation for future vector retrieval and attachment indexing

---

## New Modules

### `core/email/watcher.py` — Background Polling

- Runs IMAP IDLE or periodic polling in a background thread
- Uses `threading.Timer` for polling interval (default: 5 minutes)
- Calls existing `api.sync_account()` on each tick
- Optional desktop notification via `subprocess.run(["notify-send", ...])` on Linux
- Graceful shutdown on SIGINT/SIGTERM
- State persisted via existing `sync_state` table

### `core/email/semantic.py` — Semantic Search & Q&A

- Embeds email bodies using the existing embed model (`nomic-embed-text` via Ollama)
- Stores embeddings in `email_vectors` table (BLOB column)
- Retrieval: cosine similarity search over embeddings
- Q&A: retrieves top-K relevant emails → constructs context → sends to chat model
- Reuses `core/retrieval/embedder.py` pattern for embedding generation
- Reuses `core/generative/responder.py` pattern for streaming answers

### `core/email/analytics.py` — Contact Stats & Analytics

- Aggregates per-contact statistics: total received, total sent, avg reply time
- Newsletter detection heuristic: `List-Unsubscribe` header, bulk sender patterns
- "Needs reply" detection: emails from known contacts with no outgoing reply within N days
- Inbox zero progress tracking
- Daily/weekly digest generation via LLM

### `core/email/reminders.py` — Follow-Up Reminders

- Schedule reminders for specific emails (`remind_at` timestamp)
- `pm email remind` command to set/list/dismiss reminders
- Check due reminders on `pm email sync` or `pm email watch`
- Display overdue reminders on `pm email list` and `pm email unread`

---

## New CLI Commands

### `pm email watch`

Start background polling for new emails.

**Syntax:**
```
pm email watch [OPTIONS]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--account` | `-a` | TEXT | (all) | Account to watch |
| `--interval` | `-i` | INT | 300 | Poll interval in seconds |
| `--notify` | | FLAG | False | Enable desktop notifications |
| `--quiet` | `-q` | FLAG | False | Suppress output except errors |

**Example:**
```bash
# Watch all accounts, notify on new mail
pm email watch --notify

# Watch specific account every 2 minutes
pm email watch -a "Work" -i 120

# Quiet background mode
pm email watch -q &
```

**Expected Output:**
```
╭─ Watching Email ─╮
ℹ Polling every 5 minutes. Press Ctrl+C to stop.
[14:30] ✓ Personal Gmail: 3 new emails
[14:35] ✓ Work: 0 new emails
[14:40] ✓ Personal Gmail: 1 new email
  → "Meeting Tomorrow" from boss@company.com (Priority: ★★★★)
^C
ℹ Watcher stopped.
```

---

### `pm email ask`

Semantic Q&A over your email history using RAG.

**Syntax:**
```
pm email ask <QUESTION> [OPTIONS]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--account` | `-a` | TEXT | (all) | Scope to account |
| `--top-k` | `-k` | INT | 5 | Number of emails to use as context |
| `--after` | | TEXT | — | Only consider emails after date |

**Example:**
```bash
# Ask about your email history
pm email ask "What did John say about the Q4 budget?"

# Scoped question
pm email ask "When is the next team offsite?" -a "Work"
```

**Expected Output:**
```
╭─ Email Q&A ─╮
ℹ Searching 2,345 emails...
ℹ Sources: email #142 (2025-06-01), email #198 (2025-06-05), email #201 (2025-06-07)

Palimind: Based on your email history, John mentioned the Q4 budget in
three emails. In his June 1st email, he proposed a $500K allocation for
engineering. On June 5th, he revised this to $450K after the CFO review.
The latest email (June 7th) confirms the $450K figure was approved.
```

---

### `pm email digest`

Generate a daily/weekly digest summary.

**Syntax:**
```
pm email digest [OPTIONS]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--period` | `-p` | TEXT | day | Period: day, week |
| `--account` | `-a` | TEXT | (all) | Scope to account |

---

### `pm email remind`

Set or list follow-up reminders.

**Syntax:**
```
pm email remind <EMAIL_ID> [OPTIONS]
pm email remind --list
pm email remind --dismiss <REMINDER_ID>
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--at` | | TEXT | — | Reminder time (e.g., "tomorrow 9am", "2025-06-15") |
| `--reason` | `-r` | TEXT | — | Why you need to follow up |
| `--list` | | FLAG | False | List all pending reminders |
| `--dismiss` | | INT | — | Dismiss a reminder by ID |

---

### `pm email contacts`

Show contact statistics and analytics.

**Syntax:**
```
pm email contacts [OPTIONS]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--top` | `-n` | INT | 10 | Number of contacts to show |
| `--sort` | `-s` | TEXT | frequency | Sort: frequency, recency, reply-time |
| `--needs-reply` | | FLAG | False | Show contacts awaiting your reply |

---

### `pm email newsletters`

List detected newsletters with management options.

**Syntax:**
```
pm email newsletters [OPTIONS]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--unsubscribe` | | INT | — | Mark newsletter ID for unsubscribe |

---

## Data Flow

### Semantic Q&A Pipeline

```
pm email ask "What did John say about Q4?"
      │
      ▼
┌─── api.py ──────────────────────────────────────────┐
│                                                      │
│  1. Embed the question via embedder                  │
│  2. Cosine similarity search over email_vectors      │
│  3. Retrieve top-K email bodies as context           │
│  4. Construct RAG prompt: system + context + question │
│  5. Stream response from Ollama chat model           │
│  6. Display with source citations                    │
└──────────────────────────────────────────────────────┘
```

### Background Watcher Pipeline

```
pm email watch --notify
      │
      ▼
┌─── watcher.py ──────────────────────────────────────┐
│                                                      │
│  Loop every N seconds:                               │
│    1. Call sync_account() for each account            │
│    2. Check SyncResult.new_emails count              │
│    3. If new_emails > 0 and --notify:                │
│       a. Check for high-priority emails              │
│       b. Check for "needs reply" emails              │
│       c. Send desktop notification                   │
│    4. Check due reminders                            │
│       a. Display overdue reminders                   │
│    5. Sleep for interval                             │
│                                                      │
│  On SIGINT: clean shutdown                           │
└──────────────────────────────────────────────────────┘
```

### Contact Analytics Pipeline

```
pm email contacts --needs-reply
      │
      ▼
┌─── analytics.py ────────────────────────────────────┐
│                                                      │
│  1. Query contact_stats table                        │
│  2. For --needs-reply:                               │
│     a. Find received emails with no sent reply       │
│     b. Filter by age threshold (e.g., > 2 days)      │
│     c. Exclude newsletters and automated senders     │
│  3. Return sorted contact list                       │
└──────────────────────────────────────────────────────┘
```

---

## New Database Tables

### `email_vectors`

```sql
CREATE TABLE email_vectors (
    email_id   INTEGER PRIMARY KEY,
    embedding  BLOB NOT NULL,
    model_name TEXT NOT NULL DEFAULT 'nomic-embed-text',
    created_at REAL NOT NULL,
    FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE CASCADE
);
```

### `contact_stats`

```sql
CREATE TABLE contact_stats (
    email_address     TEXT PRIMARY KEY,
    display_name      TEXT DEFAULT '',
    total_received    INTEGER DEFAULT 0,
    total_sent        INTEGER DEFAULT 0,
    last_received_at  REAL,
    last_sent_at      REAL,
    avg_reply_time_hours REAL,
    is_newsletter     INTEGER DEFAULT 0,
    updated_at        REAL NOT NULL
);
```

### `reminders`

```sql
CREATE TABLE reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id     INTEGER NOT NULL,
    remind_at    REAL NOT NULL,
    reason       TEXT DEFAULT '',
    is_dismissed INTEGER DEFAULT 0,
    created_at   REAL NOT NULL,
    FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE CASCADE
);
CREATE INDEX idx_reminders_due ON reminders(remind_at) WHERE is_dismissed = 0;
```

---

## Upgrade Path

### From Phase 1 to Phase 2

1. **No breaking changes**: All Phase 1 CLI commands, database schema, and APIs remain identical.
2. **Schema migration**: `init_email_db()` applies new migrations (v2, v3, v4) automatically on first run after upgrade.
3. **Vector backfill**: `pm email ask` on first use triggers embedding generation for existing emails (batch process with progress bar).
4. **Contact stats backfill**: `pm email contacts` on first use aggregates stats from existing `emails` table.
5. **Config additions**: New optional keys under `config.json` → `email`:
   ```json
   {
     "email": {
       "watch_interval": 300,
       "needs_reply_threshold_days": 2,
       "newsletter_auto_detect": true,
       "digest_time": "08:00",
       "embed_on_sync": true
     }
   }
   ```

### Backward Compatibility

- Phase 2 code checks for new tables/columns before using them.
- If `email_vectors` table is empty, `pm email ask` falls back to FTS5 search.
- If `contact_stats` is empty, `pm email contacts` computes stats on-the-fly from `emails`.
- All new CLI commands are additive — no existing command signatures change.

---

## Compatibility Requirements

| Requirement | Details |
|---|---|
| Python | ≥ 3.10 (same as Phase 1) |
| SQLite | ≥ 3.35 (for FTS5 + JSON functions) |
| Ollama | Required for semantic Q&A; optional for all other Phase 2 features |
| New dependencies | None beyond Phase 1 (`cryptography`, `httpx` already present) |
| Existing `core/` | No modifications to non-email modules |
| Phase 1 DB | Auto-migrated; no manual steps |

---

## Performance Expectations

| Operation | Target | Notes |
|---|---|---|
| Embedding 1 email | < 500ms | Via Ollama `nomic-embed-text` |
| Backfill 1000 emails | < 10 minutes | Batch embedding with progress bar |
| Semantic search (top-5) | < 2 seconds | Cosine similarity over numpy arrays |
| Contact stats query | < 500ms | Pre-aggregated in `contact_stats` table |
| Newsletter detection | < 100ms | Header-based heuristic, no LLM |
| "Needs reply" query | < 1 second | SQL query with date filter |
| Daily digest generation | < 30 seconds | LLM summarization of day's emails |
| Watch poll cycle | < 10 seconds | Incremental sync + notification |

---

## Testing Strategy

### Unit Tests

- `semantic.py`: Mock embedder, test cosine similarity, test context assembly
- `analytics.py`: Test contact aggregation, newsletter detection heuristics, needs-reply logic
- `reminders.py`: Test CRUD, due-date filtering, dismissal
- `watcher.py`: Mock sync, test notification trigger logic, test graceful shutdown

### Integration Tests

- **Semantic Q&A end-to-end**: Embed sample emails → ask question → verify relevant context retrieved
- **Watch + sync**: Start watcher → inject new email via mock IMAP → verify detection
- **Contact stats backfill**: Populate emails table → run contacts → verify aggregation accuracy
- **Schema migration**: Create Phase 1 DB → run Phase 2 init → verify new tables exist + old data intact

### Stress Tests

- Semantic search over 10,000 embedded emails — verify < 5 second response
- Contact stats computation over 50,000 emails — verify < 10 seconds
- Watcher running for 1 hour with 5-minute intervals — verify no memory leak

### Edge Cases

- `pm email ask` with empty vector store → falls back to FTS5
- `pm email watch` with no accounts → clear error message
- `pm email contacts --needs-reply` with no sent emails → empty result
- `pm email digest` with no emails in period → "No emails to summarize"
- Schema migration on corrupted DB → rollback and error message

---

## Features Detail

### Automatic Polling (`pm email watch`)

- Uses `threading.Timer` for periodic execution (no external scheduler)
- Calls existing `api.sync_account()` — reuses Phase 1 sync pipeline
- Tracks new emails per cycle for notification
- Desktop notifications via `notify-send` (Linux), `osascript` (macOS)
- `Ctrl+C` for graceful shutdown

### Semantic Email Q&A (`pm email ask`)

- Embeds emails using existing `nomic-embed-text` model via Ollama
- Embeddings stored as numpy arrays serialized to BLOB
- Retrieval: brute-force cosine similarity (sufficient for < 100K emails)
- Phase 3 future: could add FAISS or pgvector for scale
- Context window: top-K emails concatenated with metadata (sender, date, subject)
- Response streamed to terminal (matching existing `pm ask` pattern)

### "Needs Reply" Detection

- SQL query: received emails with no corresponding sent email to the same sender within N days
- Excludes: newsletters, no-reply addresses, automated senders
- Configurable threshold via `needs_reply_threshold_days`

### Inbox Prioritization

- Combines Phase 1 priority score with:
  - Contact frequency (more frequent = higher priority)
  - Reply urgency (needs-reply = boost)
  - Newsletter penalty (detected newsletters = lower priority)
- Composite score stored in `emails.priority` (updated by analytics)

### Daily Summaries

- LLM-generated digest of the day's/week's emails
- Groups by: action-required, FYI, newsletters
- Includes: top contacts, unread count, needs-reply list
- Output to terminal or saved as markdown file

### Follow-Up Reminders

- User sets reminder: `pm email remind 42 --at "tomorrow 9am" -r "Follow up on proposal"`
- Checked on every `pm email sync` and `pm email watch` tick
- Overdue reminders displayed prominently at top of `pm email list`

### Contact Statistics

- Pre-aggregated in `contact_stats` table, updated on each sync
- Metrics: total emails (in/out), last contact date, average reply time
- Newsletter flag based on `List-Unsubscribe` header and bulk sender patterns

### Smarter Drafting

- Analyzes user's sent mail history for tone, greeting style, sign-off patterns
- Extracts style profile: formality level, average length, common phrases
- Feeds style profile into draft prompts for more personalized AI output
- Style profile cached in config, refreshed periodically

### Future: Attachment Indexing

- Extract text from PDF/DOCX attachments (reusing `core/ingestion/doc_parser.py`)
- Store extracted text in `attachment_content` table
- Include in FTS and semantic search
- Deferred to Phase 3 due to storage and complexity implications

### Future: Vector Retrieval

- Replace brute-force cosine similarity with approximate nearest neighbor
- Options: FAISS (numpy-based), or custom `turbovec` integration
- Deferred to Phase 3 based on scale requirements
