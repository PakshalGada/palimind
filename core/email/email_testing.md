# PaliMind Email Module — Testing Plan

## Overview

This document defines the complete testing strategy for the Email Module across both phases. Tests are organized by category: unit, integration, stress, and edge-case testing. Each section includes specific test scenarios and exact commands where applicable.

---

## Test Infrastructure

### Test Utilities

Create `core/email/tests/conftest.py` with shared fixtures:

- `tmp_db`: Creates a temporary SQLite DB, yields path, cleans up
- `mock_imap`: Patched `imaplib.IMAP4_SSL` returning canned responses
- `mock_smtp`: Patched `smtplib.SMTP_SSL` capturing sent messages
- `mock_ollama`: `httpx` transport mock returning canned AI responses
- `sample_emails`: Pre-built `email.message.EmailMessage` objects (plain, HTML, multipart, attachments)
- `populated_db`: DB pre-filled with 100 sample emails

### Test File Structure

```
core/email/tests/
├── __init__.py
├── conftest.py              # Shared fixtures
├── test_crypto.py           # Credential encryption
├── test_store.py            # Database operations
├── test_parser.py           # Email parsing
├── test_imap_client.py      # IMAP fetch logic
├── test_smtp_client.py      # SMTP send logic
├── test_ai.py               # AI engine
├── test_api.py              # Facade integration
├── test_cli.py              # CLI end-to-end
├── test_stress.py           # Performance tests
├── test_semantic.py         # Phase 2: semantic search
├── test_analytics.py        # Phase 2: contact analytics
└── fixtures/
    ├── plain_email.eml      # Sample plain-text email
    ├── html_email.eml       # Sample HTML email
    ├── multipart_email.eml  # Sample multipart/mixed
    ├── malformed_email.eml  # Intentionally broken email
    ├── unicode_email.eml    # Non-ASCII content
    └── attachment_email.eml # Email with attachments
```

### Running Tests

```bash
# Run all email tests
python -m pytest core/email/tests/ -v

# Run specific category
python -m pytest core/email/tests/test_store.py -v

# Run with coverage
python -m pytest core/email/tests/ --cov=core.email --cov-report=term-missing

# Run stress tests (slower)
python -m pytest core/email/tests/test_stress.py -v --timeout=120
```

---

## Unit Test Plan

### 1. `test_crypto.py` — Credential Encryption

| Test | Description | Expected |
|---|---|---|
| `test_encrypt_decrypt_roundtrip` | Encrypt a password, then decrypt it | Original password recovered |
| `test_different_passwords_different_ciphertexts` | Encrypt two different passwords | Ciphertexts differ |
| `test_same_password_different_ciphertexts` | Encrypt same password twice | Ciphertexts differ (Fernet uses random IV) |
| `test_decrypt_invalid_token` | Decrypt garbage data | Raises `EmailCryptoError` |
| `test_decrypt_wrong_key` | Decrypt with a different Fernet key | Raises `EmailCryptoError` |
| `test_empty_password` | Encrypt empty string | Works (empty string encrypted/decrypted) |
| `test_unicode_password` | Encrypt password with Unicode chars | Round-trip preserves Unicode |
| `test_long_password` | Encrypt 1000-char password | Round-trip works |
| `test_key_derivation_deterministic` | Same machine UUID → same key | Keys match |
| `test_fallback_key_file_created` | No machine UUID available | Key file created at expected path |

---

### 2. `test_store.py` — Database Operations

| Test | Description | Expected |
|---|---|---|
| `test_init_db_creates_tables` | Call `init_email_db()` on fresh DB | All tables exist |
| `test_init_db_idempotent` | Call `init_email_db()` twice | No errors, no duplicates |
| `test_save_account` | Insert a new account | Account retrievable by label |
| `test_save_account_duplicate_label` | Insert two accounts with same label | Raises error |
| `test_get_accounts_empty` | Query accounts on fresh DB | Empty list |
| `test_get_accounts_multiple` | Insert 3 accounts, query all | Returns all 3 |
| `test_upsert_email_new` | Insert a new email | Email stored with all fields |
| `test_upsert_email_duplicate_message_id` | Insert email with existing message_id | Ignored (no error, no duplicate) |
| `test_upsert_email_updates_ai_fields` | Update summary/tags/priority/spam for existing email | Fields updated |
| `test_get_emails_sorted_by_date` | Query emails with date sort | Newest first |
| `test_get_emails_filtered_by_folder` | Query emails filtered by folder | Only matching folder |
| `test_get_emails_filtered_by_account` | Query emails filtered by account_id | Only matching account |
| `test_get_email_by_id` | Fetch single email by ID | Correct email returned |
| `test_get_email_by_id_not_found` | Fetch non-existent ID | Returns None |
| `test_fts_search_subject` | Search for term in subject | Matching emails found |
| `test_fts_search_body` | Search for term in body | Matching emails found |
| `test_fts_search_sender` | Search for sender name | Matching emails found |
| `test_fts_search_no_results` | Search for non-existent term | Empty results |
| `test_fts_search_special_chars` | Search with quotes, backslashes | Sanitized, no SQL error |
| `test_fts_search_ranking` | Search term appearing in multiple emails | Results ranked by relevance |
| `test_mark_read` | Mark email as read | `is_read = 1` |
| `test_get_unread_count` | Count unread emails | Correct count |
| `test_update_sync_state` | Set last_uid for account/folder | State persisted |
| `test_get_sync_state` | Retrieve last_uid | Correct value |
| `test_sync_state_upsert` | Update existing sync state | Value updated, not duplicated |
| `test_delete_account_cascades` | Delete account | All associated emails, attachments, sync_state deleted |
| `test_schema_version_tracking` | Check version after init | Version set to latest |
| `test_migration_v1_to_v2` | Create v1 schema, run v2 migration | New tables exist, old data intact |

---

### 3. `test_parser.py` — Email Parsing

| Test | Description | Expected |
|---|---|---|
| `test_parse_plain_text` | Parse simple text/plain email | Subject, from, to, body_text extracted |
| `test_parse_html_only` | Parse email with only HTML body | HTML converted to readable text |
| `test_parse_multipart_alternative` | Parse multipart/alternative (text + HTML) | Prefers text/plain |
| `test_parse_multipart_mixed` | Parse email with body + attachments | Body extracted, attachments listed |
| `test_parse_nested_multipart` | Parse deeply nested multipart structure | Correctly traversed |
| `test_html_to_text_basic` | Convert simple HTML | Tags stripped, text preserved |
| `test_html_to_text_links` | Convert HTML with `<a>` tags | Link text preserved |
| `test_html_to_text_lists` | Convert HTML with `<ul>/<li>` | Formatted as text list |
| `test_html_to_text_tables` | Convert HTML with `<table>` | Readable text layout |
| `test_html_to_text_entities` | Convert `&amp;`, `&lt;`, etc. | Entities decoded |
| `test_html_to_text_styles` | Convert HTML with `<style>` blocks | Style content removed |
| `test_html_to_text_scripts` | Convert HTML with `<script>` blocks | Script content removed |
| `test_parse_utf8_body` | Parse email with UTF-8 content | Correctly decoded |
| `test_parse_iso8859_body` | Parse email with ISO-8859-1 | Correctly transcoded to UTF-8 |
| `test_parse_missing_charset` | Parse email with no charset declaration | Best-effort decode |
| `test_parse_date_formats` | Parse various date header formats | All parsed to Unix timestamp |
| `test_parse_missing_subject` | Parse email with no Subject header | Subject = '' |
| `test_parse_missing_from` | Parse email with no From header | Handled gracefully |
| `test_compute_thread_id` | Compute thread from References chain | Consistent thread_id |
| `test_compute_thread_id_no_references` | No References or In-Reply-To | Uses message_id as thread_id |
| `test_parse_attachment_metadata` | Extract attachment filename, type, size | Correct metadata |
| `test_parse_inline_attachment` | Detect inline image (Content-Disposition: inline) | Marked as attachment |
| `test_parse_no_attachments` | Parse email without attachments | Empty attachment list, has_attachments=0 |

---

### 4. `test_imap_client.py` — IMAP Fetch

| Test | Description | Expected |
|---|---|---|
| `test_connect_ssl` | Connect with SSL | Connection established |
| `test_connect_starttls` | Connect with STARTTLS | Connection established |
| `test_connect_refused` | Connect to dead server | Raises `EmailConnectionError` |
| `test_connect_auth_fail` | Connect with wrong password | Raises `EmailAuthError` |
| `test_connect_timeout` | Connect to non-responsive server | Raises `EmailConnectionError` after timeout |
| `test_list_folders` | List IMAP folders | Returns folder names |
| `test_fetch_messages` | Fetch N messages from INBOX | Returns list of EmailMessage |
| `test_fetch_since_uid` | Fetch messages with UID > X | Only newer messages returned |
| `test_fetch_empty_folder` | Fetch from empty folder | Returns empty list |
| `test_context_manager_cleanup` | Use IMAPClient in `with` block | Connection closed on exit |
| `test_context_manager_exception` | Exception inside `with` block | Connection still closed |

---

### 5. `test_smtp_client.py` — SMTP Send

| Test | Description | Expected |
|---|---|---|
| `test_send_simple` | Send plain text email | Message delivered to mock SMTP |
| `test_send_with_cc_bcc` | Send with CC and BCC | All recipients in envelope |
| `test_send_reply` | Send with In-Reply-To header | Header correctly set |
| `test_send_ssl` | Send via direct SSL (port 465) | Connection uses SSL |
| `test_send_starttls` | Send via STARTTLS (port 587) | STARTTLS negotiated |
| `test_send_auth_fail` | Send with wrong password | Raises `EmailSendError` |
| `test_send_connection_refused` | Send to dead server | Raises `EmailSendError` |
| `test_send_invalid_recipient` | Send to malformed address | Raises `EmailSendError` |
| `test_message_id_generated` | Send message without explicit Message-ID | Auto-generated Message-ID in headers |
| `test_date_header_set` | Send message | Date header present and valid |

---

### 6. `test_ai.py` — AI Engine

| Test | Description | Expected |
|---|---|---|
| `test_summarise_email` | Summarise a sample email body | Returns 2-3 sentence string |
| `test_summarise_empty_body` | Summarise empty string | Returns '' |
| `test_summarise_long_body` | Summarise 50,000 char body | Truncated and summarised |
| `test_classify_tags` | Classify a work email | Returns relevant tags (e.g., ['work', 'meeting']) |
| `test_classify_tags_personal` | Classify a personal email | Returns personal tags |
| `test_score_priority` | Score a high-priority email | Returns 4 or 5 |
| `test_score_priority_low` | Score a newsletter | Returns 0 or 1 |
| `test_score_spam` | Score an obvious spam email | Returns > 80 |
| `test_score_spam_legitimate` | Score a legitimate email | Returns < 20 |
| `test_draft_reply` | Draft a reply with intent | Returns coherent draft text |
| `test_draft_compose` | Draft a new email with intent | Returns coherent draft text |
| `test_ollama_unavailable_summarise` | Ollama is down | Returns '' (no exception) |
| `test_ollama_unavailable_classify` | Ollama is down | Returns [] (no exception) |
| `test_ollama_unavailable_priority` | Ollama is down | Returns 0 (no exception) |
| `test_ollama_unavailable_spam` | Ollama is down | Returns 0 (no exception) |
| `test_ollama_unavailable_draft` | Ollama is down | Returns '' (no exception) |
| `test_ollama_malformed_response` | Ollama returns garbage JSON | Returns default (no exception) |
| `test_ollama_timeout` | Ollama request times out (120s) | Returns default (no exception) |

---

### 7. `test_api.py` — Facade Integration

| Test | Description | Expected |
|---|---|---|
| `test_add_account_success` | Add account with valid credentials | Account saved, connection tested |
| `test_add_account_imap_fail` | Add account, IMAP test fails | Account NOT saved, error returned |
| `test_add_account_no_test` | Add account with --no-test | Account saved without testing |
| `test_sync_account_incremental` | Sync account twice | Second sync only fetches new emails |
| `test_sync_account_full` | Sync with --full flag | Re-fetches all emails |
| `test_sync_account_no_ai` | Sync with --no-ai | Emails stored but AI fields empty |
| `test_sync_account_not_found` | Sync non-existent account | Raises `EmailNotFoundError` |
| `test_list_emails_default` | List emails with defaults | Returns latest 20 emails |
| `test_list_emails_filtered` | List with account + folder filter | Only matching emails |
| `test_search_emails` | Search with keyword | BM25-ranked results |
| `test_compose_and_send` | Compose and send email | Message sent via SMTP, saved to DB |
| `test_reply_to_email` | Reply to existing email | Headers set correctly, sent and saved |
| `test_compose_dry_run` | Compose with --dry-run | No SMTP call, draft returned |

---

## Integration Test Plan

### End-to-End Sync Pipeline

```bash
# Test: Full sync pipeline with mock IMAP
python -m pytest core/email/tests/test_api.py::test_full_sync_pipeline -v
```

Scenario:
1. Add account (mock IMAP responds to login)
2. Sync account (mock IMAP returns 10 sample emails)
3. Verify 10 emails in DB with correct fields
4. Verify FTS index contains all 10 emails
5. Verify AI fields populated (mock Ollama responds)
6. Sync again (mock IMAP returns 3 new emails)
7. Verify 13 total emails (no duplicates)
8. Verify sync_state updated to latest UID

### End-to-End Compose Pipeline

Scenario:
1. Add account
2. Compose email with AI draft (mock Ollama)
3. Verify draft returned to caller
4. Confirm send (mock SMTP captures message)
5. Verify sent message has correct headers
6. Verify email saved to DB with `is_sent=1`

### End-to-End Search Pipeline

Scenario:
1. Populate DB with 50 sample emails
2. Search for specific keyword
3. Verify results are BM25-ranked
4. Verify snippet generation
5. Verify account/folder/date filters work

### CLI Integration

```bash
# Test: CLI commands produce correct output
python -m pytest core/email/tests/test_cli.py -v
```

Uses `typer.testing.CliRunner` to invoke commands and assert on stdout/stderr.

---

## Stress Testing

### Large Inbox Sync

| Test | Scenario | Target |
|---|---|---|
| `test_sync_1000_emails` | Sync 1000 emails in one batch | Completes in < 120 seconds (no AI) |
| `test_sync_1000_with_ai` | Sync 1000 emails with AI | Completes in < 30 minutes |
| `test_fts_search_10000` | FTS search over 10,000 emails | < 500ms per query |
| `test_list_50000` | List emails from 50,000 row table | < 200ms |
| `test_concurrent_reads` | 10 concurrent read queries | No locking errors (WAL mode) |

```bash
# Run stress tests
python -m pytest core/email/tests/test_stress.py -v --timeout=300
```

---

## Malformed Email Testing

| Test | Input | Expected |
|---|---|---|
| `test_missing_headers` | Email with no From, To, Subject, Date | Parser returns defaults, no crash |
| `test_invalid_date` | Date: "not-a-date" | Parser returns `None` date, logs warning |
| `test_broken_mime` | Truncated multipart boundary | Parser extracts whatever is available |
| `test_binary_body` | Body contains raw binary data | Parser returns empty body_text |
| `test_deeply_nested` | 10-level nested multipart | Parser handles without recursion overflow |
| `test_huge_attachment` | Email with 100MB attachment reference | Metadata extracted, no OOM |
| `test_null_bytes` | Body contains \x00 null bytes | Stripped before storage |
| `test_mixed_encodings` | Parts with different charsets | Each part decoded correctly |
| `test_rfc2047_subject` | Encoded subject: `=?UTF-8?B?...?=` | Correctly decoded to Unicode |

---

## Offline Testing

### Ollama Unavailable

| Test | Scenario | Expected |
|---|---|---|
| `test_sync_no_ollama` | Sync with Ollama stopped | Emails fetched and stored; AI fields empty; no crash |
| `test_compose_no_ollama` | Compose with `--ai-draft` but Ollama down | Warning printed; user prompted for manual body |
| `test_reply_no_ollama` | Reply with `--ai-draft` but Ollama down | Warning printed; user prompted for manual body |
| `test_search_no_ollama` | Search (FTS5) with Ollama down | Search works perfectly (no Ollama needed) |

```bash
# Manual test: stop Ollama and run sync
systemctl stop ollama  # or: pkill ollama
pm email sync -a "Test"
# Expected: "⚠ Ollama unavailable — AI features skipped" + emails still synced
```

---

## SMTP Failure Testing

| Test | Scenario | Expected |
|---|---|---|
| `test_smtp_connection_refused` | SMTP server unreachable | `EmailSendError` with clear message |
| `test_smtp_auth_failure` | Wrong SMTP password | `EmailSendError("Authentication failed")` |
| `test_smtp_timeout` | SMTP server hangs | `EmailSendError` after 30s timeout |
| `test_smtp_tls_failure` | TLS handshake fails | `EmailSendError` with TLS context |
| `test_smtp_recipient_rejected` | Server rejects recipient | `EmailSendError` listing rejected addresses |
| `test_smtp_data_failure` | Server rejects message body | `EmailSendError` with server response |

---

## IMAP Reconnection Testing

| Test | Scenario | Expected |
|---|---|---|
| `test_imap_connection_drop` | Connection drops mid-fetch | `EmailConnectionError`, partial results NOT saved (atomic) |
| `test_imap_idle_reconnect` | (Phase 2) IDLE connection drops | Watcher reconnects and resumes |
| `test_imap_server_restart` | Server restarts between syncs | Next sync reconnects successfully |
| `test_imap_ssl_cert_expired` | Invalid SSL certificate | `EmailConnectionError` with cert details |
| `test_imap_folder_not_found` | Sync non-existent folder | `EmailSyncError("Folder 'Drafts' not found")` |
| `test_imap_uid_validity_change` | Server UID validity counter changes | Full re-sync triggered (UIDs reset) |

---

## Manual Verification Checklist

### Phase 1 Smoke Test

```bash
# 1. Verify module imports
python -c "from core.email import api; print('email module OK')"

# 2. Verify DB init
python -c "from core.email.store import init_email_db; init_email_db(); print('DB OK')"

# 3. Add test account (use a real test account)
pm email add -l "Test" -e test@example.com \
  --imap-host imap.example.com --smtp-host smtp.example.com

# 4. Verify account persists
pm email accounts

# 5. Sync
pm email sync -a "Test"

# 6. List
pm email list

# 7. Read first email
pm email read 1

# 8. Search
pm email search "test"

# 9. Unread count
pm email unread -c

# 10. Compose dry run
pm email compose -a "Test" --to "friend@example.com" \
  -s "Test" --ai-draft "just testing" --dry-run

# 11. Reply dry run
pm email reply 1 --ai-draft "thanks for the email" --dry-run
```

### Phase 2 Smoke Test

```bash
# 1. Verify new imports
python -c "from core.email.semantic import embed_email; print('semantic OK')"
python -c "from core.email.analytics import get_contact_stats; print('analytics OK')"

# 2. Ask a question
pm email ask "What is the latest update from the team?"

# 3. Start watcher (briefly)
timeout 30 pm email watch --notify || true

# 4. Check contacts
pm email contacts --needs-reply

# 5. Set a reminder
pm email remind 1 --at "tomorrow 9am" -r "Follow up"

# 6. View digest
pm email digest -p day
```
