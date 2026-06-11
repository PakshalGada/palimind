# PaliMind

> **Local-first intelligence OS** — index documents, chat with a local LLM, and manage email entirely on your machine. No cloud. No subscriptions. No data leaving your device.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![Ollama](https://img.shields.io/badge/inference-Ollama-black.svg)](https://ollama.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## What is PaliMind?

PaliMind is a modular, privacy-first personal intelligence system. It turns your local machine into a powerful knowledge workspace:

- **RAG** — semantic search over your documents using local embeddings
- **Email** — full IMAP/SMTP email client with AI triage, spam detection, and smart drafting
- **Local-only** — all inference via [Ollama](https://ollama.com); nothing is sent to external APIs

---

## Features

| Module | Capabilities |
|--------|-------------|
| **RAG** | Vector search, intent routing, multimodal (PDF, PPTX, XLSX, images), streaming chat |
| **Email Phase 1** | IMAP sync, FTS search, AI summaries + tags + priority, SMTP compose/reply |
| **Email Phase 2** | Watch mode, NL Q&A, needs-reply detection, daily digest, contact analytics, newsletters, spam management, reminders, style-aware drafting |

---

## Install

```bash
# Core install
pip install -e .

# With OCR support (EasyOCR — large download ~2 GB)
pip install -e ".[ocr]"
```

## Ollama Models

Pull the models PaliMind uses:

```bash
ollama pull nomic-embed-text   # document embeddings
ollama pull gemma3:latest      # email AI (summaries, tagging, drafts)
ollama pull gemma4:e4b         # chat / RAG queries
ollama pull llava              # vision / image captioning (optional)
```

> **Note:** All AI features degrade gracefully — if Ollama is offline, sync, search, and storage still work normally.

---

## RAG — Document Q&A

```bash
cd /your/project

pm init .                                   # initialise the index
pm add .                                    # index all files recursively
pm ask "how does authentication work?"      # single question
pm chat                                     # interactive chat session
pm search "database schema"                 # keyword search
```

---

## Email Assistant

PaliMind includes a complete local-first email client under `pm email`.

- **Storage:** `~/.palimind/email.db` (SQLite, shared across workspaces)
- **Credentials:** encrypted at rest with Fernet (machine-bound key, never exposed to AI)
- **Privacy:** email bodies are summarised locally; no content leaves your machine

### Setup

#### Gmail

Gmail requires an **App Password** (not your regular password):

1. Enable 2-Step Verification → [myaccount.google.com/security](https://myaccount.google.com/security)
2. Create an App Password → [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Copy the 16-character password

```bash
pm email add \
  --label "Gmail" \
  --email you@gmail.com \
  --imap-host imap.gmail.com \
  --smtp-host smtp.gmail.com \
  --smtp-port 587
# Enter the App Password when prompted
```

#### Other Providers

```bash
# Outlook / Hotmail
pm email add --label "Work" --email you@outlook.com \
  --imap-host outlook.office365.com \
  --smtp-host smtp.office365.com --smtp-port 587

# Custom / self-hosted
pm email add --label "Personal" --email you@domain.com \
  --imap-host mail.domain.com --imap-port 993 \
  --smtp-host mail.domain.com --smtp-port 587
```

---

## Email — Phase 1: Core Commands

### Account Management

```bash
pm email accounts                          # list configured accounts
pm email add --label "Gmail" ...           # add an account (see setup above)
```

### Sync

```bash
pm email sync                              # sync all accounts (INBOX, last 50)
pm email sync -a "Gmail"                   # specific account
pm email sync -a "Gmail" -f "Sent"        # specific folder
pm email sync -a "Gmail" --full           # full re-sync (ignore checkpoint)
pm email sync -a "Gmail" --no-ai          # skip AI processing (faster)
pm email sync -a "Gmail" --limit 100      # fetch more emails
```

### Browse & Read

```bash
pm email list                              # latest 20 emails
pm email list -a "Gmail"                   # filter by account
pm email list --sort priority              # sort by AI priority score
pm email list --sort sender
pm email list --tag "work"                 # filter by AI-assigned tag
pm email list --after 2025-01-01
pm email list -n 50

pm email unread                            # show unread emails
pm email unread -c                         # count only (per account)

pm email read 42                           # read email #42 (marks as read)
pm email read 42 --headers                 # show full headers
pm email read 42 --html                    # show raw HTML body
```

### Search

Full-text search powered by SQLite FTS5 (BM25 ranked):

```bash
pm email search "invoice"
pm email search "meeting notes" -a "Gmail"
pm email search "deploy" --after 2025-06-01 -n 5
```

### Compose & Reply

```bash
# Manual compose
pm email compose -a "Gmail" \
  --to "friend@example.com" \
  --subject "Hello" \
  --body "Just saying hi!"

# AI-drafted compose (Ollama required)
pm email compose -a "Gmail" --to "client@work.com" -s "Project Update" \
  --ai-draft "brief update: milestone hit, next step is review"

# Skip confirmation prompt
pm email compose -a "Gmail" --to "boss@work.com" -s "Update" \
  --body "All done." --yes

# Dry run — preview without sending
pm email compose -a "Gmail" --to "test@example.com" -s "Test" \
  --body "Hello!" --dry-run

# Reply to email #7
pm email reply 7 --body "Thanks, I'll look into it."
pm email reply 7 --ai-draft "politely decline and suggest Friday instead"
pm email reply 7 --reply-all --body "Thanks everyone."
pm email reply 7 --ai-draft "confirm meeting" --dry-run
```

### AI Processing

When syncing with AI enabled (default), each new email is enriched locally:

| Field | What it does |
|-------|-------------|
| **Summary** | 2–3 sentence digest shown in `pm email read` |
| **Tags** | Auto-classification (e.g. `work`, `invoice`, `action-required`) |
| **Priority** | Score 0–5 (used for `--sort priority`) |
| **Spam Score** | 0–100 (shown as warning in `pm email read` if > 30) |

---

## Email — Phase 2: Intelligence & Automation

Phase 2 adds a layer of proactive intelligence on top of the Phase 1 core. All features degrade gracefully when Ollama is offline — heuristics continue to work.

### Watch Mode

Continuously polls all accounts in the background:

```bash
pm email watch                             # poll every 5 minutes
pm email watch --interval 60               # poll every 60 seconds
pm email watch --no-ai                     # heuristics only, no Ollama
pm email watch --no-notify                 # disable desktop notifications
pm email watch --folder "All Mail"         # watch a specific folder
```

Press `Ctrl+C` to stop. New emails are printed with timestamps as they arrive.

---

### Natural Language Q&A

Ask questions about your inbox in plain English:

```bash
pm email ask "Which recruiter emailed me last week?"
pm email ask "Do I have any pending invoices?"
pm email ask "Summarize unread emails from GitHub."
pm email ask "Which emails require my reply?"
pm email ask "Show anything about the AWS deployment."
pm email ask "Did anyone email me about the interview?" --no-refs
```

The command searches your local archive with FTS, passes relevant emails to the AI, and returns a cited answer. `--no-refs` hides the source email table.

---

### Needs-Reply Detection

Identifies emails that expect a response (questions, action requests, RSVPs, follow-ups):

```bash
pm email needs-reply                       # show previously flagged emails
pm email needs-reply --scan                # re-scan inbox first
pm email needs-reply --scan --no-ai        # heuristics only
pm email needs-reply --limit 20
```

Detection uses a combination of linguistic heuristics (question marks, "please reply", "RSVP", deadlines) and an optional AI classification pass.

---

### Daily Inbox Digest

```bash
pm email today                             # full digest with AI summary
pm email today --no-ai                     # skip AI, show categories only
pm email today --account "Gmail"           # filter to one account
```

Shows:
- **AI Summary** — one-paragraph executive briefing
- Unread count, high priority, needs reply, meetings, finance emails
- Due reminders for today
- Newsletter and spam counts

---

### Contact Analytics

```bash
pm email contacts                          # top 20 contacts by volume
pm email contacts --rebuild                # rebuild stats cache from scratch
pm email contacts --limit 30
```

Shows received/sent counts, reply rate, and last contact date per sender.

---

### Reminders

Set reminders on any email and get them surfaced in `pm email today`:

```bash
# Create a reminder (note auto-generated by AI if omitted)
pm email remind 42
pm email remind 42 --note "Reply by Friday with invoice"
pm email remind 42 --due 2026-06-15
pm email remind 42 --due tomorrow
pm email remind 42 --due "next week"

# List reminders
pm email reminders                         # active reminders only
pm email reminders --all                   # include completed

# Dismiss a reminder
pm email reminders --dismiss 3
```

---

### Newsletter Detection

```bash
pm email newsletters                       # show detected newsletters
pm email newsletters --scan                # scan inbox first, then show
pm email newsletters --limit 100
```

Detection combines MIME header signals (`List-Unsubscribe`, `List-ID`) with heuristics (bulk patterns, "unsubscribe" keywords) and optional AI classification.

---

### Spam Management

#### Dashboard
```bash
pm email spam                              # spam stats + top senders + recent detections
```

#### Listing
```bash
pm email spam-list                         # all spam + suspicious emails
pm email spam-list --status spam           # confirmed spam only
pm email spam-list --status suspicious     # borderline emails
```

#### Interactive Review
```bash
pm email spam-review                       # review borderline emails one by one
pm email spam-review --limit 20
```
For each email: press `s` = mark spam, `o` = mark safe, `Enter` = skip.

#### Sender Preferences
```bash
pm email spam-whitelist boss@company.com   # always treat as safe
pm email spam-blacklist spammer@evil.xyz   # always treat as spam
```

Whitelist/blacklist entries override AI and heuristic scores completely.

---

### Style-Aware Drafting

Phase 2 drafting commands (`pm email compose --ai-draft` and `pm email reply --ai-draft`) automatically use your past sent emails as style examples, matching your tone, vocabulary, and email length.

```bash
# Compose with style-matching (uses sent history automatically)
pm email compose -a "Gmail" --to "colleague@work.com" \
  -s "Meeting Request" \
  --ai-draft "schedule a 30-min sync this week to discuss the API design"

# Reply with style-matching
pm email reply 42 --ai-draft "accept the invitation and suggest Thursday 3pm"
```

---

### Enhanced Statistics

```bash
pm email stats
```

Shows all Phase 1 + Phase 2 metrics in one view:

| Metric | Description |
|--------|-------------|
| Total / Unread / Sent | Core counts |
| Needs Reply | Emails flagged as awaiting response |
| Active Reminders | Pending reminders |
| Newsletters | Detected bulk mail |
| Spam / Suspicious | Flagged emails |
| Storage Used | `email.db` file size |
| Last Sync | Timestamp of last successful sync |
| Top Contacts | Top 5 by email volume |

---

## Phase 2 Full Command Reference

```
pm email watch          Background polling (Ctrl+C to stop)
pm email ask "<q>"      Natural language inbox Q&A
pm email needs-reply    Emails awaiting your reply
pm email today          Daily inbox digest
pm email contacts       Contact analytics
pm email remind <ID>    Set a reminder on an email
pm email reminders      List / dismiss reminders
pm email newsletters    Newsletter detection view
pm email spam           Spam dashboard
pm email spam-list      List spam/suspicious emails
pm email spam-review    Interactive review of borderline emails
pm email spam-whitelist <addr>
pm email spam-blacklist <addr>
pm email stats          Enhanced statistics (Phase 1 + 2)
```

---

## Configuration

Settings live in `.palimind/config.json` inside each workspace:

| Setting | Default | Description |
|---------|---------|-------------|
| `embed_model` | `nomic-embed-text` | Ollama embedding model |
| `chat_model` | `gemma4:e4b` | Ollama chat / email AI model |
| `vision_model` | `llava` | Ollama vision model |
| `ollama_base_url` | `http://localhost:11434` | Ollama server URL |
| `chunk_size` | `1000` | Characters per RAG chunk |
| `chunk_overlap` | `200` | Overlap between chunks |
| `turbovec_bit_width` | `4` | Vector compression (2 or 4 bit) |
| `summarise` | `true` | Generate file summaries at index time |

Email data is stored in `~/.palimind/email.db` (shared across all workspaces). Credentials are stored encrypted in the same database — the encryption key is machine-bound and never stored in plaintext.

---

## Architecture

```
palimind/
├── core/
│   ├── email/               # Email module (isolated)
│   │   ├── crypto.py        # Fernet credential encryption
│   │   ├── store.py         # Phase 1 SQLite layer + FTS5
│   │   ├── store_p2.py      # Phase 2 DB tables (reminders, spam_prefs, etc.)
│   │   ├── ai.py            # Phase 1 Ollama integration
│   │   ├── ai_p2.py         # Phase 2 AI (Q&A, newsletter, spam, drafting)
│   │   ├── api.py           # Phase 1 facade
│   │   ├── api_p2.py        # Phase 2 facade
│   │   ├── cli.py           # Phase 1 CLI commands
│   │   ├── cli_p2.py        # Phase 2 CLI (watch, ask, today, reminders…)
│   │   ├── cli_p2b.py       # Phase 2 CLI (spam, newsletters, stats)
│   │   └── prompts/         # Ollama prompt templates
│   ├── ingestion/           # Document ingestion pipeline
│   ├── retrieval/           # RAG search + reranking
│   └── cli/                 # Top-level CLI (pm)
└── tests/
    ├── test_email_module.py      # Phase 1 tests
    └── test_email_phase2.py      # Phase 2 tests
```

---

## Privacy & Security

- **No external API calls** — all inference is local via Ollama
- **Credentials encrypted** — Fernet AES-128 with a machine-bound key; never written in plaintext
- **LLM never sees credentials** — only email content (subject, sender, body) is passed to Ollama
- **Local SQLite** — no cloud sync, no telemetry

---

## License

MIT © PakshalGada
