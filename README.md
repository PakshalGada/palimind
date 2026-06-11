# PaliMind

Local-first intelligence OS — index your documents, chat with a local LLM, and manage your email entirely on your machine.

## Features

- **Vector search** via [Turbovec](https://github.com/PakshalGada/turbovec) (4-bit compressed, O(1) deletion)
- **Intent routing** — file-targeted, corpus-wide, and semantic query strategies
- **Multimodal** — indexes text, PDF, PPTX, XLSX, and images (vision captioning + OCR)
- **Streaming responses** — token-by-token output via Ollama
- **Email assistant** — IMAP sync, full-text search, AI summaries, SMTP send — all local
- **Fully local** — all inference runs on your machine via Ollama

---

## Install

```bash
pip install -e .

# Optional: OCR support (EasyOCR, large download)
pip install -e ".[ocr]"
```

## Ollama Models

```bash
ollama pull nomic-embed-text   # embeddings
ollama pull gemma3:latest      # email AI (summaries, tagging, drafts)
ollama pull gemma4:e4b         # chat / RAG
ollama pull llava              # vision (image captioning)
```

---

## RAG Usage

```bash
cd /your/project

pm init .          # initialise the index
pm add .           # index all files
pm ask "how does authentication work?"
pm chat            # interactive session
```

---

## Email Assistant

PaliMind includes a local-first email assistant under `pm email`.  
Emails are stored in `~/.palimind/email.db` (SQLite). Credentials are encrypted at rest using Fernet (machine-bound key).

### Gmail Setup (required for Gmail)

Gmail blocks regular passwords for IMAP. You must use an **App Password**:

1. Enable **2-Step Verification** → [myaccount.google.com/security](https://myaccount.google.com/security)
2. Generate an App Password → [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Name it `PaliMind`, copy the 16-character password

### Add an Account

```bash
pm email add \
  --label "Gmail" \
  --email you@gmail.com \
  --imap-host imap.gmail.com \
  --smtp-host smtp.gmail.com \
  --smtp-port 587
# Enter the App Password when prompted
```

For other providers:

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

### All Email Commands

```bash
pm email --help          # list all sub-commands
pm email accounts        # list configured accounts
```

#### Sync
```bash
pm email sync                          # sync all accounts (INBOX, last 50)
pm email sync -a "Gmail"               # sync specific account
pm email sync -a "Gmail" -f "Sent"     # sync a specific folder
pm email sync -a "Gmail" --full        # full re-sync (ignore checkpoint)
pm email sync -a "Gmail" --no-ai       # skip AI processing (faster)
pm email sync -a "Gmail" --limit 100   # fetch more emails
```

#### List & Browse
```bash
pm email list                          # latest 20 emails (all accounts)
pm email list -a "Gmail"               # filter by account
pm email list --sort priority          # sort by AI priority score
pm email list --sort sender            # sort by sender
pm email list --tag "work"             # filter by AI-assigned tag
pm email list --after 2025-01-01       # filter by date (YYYY-MM-DD)
pm email list -n 50                    # show 50 emails
```

#### Unread
```bash
pm email unread                        # show unread emails
pm email unread -c                     # count only (per account)
pm email unread -a "Gmail"             # filter by account
```

#### Read
```bash
pm email read 42                       # read email ID 42 (marks as read)
pm email read 42 --headers             # show full headers + Message-ID
pm email read 42 --html                # show raw HTML body
```

#### Search (full-text, BM25 ranked)
```bash
pm email search "invoice"
pm email search "meeting notes" -a "Gmail"
pm email search "deploy" --after 2025-06-01 -n 5
```

#### Compose
```bash
# Interactive (shows draft, asks y/n/e before sending)
pm email compose -a "Gmail" \
  --to "friend@example.com" \
  --subject "Hello" \
  --body "Just saying hi!"

# Skip confirmation
pm email compose -a "Gmail" --to "boss@work.com" -s "Update" \
  --body "All done." --yes

# AI-assisted draft (Ollama required)
pm email compose -a "Gmail" --to "client@work.com" -s "Project Update" \
  --ai-draft "brief update: milestone hit, next step is review"

# Dry run — preview without sending
pm email compose -a "Gmail" --to "test@example.com" -s "Test" \
  --body "Hello!" --dry-run
```

#### Reply
```bash
# Manual reply to email ID 7
pm email reply 7 --body "Thanks, I'll look into it."

# AI-drafted reply (Ollama required)
pm email reply 7 --ai-draft "politely decline and suggest Friday instead"

# Reply all
pm email reply 7 --reply-all --body "Thanks everyone."

# Dry run preview
pm email reply 7 --ai-draft "confirm meeting" --dry-run
```

### How AI Processing Works

When you sync with AI enabled (default), each new email is processed by Ollama:

| Field | What it does |
|---|---|
| **Summary** | 2-3 sentence digest shown in `pm email read` |
| **Tags** | Auto-classification (e.g. `work`, `invoice`, `action-required`) |
| **Priority** | Score 0–5 (used for `--sort priority`) |
| **Spam Score** | 0–100 (shown as warning in `pm email read` if >30) |

AI runs locally and **degrades gracefully** — if Ollama is offline, sync still works; AI fields just stay empty.

---

## Configuration

Settings are stored in `.palimind/config.json` inside each workspace. Defaults:

| Setting | Default | Description |
|---|---|---|
| `embed_model` | `nomic-embed-text` | Ollama embedding model |
| `chat_model` | `gemma4:e4b` | Ollama chat / email AI model |
| `vision_model` | `llava` | Ollama vision model |
| `ollama_base_url` | `http://localhost:11434` | Ollama server URL |
| `chunk_size` | `1000` | Characters per RAG chunk |
| `chunk_overlap` | `200` | Overlap between chunks |
| `turbovec_bit_width` | `4` | Compression (2 or 4 bit) |
| `summarise` | `true` | Generate file summaries at index time |

Email data is stored in `~/.palimind/email.db` (shared across all workspaces).
