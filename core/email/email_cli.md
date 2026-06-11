# PaliMind Email Module — CLI Command Reference

## Overview

All email commands live under the `pm email` subcommand group. They are registered as a Typer sub-app in `core/email/cli.py` and mounted onto the main `app` in `core/cli/main.py`.

**Conventions (matching existing PaliMind CLI):**

- Rich-formatted output via `core/cli/ui.py` helpers
- Domain exceptions caught at CLI layer → `print_error()` + `typer.Exit(1)`
- `--help` on every command via Typer auto-generation
- Path options use `typer.Option()` with short flags where appropriate

---

## Command Index

| Command | Purpose | Phase |
|---|---|---|
| `pm email add` | Add an email account | 1 |
| `pm email accounts` | List configured accounts | 1 |
| `pm email sync` | Fetch new emails from server | 1 |
| `pm email list` | List emails in a folder | 1 |
| `pm email unread` | Show unread email count/list | 1 |
| `pm email read` | Read a specific email | 1 |
| `pm email search` | Full-text search emails | 1 |
| `pm email compose` | Compose and send a new email | 1 |
| `pm email reply` | Reply to an email | 1 |
| `pm email watch` | Background polling for new mail | 2 |
| `pm email ask` | Semantic Q&A over email history | 2 |

---

## Phase 1 Commands

### `pm email add`

Add a new email account with IMAP/SMTP credentials.

**Syntax:**
```
pm email add [OPTIONS]
```

**Options:**

| Option | Short | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `--label` | `-l` | TEXT | Yes | — | Friendly name for the account |
| `--email` | `-e` | TEXT | Yes | — | Email address |
| `--imap-host` | | TEXT | Yes | — | IMAP server hostname |
| `--imap-port` | | INT | No | 993 | IMAP port |
| `--smtp-host` | | TEXT | Yes | — | SMTP server hostname |
| `--smtp-port` | | INT | No | 587 | SMTP port |
| `--username` | `-u` | TEXT | No | (same as email) | Login username |
| `--password` | `-p` | TEXT | No | (prompted) | Password (prompted securely if omitted) |
| `--no-ssl` | | FLAG | No | False | Use STARTTLS instead of SSL |
| `--no-test` | | FLAG | No | False | Skip connection test |

**Examples:**
```bash
# Interactive password prompt (recommended)
pm email add -l "Work" -e user@company.com --imap-host imap.company.com --smtp-host smtp.company.com

# Gmail with app password
pm email add -l "Personal Gmail" -e me@gmail.com \
  --imap-host imap.gmail.com --smtp-host smtp.gmail.com \
  -p "xxxx-xxxx-xxxx-xxxx"

# Non-SSL server
pm email add -l "Local" -e test@local.dev \
  --imap-host mail.local.dev --imap-port 143 \
  --smtp-host mail.local.dev --smtp-port 25 --no-ssl
```

**Expected Output:**
```
╭─ Adding Email Account ─╮
│ Testing IMAP connection to imap.gmail.com:993...
✓ IMAP connection successful
│ Testing SMTP connection to smtp.gmail.com:587...
✓ SMTP connection successful
✓ Account "Personal Gmail" saved (credentials encrypted)
```

**Error Cases:**

| Error | Message |
|---|---|
| Label already exists | `✗ Account "Work" already exists. Use a different label.` |
| IMAP connection fails | `✗ Cannot connect to imap.company.com:993 — Connection refused` |
| SMTP connection fails | `✗ Cannot connect to smtp.company.com:587 — Authentication failed` |
| Invalid email format | `✗ Invalid email address: not-an-email` |

---

### `pm email accounts`

List all configured email accounts.

**Syntax:**
```
pm email accounts
```

**Options:** None.

**Example:**
```bash
pm email accounts
```

**Expected Output:**
```
╭─ Email Accounts ─╮
┌────┬──────────────────┬──────────────────────┬──────────────────┬──────────────┐
│ #  │ Label            │ Email                │ IMAP Host        │ Last Synced  │
├────┼──────────────────┼──────────────────────┼──────────────────┼──────────────┤
│ 1  │ Personal Gmail   │ me@gmail.com         │ imap.gmail.com   │ 2 hours ago  │
│ 2  │ Work             │ user@company.com     │ imap.company.com │ Never        │
└────┴──────────────────┴──────────────────────┴──────────────────┴──────────────┘
```

**Error Cases:**

| Error | Message |
|---|---|
| No accounts configured | `ℹ No email accounts configured. Run 'pm email add' to add one.` |

---

### `pm email sync`

Fetch new emails from the server. Runs incrementally using stored IMAP UIDs.

**Syntax:**
```
pm email sync [OPTIONS]
```

**Options:**

| Option | Short | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `--account` | `-a` | TEXT | No | (all accounts) | Account label to sync |
| `--folder` | `-f` | TEXT | No | INBOX | IMAP folder to sync |
| `--limit` | `-n` | INT | No | 50 | Max emails to fetch per sync |
| `--full` | | FLAG | No | False | Full re-sync (ignore last UID) |
| `--no-ai` | | FLAG | No | False | Skip AI processing (summary, tags, priority, spam) |

**Examples:**
```bash
# Sync all accounts (INBOX only)
pm email sync

# Sync specific account
pm email sync -a "Work"

# Sync a specific folder
pm email sync -a "Work" -f "Sent"

# Full re-sync with AI disabled
pm email sync -a "Personal Gmail" --full --no-ai

# Fetch last 100 emails
pm email sync -n 100
```

**Expected Output:**
```
╭─ Syncing Email ─╮
ℹ Syncing "Personal Gmail" — INBOX
⠋ Fetching new emails...         ━━━━━━━━━━━━ 23/23
⠋ Processing AI features...      ━━━━━━━━━━━━ 23/23
✓ Synced 23 new emails (5 with attachments)
  Summaries: 23 | Tags: 23 | Priority scored: 23 | Spam scored: 23
```

**Error Cases:**

| Error | Message |
|---|---|
| Account not found | `✗ Account "Unknown" not found. Run 'pm email accounts' to see available accounts.` |
| IMAP connection fails | `✗ Cannot connect to imap.gmail.com:993 — Connection timed out` |
| IMAP auth fails | `✗ Authentication failed for me@gmail.com — check password` |
| Partial sync failure | `✓ Synced 20/23 emails (3 failed to parse)` |

---

### `pm email list`

List emails in a folder with summary info.

**Syntax:**
```
pm email list [OPTIONS]
```

**Options:**

| Option | Short | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `--account` | `-a` | TEXT | No | (all accounts) | Filter by account label |
| `--folder` | `-f` | TEXT | No | INBOX | IMAP folder |
| `--limit` | `-n` | INT | No | 20 | Number of emails to show |
| `--offset` | | INT | No | 0 | Pagination offset |
| `--sort` | `-s` | TEXT | No | date | Sort by: date, priority, sender |
| `--tag` | `-t` | TEXT | No | — | Filter by tag |
| `--before` | | TEXT | No | — | Show emails before date (YYYY-MM-DD) |
| `--after` | | TEXT | No | — | Show emails after date (YYYY-MM-DD) |

**Examples:**
```bash
# Default: latest 20 emails from INBOX
pm email list

# List with priority sort
pm email list -s priority

# Filter by tag
pm email list -t "work"

# Paginate
pm email list -n 10 --offset 10

# Date range
pm email list --after 2025-01-01 --before 2025-02-01
```

**Expected Output:**
```
╭─ INBOX — Personal Gmail (47 emails) ─╮
┌────┬────┬──────────┬────────────────────┬──────────────────────────────┬───────┐
│ #  │ ★  │ From     │ Subject            │ Summary                      │ Date  │
├────┼────┼──────────┼────────────────────┼──────────────────────────────┼───────┤
│ 1  │ ●  │ boss@... │ Q4 Planning        │ Discussion about Q4 goals... │ 2h    │
│ 2  │    │ hr@...   │ Benefits Update    │ Open enrollment reminder...  │ 5h    │
│ 3  │ ●  │ dev@...  │ Deploy Failed      │ CI pipeline failure on...    │ 1d    │
└────┴────┴──────────┴────────────────────┴──────────────────────────────┴───────┘
● = unread  ★ = priority ≥ 4
```

---

### `pm email unread`

Show unread emails or just the count.

**Syntax:**
```
pm email unread [OPTIONS]
```

**Options:**

| Option | Short | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `--account` | `-a` | TEXT | No | (all) | Filter by account |
| `--count` | `-c` | FLAG | No | False | Show count only |
| `--folder` | `-f` | TEXT | No | INBOX | IMAP folder |

**Examples:**
```bash
# List unread emails
pm email unread

# Count only
pm email unread -c

# Specific account
pm email unread -a "Work"
```

**Expected Output (list):**
```
╭─ Unread Emails (12) ─╮
┌────┬──────────┬─────────────────────┬──────────────────────────────┬───────┐
│ #  │ From     │ Subject             │ Summary                      │ Date  │
├────┼──────────┼─────────────────────┼──────────────────────────────┼───────┤
│ 1  │ boss@... │ Q4 Planning         │ Discussion about Q4 goals... │ 2h    │
│ 2  │ dev@...  │ Deploy Failed       │ CI pipeline failure on...    │ 1d    │
└────┴──────────┴─────────────────────┴──────────────────────────────┴───────┘
```

**Expected Output (count only):**
```
ℹ 12 unread emails across 2 accounts
  Personal Gmail: 8 unread
  Work: 4 unread
```

---

### `pm email read`

Display the full content of a specific email.

**Syntax:**
```
pm email read <EMAIL_ID> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|---|---|---|---|
| `EMAIL_ID` | INT | Yes | Email ID from `pm email list` output |

**Options:**

| Option | Short | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `--html` | | FLAG | No | False | Show raw HTML instead of plaintext |
| `--headers` | | FLAG | No | False | Show full email headers |
| `--thread` | | FLAG | No | False | Show entire thread |

**Examples:**
```bash
# Read email #1
pm email read 1

# Show full thread
pm email read 1 --thread

# Show full headers
pm email read 1 --headers
```

**Expected Output:**
```
╭─ Email #1 ─────────────────────────────────────────────╮
│ From:    John Boss <boss@company.com>                  │
│ To:      me@gmail.com                                  │
│ Date:    2025-06-10 14:30 UTC                          │
│ Subject: Q4 Planning                                   │
│ Tags:    work, planning, action-required                │
│ Priority: ★★★★☆ (4/5)                                  │
│ Attachments: Q4-goals.pdf (245 KB)                     │
╰────────────────────────────────────────────────────────╯

Summary: John outlines Q4 objectives and requests input on
resource allocation by Friday. Mentions potential new hires.

────────────────────────────────────────────────────────────
Hi team,

I wanted to share our Q4 planning document...
[full plaintext body]
────────────────────────────────────────────────────────────
```

**Error Cases:**

| Error | Message |
|---|---|
| Email not found | `✗ Email #999 not found` |

---

### `pm email search`

Full-text search across email subject, body, and sender.

**Syntax:**
```
pm email search <QUERY> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|---|---|---|---|
| `QUERY` | TEXT | Yes | Search query (BM25 ranked) |

**Options:**

| Option | Short | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `--account` | `-a` | TEXT | No | (all) | Filter by account |
| `--folder` | `-f` | TEXT | No | (all) | Filter by folder |
| `--limit` | `-n` | INT | No | 10 | Max results |
| `--after` | | TEXT | No | — | Only emails after date |
| `--before` | | TEXT | No | — | Only emails before date |

**Examples:**
```bash
# Basic search
pm email search "quarterly report"

# Scoped search
pm email search "deploy" -a "Work" -n 5

# Date-bounded search
pm email search "invoice" --after 2025-01-01
```

**Expected Output:**
```
╭─ Search Results: "quarterly report" (3 matches) ─╮
┌────┬───────┬──────────┬──────────────────────┬───────────────────────────┬───────┐
│ #  │ Score │ From     │ Subject              │ Snippet                   │ Date  │
├────┼───────┼──────────┼──────────────────────┼───────────────────────────┼───────┤
│ 1  │ 8.2   │ boss@... │ Q4 Report Ready      │ ...quarterly report is... │ 1d    │
│ 2  │ 5.1   │ hr@...   │ Annual Review         │ ...quarterly reviews...   │ 3d    │
│ 3  │ 3.4   │ cfo@...  │ Budget Q3             │ ...quarterly spending...  │ 2w    │
└────┴───────┴──────────┴──────────────────────┴───────────────────────────┴───────┘
```

---

### `pm email compose`

Compose a new email, optionally with AI-assisted drafting.

**Syntax:**
```
pm email compose [OPTIONS]
```

**Options:**

| Option | Short | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `--account` | `-a` | TEXT | Yes | — | Account to send from |
| `--to` | | TEXT | Yes | — | Recipient email address(es), comma-separated |
| `--subject` | `-s` | TEXT | Yes | — | Email subject |
| `--body` | `-b` | TEXT | No | — | Email body (opens $EDITOR if omitted) |
| `--cc` | | TEXT | No | — | CC recipients |
| `--bcc` | | TEXT | No | — | BCC recipients |
| `--ai-draft` | | TEXT | No | — | AI drafting intent (e.g., "request meeting about Q4") |
| `--dry-run` | | FLAG | No | False | Show what would be sent without sending |
| `--yes` | `-y` | FLAG | No | False | Skip confirmation prompt |

**Examples:**
```bash
# Simple send
pm email compose -a "Work" --to "boss@company.com" -s "Update" -b "Here's my update..." -y

# AI-assisted draft
pm email compose -a "Work" --to "team@company.com" -s "Meeting" \
  --ai-draft "Schedule a team sync for Friday afternoon, friendly tone"

# Open editor for body
pm email compose -a "Work" --to "client@external.com" -s "Proposal"

# Dry run
pm email compose -a "Work" --to "all@company.com" -s "Announcement" -b "..." --dry-run
```

**Expected Output (with AI draft):**
```
╭─ Composing Email ─╮
ℹ Generating AI draft...

To:      team@company.com
Subject: Meeting
──────────────────────────
Hi team,

I'd like to propose a team sync this Friday afternoon.
Would 3 PM work for everyone? We can use the usual conf room.

Looking forward to catching up!

Best,
[Your Name]
──────────────────────────

Send this email? [y/N/e(dit)]:
✓ Email sent via smtp.company.com
```

---

### `pm email reply`

Reply to an existing email, optionally with AI-assisted drafting.

**Syntax:**
```
pm email reply <EMAIL_ID> [OPTIONS]
```

**Arguments:**

| Argument | Type | Required | Description |
|---|---|---|---|
| `EMAIL_ID` | INT | Yes | Email ID to reply to |

**Options:**

| Option | Short | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `--body` | `-b` | TEXT | No | — | Reply body (opens $EDITOR if omitted) |
| `--ai-draft` | | TEXT | No | — | AI drafting intent |
| `--reply-all` | | FLAG | No | False | Reply to all recipients |
| `--dry-run` | | FLAG | No | False | Preview without sending |
| `--yes` | `-y` | FLAG | No | False | Skip confirmation |

**Examples:**
```bash
# Manual reply
pm email reply 1 -b "Sounds good, I'll have it ready by Friday."

# AI-drafted reply
pm email reply 1 --ai-draft "agree and confirm Friday deadline"

# Reply-all
pm email reply 1 --reply-all -b "Thanks everyone, noted."
```

**Expected Output:**
```
╭─ Replying to Email #1 ─╮
│ Original: "Q4 Planning" from boss@company.com
ℹ Generating AI draft...

Re: Q4 Planning
──────────────────────────
Hi John,

Thanks for sharing the Q4 plan. I agree with the proposed
objectives and can confirm I'll have the resource allocation
breakdown ready by Friday.

Best regards
──────────────────────────

Send this reply? [y/N/e(dit)]:
✓ Reply sent via smtp.company.com
```

**Error Cases:**

| Error | Message |
|---|---|
| Email not found | `✗ Email #999 not found` |
| No account for email | `✗ Cannot determine sending account for this email` |
| SMTP failure | `✗ Failed to send: Connection refused` |

---

## User Workflow Examples

### First-Time Setup

```bash
# 1. Add your email account
pm email add -l "Gmail" -e me@gmail.com \
  --imap-host imap.gmail.com --smtp-host smtp.gmail.com

# 2. Sync your inbox
pm email sync

# 3. Check what came in
pm email list

# 4. Read an important email
pm email read 1
```

### Daily Usage

```bash
# Morning: check unread
pm email unread

# Read and reply to urgent items
pm email read 3
pm email reply 3 --ai-draft "acknowledge and ask for more details"

# Search for something specific
pm email search "invoice december"

# Compose a new email
pm email compose -a "Gmail" --to "team@work.com" -s "Status Update" \
  --ai-draft "brief weekly status update, completed API refactor, starting testing phase"
```

### Multi-Account Workflow

```bash
# Sync everything
pm email sync

# Check work inbox specifically
pm email list -a "Work" -n 30

# Check personal unread
pm email unread -a "Gmail"
```
