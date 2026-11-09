# PaliMind

**A local-first AI workspace for your documents, your agents, and your desktop.**

PaliMind is an open-source desktop app that combines chat, retrieval over your own files, autonomous agents, generated documents and slides, voice input, and desktop automation in one place. Models run locally through [Ollama](https://ollama.com) by default, so you can use it without an account, an API key, or a cloud subscription.

Add an OpenCode API key only if you want to route some work to hosted models; local models work without one.



## Contents

- [What PaliMind is](#what-palimind-is)
- [Quick start](#quick-start)
- [Using PaliMind](#using-palimind)
  - [Chat](#chat)
  - [Knowledge](#knowledge)
  - [Agents](#agents)
  - [Projects](#projects)
  - [Artifacts](#artifacts)
  - [Computer use](#computer-use)
  - [Voice, API, and mobile](#voice-api-and-mobile)
- [CLI](#cli)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Privacy and security](#privacy-and-security)
- [Development](#development)
- [Documentation](#documentation)

---

## What PaliMind is

PaliMind is a single desktop workspace built around three ideas:

1. **Your files are the context.** Point PaliMind at a folder and it indexes the documents, code, spreadsheets, slides, and video inside it into a local vector store. Answers cite the files they came from.
2. **Agents do the work.** Create specialised agents that can search, browse, run code, query databases, read and write Office files, and schedule themselves. You approve risky actions.
3. **The desktop is part of the workspace.** On Linux, agents can observe and operate ordinary apps through the accessibility tree with approvals and a global stop.

It is **local-first, not network-isolated**. Web search, URL fetching, optional MQTT/browser tools, and the optional OpenCode provider send data to third parties when you use them. PaliMind sends no telemetry, and nothing leaves the machine unless you invoke one of those features.

### The workspace at a glance

| Area | What it is for |
|---|---|
| **Home** | Recent chats, active agents, workspace status, and starting points |
| **Chat** | Direct model chat with web search, tools, files, and agent mentions |
| **Knowledge** | PaliSpace: index a folder and ask questions with citations |
| **Agents** | PalIAgents: create, chat with, schedule, and manage agents |
| **Projects** | Group sessions, knowledge, and artifacts into an isolated workspace |
| **Artifacts** | Saved documents, pages, decks, code, and other generated outputs |
| **Computer use** | Let an agent observe or operate Linux desktop apps |

---

## Quick start

### Prerequisites

| Requirement | Version | Why |
|---|---|---|
| Python | 3.12+ | Backend |
| Node.js | 20+ | Frontend and Tauri CLI |
| Rust | stable | Desktop shell (install via [rustup](https://rustup.rs)) |
| Ollama | latest | Local model inference |
| Linux system libraries | — | `libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev patchelf` |

### 1. Install Ollama

```bash
# Linux / macOS
curl -fsSL https://ollama.com/install.sh | sh
```

On Windows, download it from [ollama.com/download](https://ollama.com/download).

### 2. Clone and bootstrap

```bash
git clone https://github.com/PakshalGada/palimind.git
cd palimind
./scripts/bootstrap.sh
```

`bootstrap.sh` (Linux/macOS) checks the toolchain, installs the backend in editable mode plus the frontend and root dependencies, installs the Tauri system libraries where possible, sets up pre-commit hooks, and pulls the default models. Run it from an activated virtual environment if you want an isolated Python install.

### 3. Launch

```bash
make dev
```

This builds the frontend, starts Ollama if needed, starts the local API server, and opens the desktop app. The `pm` command provides the same launcher directly:

```bash
pm ui
pm ui --skip-install      # skip dependency installation
pm ui --keep-backend      # keep Ollama/API running after the app closes
pm ui --port 8001         # use a different backend port
```

### 4. First run

1. Open **Settings** and choose your default chat and embedding models. Local Ollama models are listed automatically.
2. Optional: add an OpenCode API key under **Settings → OpenCode** to use hosted models. Local models continue to work without one.
3. In **Knowledge**, choose **Add folder** and pick a directory to index.
4. Ask a question. The first sync indexes files locally; later syncs only process what changed.

### Manual setup

If you prefer not to use the bootstrap script:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e "packages/backend[dev]"
npm install
npm install --prefix packages/frontend
npm run build --prefix packages/frontend

ollama pull nomic-embed-text
ollama pull gemma4:e2b

pm ui
```

On Windows, run `.\dev.ps1` after installing dependencies; it starts the backend and Tauri together. On Linux, the Tauri system libraries listed above are required.

You can also run the backend without the desktop shell:

```bash
python -m palimind.api_server --host 127.0.0.1 --port 8000
# or
make backend
```

Then open `http://127.0.0.1:8000/ui`.

---

## Using PaliMind

### Chat

Chat is a conversation with a model. Unlike a plain chat app, the composer can pull in knowledge, search the web, call agents, attach files, and produce real documents.



#### Chat modes

Pick a mode from the composer before sending a message:

| Mode | What happens |
|---|---|
| **Default** | One model answers. Live web search is available, and citations are included when pages are read. |
| **Mixture of Experts** | An orchestrator plans the work, dispatches parallel expert agents with tools, then synthesises and verifies the answer. You can watch the plan and expert lanes as they run. |
| **Deep Research** | PaliMind proposes research sub-topics, lets you edit and approve the plan, runs research agents in parallel, and writes a long cited report. |

#### Composer tips

- Type `@` to mention an enabled agent, for example `@researcher find the latest papers`.
- Type `/` to run a skill or switch mode: `/doc`, `/docx`, `/pptx`, `/page`, `/code`, `/default`, `/moe`, `/research`.
- Attach local files with the attachment button. Images go to a vision-capable model; PDFs and text files are extracted as context.
- Use the microphone button for local speech-to-text.
- Use the model switcher to change the model for the current conversation.
- Press `Ctrl/⌘+K` (or `Mod+K`) to search every action, session, agent, and file from the command palette. `Mod+/` shows all keyboard shortcuts.

#### Web search

Search is built into the chat flow rather than being a separate switch. When a question needs current information, PaliMind searches, reads the top results, and cites them. For fully offline work, avoid search-dependent questions or use a local-only agent.

### Knowledge

**Knowledge** is the PaliSpace RAG workspace. It turns a folder into a private, searchable knowledge base.



1. Open **Knowledge** and choose **Add folder**.
2. PaliMind parses and embeds supported files, then reports progress in the sidebar and header.
3. Ask questions in natural language. Answers cite the source files and show the passages used.
4. Choose **Sync** after files change. Only new, modified, and deleted files are processed.
5. Choose **Graph** to explore entities and relationships extracted from the documents.

**Supported content:** PDF, DOCX, PPTX, XLSX, Markdown, plain text, source code, CSV, images with optional OCR, and video with local Whisper transcription.

**What you get:**

- Local vector search with SQLite/FTS5 metadata and FAISS HNSW vectors. No external database.
- Child chunks with context headers and page/slide numbers, reassembled into parent sections for the answer.
- Document-summary index, metadata filters (year, type, entity, section) and embedding-MMR diversity.
- Agentic RAG for complex, multi-hop questions: plan sub-queries, search in parallel, look up exact figures, verify sufficiency, then answer with citations.
- Per-file summaries and optional knowledge-graph extraction.
- Persistent sessions and hierarchical chat memory, so follow-up questions keep context.
- Source citations and a source ledger for agent answers.
- Optional cross-encoder reranking for higher-precision retrieval.

The index and workspace config live in a `.palimind` folder inside the indexed workspace. Shared app state — agent definitions, uploads, tokens, and global sessions — lives under `~/.palimind`.

### Agents

**Agents** is the PalIAgents runtime. An agent is a model with instructions, tools, knowledge access, memory, and a schedule.

#### Create an agent

Choose **New agent** and complete the six-step wizard:

1. **Identity** — display name, handle, avatar, and an optional template.
2. **Instructions** — what the agent is for and how it should behave.
3. **Capabilities** — which tools and skills it may use.
4. **Behavior** — autonomy level, approval requirements, memory mode, and run mode.
5. **Knowledge** — which indexed folders the agent can read.
6. **Review** — confirm and create.

Templates are a fast way to start; a blank agent gives you full control.

#### Built-in tools

Agents can use tools such as:

- Shell and Python execution (sandboxed, with timeouts and memory limits)
- Web search and URL browsing
- Shared Playwright browser with user takeover (requires the optional `browser` extra)
- arxiv search, RSS feeds, CSV/SQLite/DuckDB queries
- Knowledge-graph queries
- Office documents: DOCX, PPTX, XLSX, and PDF operations
- Chart generation and optional local image generation (ComfyUI or stable-diffusion.cpp)
- Git operations and atomic patching
- MQTT publish/subscribe
- Memory: `remember` and `forget`
- Local MCP servers declared in `~/.palimind/mcp.json`

Tool calls are typed, audited, and routed so the model sees the most relevant tools instead of the entire catalogue. Independent read-only calls run in parallel; writes, shell commands, and approval-gated actions run one at a time.

#### Run an agent

There are four ways to put an agent to work:

- **Agents → Chat** — talk to it directly. Each agent has its own sessions and memory.
- **From normal chat** — mention it with `@handle`.
- **Agents → Work** — run tasks and monitor progress from the dashboard.
- **Automations** — create a routine that runs on demand, on an interval, or on a cron schedule.

**Work** contains five views:

| Tab | Purpose |
|---|---|
| **Overview** | Agent and team status, recent runs, and what needs attention |
| **Activity** | A live, replayable timeline of runs, tools, and checkpoints |
| **Tasks** | Queued and running work, including goals and background tasks |
| **Board** | A kanban view of all agent tasks |
| **Automations** | Recurring routines and their schedules |

#### Teams and channels

- A **team** is a group of agents with a manager and a shared charter. Use one for work that benefits from multiple roles.
- A **channel** is a shared room where a few agents work in one thread. Use one for ongoing coordination.

Both appear in the conversation rail alongside individual agents.

#### Safety

Risky tools are approval-gated by default: file writes, shell and Python execution, browser mutations, and similar actions. Agents run under the strongest OS sandbox available:

- **Linux:** bubblewrap
- **macOS:** deny-by-default `sandbox-exec` profile
- **Windows:** Job Object with memory and process limits

Network access is denied and the workspace is read-only unless the agent has been granted the relevant access. If no sandbox can be built, the tools fail closed. `PALIMIND_ALLOW_UNSANDBOXED_EXEC=1` is an explicit, unsafe opt-out.

### Projects

A **Project** groups a set of sessions, knowledge, and artifacts so work does not leak between contexts. Create one from **Projects**, optionally pointing it at a workspace folder.

Use projects when you want:

- A separate chat history and model configuration for a client or codebase.
- Knowledge and artifacts scoped to one initiative.
- A clean context switch without deleting anything.

Selecting a project makes it the active scope for Chat and Knowledge until you leave it.

### Artifacts

Answers that produce a slide deck, Word document, web page, diagram, or code file stay compact in the transcript. Open the artifact panel to preview, edit, save, and export the result. Markdown answers and tables stay inline in the conversation and never open the artifact panel.

- Browse everything you have saved in **Artifacts**.
- Export to Markdown, HTML, PDF, DOCX, or PPTX.
- Use the composer commands for a guided pipeline:
  - `/doc` — structured Markdown document
  - `/docx` — real Word document download
  - `/pptx` — designed slide deck download
  - `/page` — self-contained HTML page
  - `/code` — complete source file

Office exports are built as real OOXML files, not renamed text. PPTX output includes cover, section, KPI, and bullet layouts.

### Computer use

On Linux, agents can observe and operate ordinary desktop apps through the AT-SPI2 accessibility tree. They act on stable element references rather than pixel coordinates, capture screenshots only on demand, and fall back to physical input only when no semantic action exists.

On Wayland, physical clicks use the compositor's RemoteDesktop session, Unicode typing uses clipboard paste with restore, and a one-time xdg-desktop-portal ScreenCast approval enables persistent full-screen capture without prompting again. None of these paths requires `/dev/uinput`; the kernel backend remains an opt-in alternative.

It is **on by default** and works with any app, with several layers of control:

- Global enable switch, plus per-agent `desktop_access` and `desktop_control` flags
- Optional app allowlist
- Approval for every mutating action
- Protected-process refusal list and a rate limit
- Append-only audit log that never stores typed text
- A Stop that immediately releases held input

**How to use it:**

1. Click **Computer Use** in the sidebar, use the tray menu, or press `Super+Shift+C`.
2. Pick any open window, or drag a screen area.
3. Choose **Ask** for read-only questions, or **Act** to perform a task. Each mutating step shows an **Approve / Deny** card.
4. Press `Ctrl+Shift+Escape`, use the popup's Stop button, or choose the tray's **Stop desktop control** to release input immediately.

Settings → Computer use shows live status, a walkthrough, recent audit entries, and the ghost-cursor toggle.

To restrict the agent to specific apps, set an allowlist and restart the backend:

```bash
export PALIMIND_DESKTOP_ALLOWED_APPS=gnome-calculator,gnome-text-editor
```

Kernel-level input is opt-in and requires a udev rule plus membership in the `input` group:

```bash
sudo scripts/install-uinput-udev.sh
# sign out and back in afterwards
```

See [docs/computer-use.md](docs/computer-use.md) for the threat model and platform details. Computer use is Linux-only.

### Voice, API, and mobile

- **Voice input** — the composer microphone records audio, transcribes it locally with Faster-Whisper, and inserts the text. Speech output is available through the local voice API.
- **OpenAI-compatible API** — use PaliMind from editors, scripts, or other tools:

  ```bash
  curl -H "Authorization: Bearer $(cat ~/.palimind/api_token)" \
    http://127.0.0.1:8000/v1/models
  ```

  Supported endpoints: `GET /v1/models`, `POST /v1/chat/completions`, and `POST /v1/embeddings`. Tool calling and streaming are supported.

- **Mobile / thin client** — open `http://127.0.0.1:8000/client` on a phone or tablet on the same LAN, paste the token from `~/.palimind/api_token`, and chat through the local API. The token is stored only in that browser.

- **Local MCP tools** — declare trusted stdio servers in `~/.palimind/mcp.json`:

  ```json
  {
    "servers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/me/docs"],
        "trusted": true
      }
    }
  }
  ```

  Reload them with `POST /api/mcp/reload`. Read-only MCP tools are tier 1; destructive tools stay behind approval.

---

### Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/your-feature`.
3. Commit with a clear message. Pre-commit hooks run Ruff, whitespace checks, and gitleaks.
4. Push and open a pull request. CI re-runs the same gates on a clean runner.

Core backend changes should degrade gracefully when Ollama is not running.

---
