# PaliMind Email Module — Implementation Checklist

## Overview

Ordered implementation checklist from database setup to a fully functioning AI-powered email assistant. Tasks are grouped by phase and ordered by dependency. Each task is independently completable.

**Complexity key**: 🟢 Low | 🟡 Medium | 🔴 High

---

## Phase 1 — MVP

### 1. Foundation

- [ ] **1.1 Create `core/email/` package directory and `__init__.py`**
  - Dependencies: None
  - Complexity: 🟢 Low
  - Acceptance: `from core.email import __init__` succeeds; package recognized by setuptools

- [ ] **1.2 Implement `core/email/exceptions.py`**
  - Dependencies: `core/exceptions.py` (for `PalimindError` base class)
  - Complexity: 🟢 Low
  - Acceptance: All exception classes (`EmailError`, `EmailConnectionError`, `EmailAuthError`, `EmailSyncError`, `EmailSendError`, `EmailNotFoundError`, `EmailCryptoError`, `EmailParseError`) importable and inherit from `PalimindError`

- [ ] **1.3 Implement `core/email/models.py`**
  - Dependencies: None
  - Complexity: 🟢 Low
  - Acceptance: Frozen dataclasses `Account`, `Email`, `Attachment`, `SyncResult`, `SendResult`, `SearchResult` are importable; all fields typed

---

### 2. Credential Security

- [ ] **2.1 Implement `core/email/crypto.py`**
  - Dependencies: `exceptions.py`, `cryptography` package
  - Complexity: 🟡 Medium
  - Acceptance: `encrypt_password("secret")` returns a base64 string; `decrypt_password(enc)` returns `"secret"`; works on Linux, macOS, and fallback mode; `EmailCryptoError` raised on invalid token

- [ ] **2.2 Add `cryptography>=42.0` to `pyproject.toml`**
  - Dependencies: None
  - Complexity: 🟢 Low
  - Acceptance: `pip install -e .` installs cryptography; `python -c "import cryptography"` succeeds

---

### 3. Database Layer

- [ ] **3.1 Implement `core/email/store.py` — schema init**
  - Dependencies: `exceptions.py`, `models.py`
  - Complexity: 🔴 High
  - Acceptance: `init_email_db()` creates `accounts`, `emails`, `attachments`, `sync_state`, `emails_fts`, `schema_version` tables; WAL mode enabled; all indexes created; FTS triggers installed; idempotent (safe to call twice)

- [ ] **3.2 Implement `core/email/store.py` — account CRUD**
  - Dependencies: 3.1, `crypto.py`
  - Complexity: 🟡 Medium
  - Acceptance: `save_account()` stores account with encrypted password; `get_accounts()` returns all accounts; `delete_account()` cascades to emails/sync_state; duplicate label raises error

- [ ] **3.3 Implement `core/email/store.py` — email CRUD**
  - Dependencies: 3.1
  - Complexity: 🟡 Medium
  - Acceptance: `upsert_email()` inserts new email; duplicate `message_id` is ignored; `get_emails()` supports filtering by account, folder, date range, sort; `get_email_by_id()` returns single email; `mark_read()` sets `is_read=1`

- [ ] **3.4 Implement `core/email/store.py` — FTS search**
  - Dependencies: 3.3
  - Complexity: 🟡 Medium
  - Acceptance: `search_fts(query)` returns BM25-ranked results; special characters sanitized; searches subject, body_text, sender; returns snippets

- [ ] **3.5 Implement `core/email/store.py` — sync state**
  - Dependencies: 3.1
  - Complexity: 🟢 Low
  - Acceptance: `update_sync_state(account_id, folder, uid)` upserts; `get_sync_state(account_id, folder)` returns last UID; default 0 for unseen folder

- [ ] **3.6 Write unit tests for `store.py`**
  - Dependencies: 3.1–3.5
  - Complexity: 🟡 Medium
  - Acceptance: All `test_store.py` tests pass; 90%+ coverage on `store.py`

---

### 4. Email Parsing

- [ ] **4.1 Implement `core/email/parser.py` — HTML→text**
  - Dependencies: None (stdlib only)
  - Complexity: 🟡 Medium
  - Acceptance: `html_to_text(html)` strips tags, decodes entities, removes scripts/styles, preserves readability; handles edge cases (empty input, deeply nested tags, malformed HTML)

- [ ] **4.2 Implement `core/email/parser.py` — message parser**
  - Dependencies: 4.1, `models.py`
  - Complexity: 🟡 Medium
  - Acceptance: `parse_message(msg)` extracts all fields (subject, from, to, cc, date, message_id, in_reply_to, references, body_text, body_html, attachments); handles multipart/alternative, multipart/mixed; encoding normalization works

- [ ] **4.3 Implement `core/email/parser.py` — thread ID computation**
  - Dependencies: 4.2
  - Complexity: 🟢 Low
  - Acceptance: `compute_thread_id()` returns consistent thread_id from References/In-Reply-To chain; falls back to message_id if no threading headers

- [ ] **4.4 Write unit tests for `parser.py`**
  - Dependencies: 4.1–4.3, test fixtures (sample .eml files)
  - Complexity: 🟡 Medium
  - Acceptance: All `test_parser.py` tests pass including malformed email edge cases

---

### 5. IMAP Client

- [ ] **5.1 Implement `core/email/imap_client.py`**
  - Dependencies: `exceptions.py`
  - Complexity: 🟡 Medium
  - Acceptance: `IMAPClient` context manager connects via SSL/STARTTLS; `list_folders()` returns folder names; `fetch_messages(folder, uid_start)` returns `EmailMessage` list; `fetch_all(folder, limit)` returns latest N messages; proper cleanup on context exit

- [ ] **5.2 Write unit tests for `imap_client.py`**
  - Dependencies: 5.1, mock IMAP fixture
  - Complexity: 🟡 Medium
  - Acceptance: All `test_imap_client.py` tests pass including connection failure and auth failure

---

### 6. SMTP Client

- [ ] **6.1 Implement `core/email/smtp_client.py`**
  - Dependencies: `exceptions.py`
  - Complexity: 🟡 Medium
  - Acceptance: `send_message()` sends via SSL or STARTTLS; sets Message-ID, Date, In-Reply-To, References headers; handles CC/BCC; raises `EmailSendError` on failure

- [ ] **6.2 Write unit tests for `smtp_client.py`**
  - Dependencies: 6.1, mock SMTP fixture
  - Complexity: 🟡 Medium
  - Acceptance: All `test_smtp_client.py` tests pass including auth failure and connection failure

---

### 7. AI Engine

- [ ] **7.1 Create prompt templates in `core/email/prompts/`**
  - Dependencies: None
  - Complexity: 🟢 Low
  - Acceptance: 6 markdown files created: `summarise.md`, `classify.md`, `priority.md`, `spam.md`, `draft_reply.md`, `draft_compose.md`; each has clear instructions and `{placeholder}` variables

- [ ] **7.2 Implement `core/email/ai.py`**
  - Dependencies: `prompts/`, `core/config.py`
  - Complexity: 🟡 Medium
  - Acceptance: `summarise_email()` returns 2-3 sentences; `classify_tags()` returns list of tags; `score_priority()` returns 0-5; `score_spam()` returns 0-100; `draft_reply()` and `draft_compose()` return draft text; all functions return defaults when Ollama unavailable (never raise)

- [ ] **7.3 Write unit tests for `ai.py`**
  - Dependencies: 7.2, mock Ollama fixture
  - Complexity: 🟡 Medium
  - Acceptance: All `test_ai.py` tests pass; graceful degradation tests pass with mocked connection failures

---

### 8. Facade Layer

- [ ] **8.1 Implement `core/email/api.py`**
  - Dependencies: All modules above (store, imap, smtp, parser, ai, crypto, exceptions, models)
  - Complexity: 🔴 High
  - Acceptance: `add_account()` saves credentials and optionally tests connection; `sync_account()` fetches incrementally, parses, stores, runs AI pipeline; `list_emails()` returns filtered/sorted results; `search_emails()` performs FTS; `compose_email()` and `reply_to_email()` generate drafts and send; all errors wrapped in EmailError hierarchy

- [ ] **8.2 Write integration tests for `api.py`**
  - Dependencies: 8.1, all mock fixtures
  - Complexity: 🔴 High
  - Acceptance: Full sync pipeline test passes; compose pipeline test passes; search test passes; error handling tests pass

---

### 9. CLI Layer

- [ ] **9.1 Implement `core/email/cli.py`**
  - Dependencies: `api.py`, `core/cli/ui.py`
  - Complexity: 🟡 Medium
  - Acceptance: All 9 commands (`add`, `accounts`, `sync`, `list`, `unread`, `read`, `search`, `compose`, `reply`) are registered as `pm email <cmd>`; Rich-formatted output; error messages via `print_error()`; `typer.Exit(1)` on failures

- [ ] **9.2 Register email sub-app in `core/cli/main.py`**
  - Dependencies: 9.1
  - Complexity: 🟢 Low
  - Acceptance: `pm email --help` shows all commands; `pm --help` shows email in command list

- [ ] **9.3 Update `core/email/__init__.py` with public re-exports**
  - Dependencies: All modules
  - Complexity: 🟢 Low
  - Acceptance: `from core.email import add_account, sync_account, EmailError` works

- [ ] **9.4 Write CLI end-to-end tests**
  - Dependencies: 9.1, `typer.testing.CliRunner`
  - Complexity: 🟡 Medium
  - Acceptance: All `test_cli.py` tests pass; each command tested for success and error paths

---

### 10. Polish & Verify

- [ ] **10.1 Run full test suite**
  - Dependencies: All above
  - Complexity: 🟢 Low
  - Acceptance: `python -m pytest core/email/tests/ -v` — all tests pass

- [ ] **10.2 Run manual verification checklist**
  - Dependencies: A real or test email account
  - Complexity: 🟡 Medium
  - Acceptance: All 11 manual verification steps from `email_testing.md` pass

- [ ] **10.3 Verify no regressions in existing PaliMind**
  - Dependencies: None
  - Complexity: 🟢 Low
  - Acceptance: `pm init .`, `pm add .`, `pm ask "test"` still work; no import errors

- [ ] **10.4 Review and finalize documentation**
  - Dependencies: All above
  - Complexity: 🟢 Low
  - Acceptance: All 7 planning docs accurate and consistent with implementation

---

## Phase 2 — Advanced AI

### 11. Semantic Search

- [ ] **11.1 Implement `core/email/semantic.py` — embedding**
  - Dependencies: Phase 1 complete, `core/retrieval/embedder.py` (pattern reference)
  - Complexity: 🔴 High
  - Acceptance: `embed_email(body_text)` returns numpy array via Ollama; `embed_batch(emails)` processes list with progress; embeddings stored in `email_vectors` table

- [ ] **11.2 Implement `core/email/semantic.py` — search**
  - Dependencies: 11.1
  - Complexity: 🟡 Medium
  - Acceptance: `semantic_search(query, top_k=5)` returns top-K emails by cosine similarity; results include email metadata and relevance score

- [ ] **11.3 Implement `pm email ask` command**
  - Dependencies: 11.2, `core/generative/responder.py` (pattern)
  - Complexity: 🟡 Medium
  - Acceptance: `pm email ask "question"` retrieves relevant emails, constructs context, streams answer with source citations; falls back to FTS when vectors unavailable

- [ ] **11.4 Write tests for semantic module**
  - Dependencies: 11.1–11.3
  - Complexity: 🟡 Medium
  - Acceptance: All `test_semantic.py` tests pass including fallback behavior

---

### 12. Background Watcher

- [ ] **12.1 Implement `core/email/watcher.py`**
  - Dependencies: Phase 1 `api.sync_account()`
  - Complexity: 🟡 Medium
  - Acceptance: `start_watching()` polls at configured interval; detects new emails; sends desktop notifications when `--notify` set; `Ctrl+C` stops cleanly; no memory leaks over 1 hour

- [ ] **12.2 Implement `pm email watch` command**
  - Dependencies: 12.1
  - Complexity: 🟢 Low
  - Acceptance: `pm email watch` starts watcher; `pm email watch --notify -i 120` configures interval and notifications

- [ ] **12.3 Write tests for watcher module**
  - Dependencies: 12.1
  - Complexity: 🟡 Medium
  - Acceptance: Mock sync called at correct intervals; notification triggered on new emails; graceful shutdown tested

---

### 13. Contact Analytics

- [ ] **13.1 Add `contact_stats` table migration**
  - Dependencies: Phase 1 `store.py`
  - Complexity: 🟢 Low
  - Acceptance: Migration creates table; existing data untouched

- [ ] **13.2 Implement `core/email/analytics.py` — contact stats**
  - Dependencies: 13.1
  - Complexity: 🟡 Medium
  - Acceptance: `compute_contact_stats()` aggregates from emails table; `get_top_contacts(n)` returns ranked contacts; `needs_reply()` detects unanswered emails

- [ ] **13.3 Implement `core/email/analytics.py` — newsletter detection**
  - Dependencies: 13.2
  - Complexity: 🟡 Medium
  - Acceptance: Detects `List-Unsubscribe` headers; identifies bulk senders; marks contacts as `is_newsletter=1`

- [ ] **13.4 Implement `pm email contacts` command**
  - Dependencies: 13.2, 13.3
  - Complexity: 🟡 Medium
  - Acceptance: `pm email contacts` shows top contacts; `--needs-reply` shows unanswered; `--sort reply-time` sorts by avg reply time

- [ ] **13.5 Implement `pm email newsletters` command**
  - Dependencies: 13.3
  - Complexity: 🟢 Low
  - Acceptance: Lists detected newsletters with frequency info

- [ ] **13.6 Write tests for analytics module**
  - Dependencies: 13.2, 13.3
  - Complexity: 🟡 Medium
  - Acceptance: All `test_analytics.py` tests pass; newsletter detection accuracy > 90% on test set

---

### 14. Reminders

- [ ] **14.1 Add `reminders` table migration**
  - Dependencies: Phase 1 `store.py`
  - Complexity: 🟢 Low
  - Acceptance: Migration creates table with correct indexes

- [ ] **14.2 Implement `core/email/reminders.py`**
  - Dependencies: 14.1
  - Complexity: 🟡 Medium
  - Acceptance: `set_reminder(email_id, remind_at, reason)` creates reminder; `get_due_reminders()` returns overdue; `dismiss_reminder(id)` marks dismissed

- [ ] **14.3 Implement `pm email remind` command**
  - Dependencies: 14.2
  - Complexity: 🟡 Medium
  - Acceptance: `pm email remind 42 --at "tomorrow 9am"` sets reminder; `pm email remind --list` shows pending; `pm email remind --dismiss 1` dismisses

- [ ] **14.4 Integrate reminders into sync and list output**
  - Dependencies: 14.2, Phase 1 `api.py` and `cli.py`
  - Complexity: 🟡 Medium
  - Acceptance: `pm email sync` checks due reminders; `pm email list` shows reminder badges on relevant emails

---

### 15. Daily Digest

- [ ] **15.1 Implement digest generation in `analytics.py`**
  - Dependencies: 13.2, Phase 1 `ai.py`
  - Complexity: 🟡 Medium
  - Acceptance: `generate_digest(period="day")` returns LLM-generated summary of period's emails grouped by action-required, FYI, newsletters

- [ ] **15.2 Implement `pm email digest` command**
  - Dependencies: 15.1
  - Complexity: 🟢 Low
  - Acceptance: `pm email digest` shows today's summary; `pm email digest -p week` shows weekly

---

### 16. Smart Drafting

- [ ] **16.1 Implement style analysis in `ai.py`**
  - Dependencies: Phase 1 `ai.py`, `store.py`
  - Complexity: 🟡 Medium
  - Acceptance: `analyze_writing_style(account_id)` analyzes sent emails for tone, formality, greeting/sign-off patterns; caches style profile

- [ ] **16.2 Integrate style into draft prompts**
  - Dependencies: 16.1
  - Complexity: 🟢 Low
  - Acceptance: AI drafts match user's historical style more closely than Phase 1 generic drafts

---

### 17. Phase 2 Polish

- [ ] **17.1 Run full Phase 2 test suite**
  - Dependencies: All Phase 2 tasks
  - Complexity: 🟢 Low
  - Acceptance: `python -m pytest core/email/tests/ -v` — all tests pass

- [ ] **17.2 Run Phase 2 manual verification**
  - Dependencies: All Phase 2 tasks
  - Complexity: 🟡 Medium
  - Acceptance: All Phase 2 smoke test steps pass

- [ ] **17.3 Verify Phase 1 not regressed**
  - Dependencies: None
  - Complexity: 🟢 Low
  - Acceptance: All Phase 1 CLI commands still work identically

- [ ] **17.4 Performance validation**
  - Dependencies: All Phase 2 tasks
  - Complexity: 🟡 Medium
  - Acceptance: Semantic search < 2s over 5K emails; contact stats < 500ms; watcher no memory leak over 1 hour

---

## Summary Statistics

| Phase | Tasks | 🟢 Low | 🟡 Medium | 🔴 High |
|---|---|---|---|---|
| Phase 1 | 24 | 9 | 12 | 3 |
| Phase 2 | 17 | 5 | 10 | 2 |
| **Total** | **41** | **14** | **22** | **5** |
