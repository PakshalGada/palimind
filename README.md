# PaliMind

PaliMind is an open-source, **local-first AI intelligence platform** that brings a full suite of AI productivity tools to your desktop. Local models run on your own machine via **Ollama**; no cloud subscription or external API key is required for local-only use.

PaliMind is local-first, not network-isolated: web search, URL fetching, optional MQTT/browser tools, and the optional OpenCode cloud provider send data to third parties when you use them. No telemetry is sent, and nothing leaves the machine unless you explicitly invoke one of those features.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Pulling Models](#pulling-models)
- [CLI Usage](#cli-usage)
- [Configuration](#configuration)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

---

## Features

### PaliSpace - RAG Workspace

The core retrieval-augmented generation (RAG) engine. Point it at any folder and index every document into a local vector store you can query in natural language.

- **Multimodal indexing** - parses PDF, DOCX, PPTX, XLSX, Markdown, code, CSV, and video (with Whisper transcription). Image OCR requires the optional `easyocr` dependency; without it images are skipped with an error rather than silently indexed.
- **Local vector store** - FAISS HNSW vectors with SQLite/FTS5 metadata for document chunks; a separate TurboVec index stores episodic chat memory. No external database server.
- **Hierarchical memory** - episodic conversation turns are embedded and retrieved for long-term context.
- **Session management** - multiple persistent chat sessions per workspace with summaries.
- **Web search** - integrated DuckDuckGo search and Scrapling for real-time context augmentation.
- **Knowledge graph** - entities and relationships extracted from documents, queryable and visualized.
- **Summarisation** - per-file summaries, financial fact extraction, and timeline extraction at index time.

![PaliSpace - Chat](assets/chat.png)
![PaliSpace - Knowledge Base](assets/knowledge_base.png)
![PaliSpace - Knowledge Graph](assets/knowledge_graph.png)

### Chat modes

The chat composer has three LLM modes, all of which can use live web search:

| Mode | What it does |
|---|---|
| **Default** | One model answers directly. With **Web** on, it searches first, reads the top pages, and cites its sources. |
| **Mixture of Experts** | An orchestrator plans the work and dispatches parallel expert agents with tools, then synthesizes and verifies the result. Expert lanes and the plan are visible while they run. |
| **Deep Research** | Plans research sub-topics, lets you edit and approve the plan, runs research agents in parallel, and writes a long, cited report. |

Live web search is on by default for every LLM mode and has no separate
composer toggle; Deep Research is always web-backed. Agent mentions are
available in every mode: type `@` anywhere in the composer to pick an enabled
agent (for example `@researcher find the latest papers`).

### Artifacts

Answers that produce a web page, Markdown/Word document, slide deck or
previewable code file stay compact in the transcript: one block shows the
artifact's title and an **Open in artifact** button, and the full preview opens
in the artifact panel on demand. Ordinary tables and short snippets stay in the
chat. From the panel you can edit, save, and export to Markdown, HTML, PDF, DOCX
or PPTX. Type `/` in the composer to run an artifact skill: `/doc`, `/docx`,
`/slides`, `/pptx`, `/page` and `/code`. The skill's detailed instructions are
sent to the model but only your own request appears in the conversation. The
Word document and PowerPoint choices run the full office pipeline: the model
writes one fenced artifact, the backend builds a real OOXML file, and the
browser downloads it when the turn settles. Slide decks are rendered with a
cover, section dividers, KPI cards, content boxes and bullet layouts.

### PalIAgents - Agent System

A runtime for creating and running specialized agents that can call tools to complete tasks. Agents can be created, run manually, invoked from chat with `@mention` syntax, and also can be scheduled.

Available tools include:

- **Shell execution** (`run_shell`)
- **Python execution** (`run_python`)
- **Web browsing** (`browse_url`)
- **Web search** (DuckDuckGo)
- **arxiv search**
- **RSS feed fetching**
- **CSV query**
- **SQLite query**
- **Knowledge graph query**
- **MQTT** publish/subscribe

Agents maintain their own memory, run history, and chat logs. Tool calls are audited and debug-traced by default.

The tool layer is typed and parallel-aware:

- **Typed tool contracts** — parameters are real JSON Schema (`integer`,
  `boolean`, `array`, `object`, enum values), not everything-as-a-string, so
  local models make far fewer argument mistakes.
- **Parallel read-only calls** — independent safe tools in one model step run
  concurrently; writes, shell and approval-gated tools stay serialized.
- **Tool routing** — each step sees the most relevant tools instead of the full
  catalog; `tool_search` can discover the rest on demand.
- **Drop-in tools** — add a folder under `~/.palimind/tools/<name>/` with a
  `tool.json` and entrypoint; reload with `POST /api/agents/tools/reload`.
- **Source ledger** — web and document searches record their sources; agent
  answers are cited (`[1]`, `[2]`, …) and the run history stores the source
  ledger and citation map.
- **Code tools** — git status/diff/log/show/commit/branch plus an atomic
  `apply_patch` primitive that validates paths before editing.
- **Run checkpoints & resume** — the agent loop persists a bounded checkpoint
  after every step. `GET /api/agents/{id}/runs/{run_id}/state` returns it and
  `POST /api/agents/{id}/runs/{run_id}/resume` continues from the last completed
  step. Stale checkpoints from a previous process are marked resumable at
  startup instead of being lost.
- **Durable job service** — scheduled agents, background tasks, queue items and
  routines are rows in a SQLite jobs table with priority, delays, cron/interval
  recurrence, leases, exponential-backoff retries, cancellation and dead-letter
  handling. Jobs survive restarts; `GET /api/jobs`, `GET /api/jobs/stats` and
  the per-job cancel/retry endpoints expose them.
- **Incremental indexing** — each sync is planned as a durable run with
  per-file `queued`/`skipped`/`deleted` rows. Only changed files are parsed and
  embedded, deleted files are removed, progress is persisted as events, and a
  run can be cancelled or resumed without redoing committed batches.
  Endpoints: `POST /api/index/runs`, `GET /api/index/runs`,
  `GET /api/index/runs/{id}`, `.../events`, `.../cancel`, `.../resume`.
- **Replayable SSE** — every global and per-chat event is persisted with a
  monotonic id. `/api/events` and `/api/streams/{stream_id}/events` honor the
  browser's `Last-Event-ID` header, so a reconnect replays exactly the missed
  frames instead of losing progress.
- **Memory 2.0** — hybrid local-vector + lexical recall with confidence,
  recency, stable ids, superseding and consolidation. Memories can be viewed,
  edited, forgotten via `/api/memory`, and agents get `remember` / `forget`
  tools. Set `PALIMIND_MEMORY_EMBEDDINGS=ollama` to use the local embedding
  model instead of the dependency-free hashed vectors.
- **Workflows & triggers** — JSON DAGs of agent/tool nodes executed through the
  durable job service, with manual, cron, file-change and webhook triggers.
  Endpoints: `/api/workflows`, `/{id}/run`, `/{id}/runs`, `/hooks/{token}`.
  Node outputs are templated (`{{input}}`, `{{nodes.node_id.output}}`).
- **Live voice loop** — `POST /api/voice/chat` takes WAV input, runs local
  energy VAD, transcribes with Whisper, streams the token answer and emits
  base64 Kokoro WAV chunks over one SSE response. `POST /api/voice/chat/stop`
  supports barge-in/cancellation.
- **Local image generation** — optional ComfyUI or stable-diffusion.cpp backend
  (`PALIMIND_IMAGE_BACKEND=comfyui|sdcpp`), `image_generate` agent tool,
  `/api/images/generate` endpoint, `/api/images/status` capability check, and
  generated PNGs saved as local image artifacts under `~/.palimind/images`.
- **Office document tools** — `docx_read`/`docx_write`, `pptx_read`/`pptx_write`
  and `pdf_merge`/`pdf_split`/`pdf_rotate`, all sandboxed to the agent
  workspace with typed schemas and approval-gated write operations.
- **Data tools** — `duckdb_query` over workspace CSV/Parquet/JSON files,
  `xlsx_read`/`xlsx_write`, and `chart_generate` (PNG line/bar/scatter charts),
  all sandboxed and registered in the data tool pack.
- **Local observability** — `GET /api/metrics` exposes request latency/status,
  token usage, tool success/failure, agent-run statuses, index throughput and
  queue depth. A self-contained local dashboard is served at `/metrics` (data
  at `/metrics/data`). Metrics are process-local and never transmitted.
- **Search providers** — pluggable local **SearXNG** with automatic DuckDuckGo
  fallback. `auto` prefers SearXNG when reachable; status/config endpoints are
  `GET /api/search/status`, `GET /api/search/providers`,
  `GET/PATCH /api/search/config`.
- **Backup & restore** — versioned local archives with a manifest and per-file
  SHA-256 checks, optional passphrase encryption (scrypt + AES-GCM), and
  tamper/corruption rejection. API: `GET/POST /api/backup`,
  `POST /api/backup/verify`, `POST /api/backup/restore` (requires
  `confirm=true`). CLI: `pm backup create|list|verify|restore`.

Phase 4 adds an intelligence & automation layer:

- **Adaptive reasoning** — per-agent effort levels (`minimal`…`max`) chosen by a complexity classifier, with auto-escalation when an agent gets stuck.
- **Multi-agent orchestration** — fan-out parallel agents with a shared blackboard, conflict resolution, synthesis, and an arena/tournament mode (max 8 agents).
- **Skills as slash commands** — reusable behaviour bundles in `~/.palimind/skills/` (JSON/YAML), invocable as `/commit`, `/review`, …, with composition and a bundled marketplace.
- **Planning mode** — plan-then-execute with user review/editing, plan templates, a flowchart view, and rollback of file mutations.
- **Goals & background tasks** — objectives with success criteria, `/loop 5m …` scheduling, a monitoring dashboard and completion notifications (50 tasks / 7 days).
- **Structured self-critique** — per-task-type verification checklists, confidence scoring, bounded auto-retry and human review of low-confidence results.
- **Live task checklist** — agents call `todo_write` to keep a 3–7 item plan
  with `pending` / `in_progress` / `completed` states. Every update streams to
  the activity panel as an `agent:todo` event and renders above the tool
  timeline, so long runs show progress instead of a spinner.
- **Context-safe tool results** — oversized tool output is compacted to keep
  both the head and the conclusion (totals, summaries, errors) instead of a
  blind truncation, so agents keep the facts they gathered.
- **Live run peek** — the agents home streams the answer, current step, tools
  and checklist for a run started from the dashboard, with Stop and Open
  actions, so work is never hidden behind a toast.
- **Follow-up suggestions** — after a settled answer the light model proposes
  2–4 next actions (with a deterministic tool-aware fallback). Chips appear in
  chat and on the home live card and prefill the composer when clicked.
- **Automatic model escalation** — if an agent exhausts its step budget without
  a final answer, it emits `agent:escalation` and runs the final synthesis on
  the knowledge base's chat model or `PALIMIND_AGENT_ESCALATION_MODEL`.
- **Live token and cost accounting** — every model call emits cumulative
  `agent:usage`; chat and the home live card show prompt/completion tokens and
  an estimate from `PALIMIND_COST_INPUT_PER_MTOK` /
  `PALIMIND_COST_OUTPUT_PER_MTOK` (0 for local models).
- **Capability benchmark** — `make agent-benchmark` runs deterministic
  research/coding/tool-recovery/checklist/UI scenarios; `make
  agent-benchmark-live` runs the same suite against a local model and writes a
  JSON report under `benchmarks/`. Current live baselines are 5/5 on both
  `qwen3.5:4b` and `qwen3.5:9b`. The suite also guards the loop against
  research loops, unverified edits and checklist-only “work.”
- **Retrieval-aware checklists** — before the first turn, matching workspace
  files seed a 3-item checklist (review material → complete work → verify),
  emitted immediately so the UI shows the plan and the model starts from real
  documents instead of generic steps.
- **Per-stage usage and persisted follow-ups** — run records now store a token
  breakdown (`classifier`, `planning`, `agent`, `verification`, `followups`)
  plus the follow-up suggestions, both visible in the runs view.
- **Escalation policy** — ordered fallback models via
  `PALIMIND_AGENT_ESCALATION_MODELS` and an optional USD ceiling via
  `PALIMIND_AGENT_ESCALATION_MAX_USD`; runs that exceed the ceiling stay on the
  current model with an explicit `agent:escalation` reason.
- **Grok comparison** — `docs/grok-comparison.md` tracks capability-by-capability
  parity (search, X, research, tools, computing, voice, memory, privacy) and
  names the remaining gaps instead of implying full parity.
- **Capability-aware routing** — tasks are routed by required tools, vision,
  code and reasoning depth. Hard tasks on small local models can use a
  reasoning local model or a configured frontier fallback
  (`PALIMIND_FRONTIER_MODELS` / `PALIMIND_AGENT_MODEL_ROUTING`). The chosen
  route is shown in run history. `make routing-probe` proves a hard 4B task
  routes to `grok-4.7` (26.8s) instead of the local model (45.1s), both correct.
- **Head-to-head benchmark** — `make agent-benchmark-vs-grok` runs the same
  scenarios against a local model and a hosted `grok-4.7` baseline using a
  direct OpenAI-compatible client with native `tool_calls` / `role=tool`
  messages, then writes a per-scenario comparison report. The latest native run
  is a **100% vs 100% tie** (local 9B vs Grok-4.7); Grok was much faster, while
  the local run was private and offline.
- **Optional X API** — `x_search` uses X API v2 recent search when
  `PALIMIND_X_BEARER_TOKEN` (or `X_BEARER_TOKEN`) is set, and falls back to the
  public web index when it is not.
- **Thin web/mobile client** — the backend serves a dependency-free,
  phone-friendly chat page at `/client` over the local OpenAI-compatible API.
  It uses the same per-install bearer token as `/v1/*`.

![PalIAgents - Agents](assets/agents.png)

### Computer use (Linux)

Agents can observe and operate Linux desktop apps through the AT-SPI2
accessibility tree. The agent acts on stable refs (`@s<snapshot>:eN`) rather
than pixel coordinates, captures a screenshot only on demand (with optional
ref-bound annotation and local OCR boxes), and falls back to
physical input (XTEST on X11, Mutter RemoteDesktop on Wayland, or the opt-in
`/dev/uinput` kernel backend) only when no semantic action exists.

It is **on by default and works with any app on the desktop**, layered with a
global switch, per-agent `desktop_access` and `desktop_control` flags, an
optional app allowlist, approval for every mutating action, a protected-process
refusal list, a rate limit, an append-only audit log that never stores typed
text, and a Stop that releases held input.

```bash
make desktop-native                 # build the palimind-desktop binary
make desktop-test                   # vendored engine + wrapper tests
make desktop-bundle                 # stage the Tauri sidecar (binaries/)
make desktop-dogfood                # 20-task Linux benchmark (100%, 0 screenshots)
make desktop-x11-check              # X11 gate on the current display
make desktop-x11-gate               # nested Xephyr + openbox X11 gate
palimind-desktop status             # platform, AT-SPI, kernel input, policy
# optional: narrow the default "any app" policy to a list
export PALIMIND_DESKTOP_ALLOWED_APPS=gnome-calculator,gnome-text-editor
```

**How to use it**

1. Start the app (`make dev`, or the packaged desktop app). Computer use is
   already enabled — no agent setup required.
2. Click **Computer Use** in the sidebar, use the tray menu, or press
   `Super+Shift+C`. The popup lists **every window on your desktop**; pick one,
   or drag a screen area.
3. Choose **Ask** for read-only questions (“what does this error mean?”) or
   **Act** to perform the task. Act shows an **Approve / Deny** card for each
   mutating step. The model button in the footer switches the model used for
   desktop runs.
4. `Ctrl+Shift+Escape`, the popup’s Stop button, or the tray’s “Stop desktop
   control” releases held input immediately.
5. Optional: set `PALIMIND_DESKTOP_ALLOWED_APPS` (and restart the backend) to
   restrict the agent to specific apps. Empty means any app.

Settings > Computer use shows the live status, a “How to use” walkthrough,
recent audit entries and the ghost-cursor toggle. The popup’s **Show target**
button draws the click-through ghost cursor without moving the real pointer.

Kernel input is opt-in and needs a udev rule + the `input` group:

```bash
sudo scripts/install-uinput-udev.sh   # sign out and back in afterwards
```

The desktop app exposes a Computer Use popup (`Super+Shift+C`), a screen-region
selection overlay, and a global stop hotkey (`Ctrl+Shift+Escape`). Tauri bundles
`palimind-desktop` as an `externalBin`; `make desktop-bundle` stages it before
`tauri build`. Chromium web content uses an explicit CDP route
(`desktop_browser`) when AT-SPI web-content refs cannot be proven unique.

See [docs/computer-use.md](docs/computer-use.md) for the threat model, the
measured at-spi2-core 2.44 findings, the vendored-engine licence obligations
and the Wayland targeting policy. Computer use is Linux-only.

### Shared browser

The Agents workspace embeds a live Playwright browser that the user and agents
share. It opens automatically when an agent starts a browser tool, renders the
real page as a live frame, and supports the controls people expect: an editable
address bar (`Ctrl/⌘+L`), back/forward/reload, tabs, click, double-click,
right-click, typing, paste, wheel scrolling, zoom, and full screen. The first
user interaction takes control from the agent without a separate modal; **Hand
back** returns it. URLs remain SSRF-checked, including redirects and script
navigation.

### OpenCode Integration

PaliMind stores an OpenCode API key entered once in **Settings** (owner-only
permissions, never logged) and reuses it for its provider proxy. Keys already
configured with the OpenCode CLI are detected automatically — OpenCode v2 keeps
them in its local SQLite database, which PaliMind reads read-only. The launcher
never prompts for credentials in the terminal; without a key, local Ollama
models continue to work.

### Local attachments and model routing

Chat accepts local attachments for multimodal turns. The browser uploads bytes
to `POST /api/uploads`; files are content-addressed under `~/.palimind/uploads`
and deduplicated by SHA-256. Images are sent to the configured local vision
model, PDFs and text files are extracted as context, and unsupported media is
reported clearly instead of failing the turn. `GET /api/models/capabilities`
reports each installed model's tools/vision/reasoning/context metadata so the
UI can route image turns to a vision-capable model automatically.

### Local MCP tools

PaliMind can load tools from any local MCP server over stdio. Declare servers in
`~/.palimind/mcp.json`, mark each one `"trusted": true`, and restart/reload:

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

`POST /api/mcp/reload` restarts the servers and re-registers their tools as
`mcp__<server>__<tool>`. Read-only MCP tools are tier 1; destructive tools stay
behind the approval gate.

### Local OpenAI-compatible API

PaliMind can act as a local OpenAI backend for editors, scripts and other
tools:

```bash
curl -H "Authorization: Bearer $(cat ~/.palimind/api_token)" \
  http://127.0.0.1:8000/v1/models
```

Supported endpoints:

- `GET /v1/models` — installed Ollama/OpenCode models
- `POST /v1/chat/completions` — streaming and non-streaming, including OpenAI
  `tools` / `tool_calls` mapping
- `POST /v1/embeddings` — local embedding model

All `/v1/*` routes use the same per-install bearer token as `/api/*`.

### Thin web / mobile client

A dependency-free chat page is served at `GET /client`. Open
`http://127.0.0.1:8000/client` on a phone or tablet on the same LAN, paste the
token from `~/.palimind/api_token`, and chat through the local
`/v1/chat/completions` API. The page is mobile-sized, respects safe-area insets,
and stores the token only in that browser's local storage.

---

## Architecture

```
Tauri Desktop App
    |  spawns & manages the FastAPI server, registers global hotkeys,
    |  opens the main WebView window
    v
FastAPI Server (127.0.0.1:8000)
    |  REST + SSE streaming endpoints
    v
Ollama (127.0.0.1:11434)
    |  chat / embed / vision inference
    v
Local resources: SQLite (FTS5), vector store, filesystem, tools
```

The Tauri shell spawns the Python backend as a child process, polls it until healthy, then loads the React frontend at `http://127.0.0.1:8000/ui` inside a WebView window.

Backend HTTP routes are split into focused routers under
`palimind/api_routers/routers/` (uploads, jobs, incremental index, research,
tasks, media, voice, models, config, documents, cookbook) alongside the
agent/project/artifact routers. URLs are unchanged; `api_server.py` owns app
creation, startup/shutdown, authentication and the chat surface.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | Core backend (`pyproject.toml` requires ≥3.12) |
| Node.js | 20+ | Frontend build + Tauri CLI |
| Rust | stable | Tauri 2 toolchain |
| Ollama | latest | Local LLM inference engine |
| Linux system libs | — | Tauri deps: `libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev` |

---

## Installation

### 1. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Windows: download from [ollama.com/download](https://ollama.com/download).

### 2. Clone and set up the Python backend

```bash
git clone <your-repo-url> palimind
cd palimind

python -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate

pip install -e "packages/backend[dev]"
# optional hotkey support:
pip install -e "packages/backend[hotkey]"
```

> **Fast path (Linux/macOS):** `./scripts/bootstrap.sh` runs the full setup —
> Python backend (editable + dev tools), frontend/root `npm install`s,
> pre-commit hooks, and model pulls — idempotently. Then just `make dev`.

### 3. Install Rust / Tauri prerequisites

Install Rust via [rustup](https://rustup.rs), then on Linux ensure the required system libraries for Tauri are present (see the [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/), or let `scripts/bootstrap.sh` install them).

### 4. Install frontend and desktop dependencies

```bash
npm install                                   # root (Tauri CLI)
cd packages/frontend && npm install && cd ..  # React frontend
```

### 5. Build the frontend once

The desktop app loads the prebuilt frontend, so build it before launching:

```bash
cd packages/frontend && npm run build && cd ..
```

### 6. Pull required models

```bash
ollama pull nomic-embed-text
ollama pull gemma4:e2b
```

---

## Launching

The one-command launcher installs missing dependencies, starts Ollama, launches the API server, and opens the desktop app. If an older PaliMind API server is already holding the port, the launcher checks its OpenAPI routes and restarts it when the UI needs routes that process does not have (for example after pulling the shared browser or office pipeline):

```bash
pm ui
```

Related flags:

```bash
pm ui --skip-install       # skip dependency install (frontend is built if dist is missing)
pm ui --keep-backend       # keep Ollama/API server running after the app closes
pm ui --port 8001          # use a custom backend port
```

You can also run the backend directly:

```bash
python -m palimind.api_server --host 127.0.0.1 --port 8000
# or: make backend
```

---

## CLI Usage

PaliMind ships a `pm` CLI built with Typer.

### Indexing

```bash
pm init /path/to/project    # initialize a workspace
pm add /path/to/project     # index or update files
```

### Asking questions

```bash
pm ask "What are the key findings in the Q3 report?" --path /path/to/project
```


---

## Configuration

Per-workspace settings live in `.palimind/config.json` (created in the directory where you run `pm init`). Key defaults:

| Key                    | Default                  | Purpose                          |
| ---------------------- | ------------------------ | -------------------------------- |
| `embed_model`          | `bge-m3`                 | Embedding model                  |
| `embed_dim`            | `1024`                   | Must match `embed_model`         |
| `chat_model`           | `gemma4:e2b`             | Chat model                       |
| `chunk_size`           | `1500`                   | Document chunk size              |
| `chunk_overlap`        | `200`                    | Chunk overlap                    |
| `summarise`            | `false`                  | Generate per-file summaries      |
| `retrieval_limit`      | `10`                     | Chunks returned per retrieval    |
| `context_token_budget` | `8000`                   | Max tokens in LLM context        |
| `num_ctx`              | `16384`                  | Ollama context window (must cover `context_token_budget` + prompt overhead) |
| `rerank`               | `false`                  | Cross-encoder reranking (CPU-heavy) |
| `rerank_opt_in`        | `false`                  | Must be `true` to enable `rerank`; `PALIMIND_RERANK=1` overrides |
| `query_rewrite`        | `true`                   | LLM query rewriting at retrieval |
| `ollama_base_url`      | `http://localhost:11434` | Ollama endpoint                  |
| `extensions`           | (many)                   | Indexed file extensions          |

Agent runtime behavior is configurable via environment variables, including:

| Variable | Default | Purpose |
|---|---|---|
| `PALIMIND_ENABLE_PALIAGENTS` | `true` | Master switch for agents |
| `PALIMIND_SHELL_EXEC_TIMEOUT` | `30` | Shell tool timeout (s) |
| `PALIMIND_PYTHON_EXEC_TIMEOUT` | `30` | Python tool timeout (s) |
| `PALIMIND_PYTHON_EXEC_MEMORY_MB` | `512` | Python tool memory cap |
| `PALIMIND_ALLOWED_PATHS` | (empty) | Extra paths file tools may access |
| `PALIMIND_AGENT_SCHEDULER_TICK` | `15` | Scheduler poll interval (s) |

Mixture-of-Experts tuning (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `PALIMIND_MOE_NUM_CTX` | `8192` | Ollama `num_ctx` for MoE LLM calls |
| `PALIMIND_MOE_CONTEXT_BUDGET_TOKENS` | `6000` | Live agent-history budget; older tool exchanges are compacted |
| `PALIMIND_MOE_MAX_CONCURRENCY` | `0` | Max parallel agents (`0` = auto: Ollama/RAM-aware) |
| `PALIMIND_MOE_MAX_AGENT_ITERATIONS` | `12` | Hard ceiling on tool iterations per agent |
| `PALIMIND_MOE_VERIFY` | `true` | Post-synthesis critique + one refinement pass |
| `PALIMIND_LLM_RETRIES` | `2` | Bounded retries for transient LLM failures |

Tool, attachment and model-routing tuning (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `PALIMIND_MAX_PARALLEL_TOOLS` | `4` | Max concurrent read-only tool calls per agent step |
| `PALIMIND_TOOL_ROUTER` | `true` | Show only the most relevant tools to the model |
| `PALIMIND_TOOL_ROUTER_TOP_K` | `12` | Max routed tool schemas per step |
| `PALIMIND_UPLOAD_MAX_MB` | `25` | Max local chat attachment size |
| `PALIMIND_UPLOAD_TEXT_LIMIT` | `30000` | Extracted attachment text cap (chars) |
| `PALIMIND_WORKSPACE_TOOLS_DIR` | (empty) | Optional extra drop-in tool folder |
| `PALIMIND_AGENT_MODEL_ROUTING` | `auto` | `off`, `local`, `auto`, or `frontier` capability routing |
| `PALIMIND_FRONTIER_MODELS` | (empty) | Comma-separated hosted/frontier fallback model ids |
| `PALIMIND_FRONTIER_MIN_COMPLEXITY` | `high` | Minimum complexity for a frontier fallback |
| `PALIMIND_AGENT_ESCALATION_MODELS` | (empty) | Ordered fallback models when a run exhausts its budget |
| `PALIMIND_AGENT_ESCALATION_MAX_USD` | `0` | Escalation cost ceiling (`0` = no ceiling) |
| `PALIMIND_COST_INPUT_PER_MTOK` | `0` | Input price used for per-run cost estimates |
| `PALIMIND_COST_OUTPUT_PER_MTOK` | `0` | Output price used for per-run cost estimates |
| `PALIMIND_X_BEARER_TOKEN` | (empty) | Optional X API v2 token for `x_search` |
| `PALIMIND_X_API_MAX_RESULTS` | `40` | Max recent-search results requested from X |
| `PALIMIND_MCP_ENABLE` | `true` | Load trusted local MCP servers |
| `PALIMIND_JOB_CONCURRENCY` | `2` | Durable job workers |
| `PALIMIND_JOB_POLL_INTERVAL` | `2` | Job poll interval (s) |
| `PALIMIND_JOB_LEASE_SECONDS` | `300` | Job lease/heartbeat window (s) |
| `PALIMIND_MEMORY_EMBEDDINGS` | `hash` | `hash` (offline) or `ollama` for semantic recall |
| `PALIMIND_MEMORY_SEMANTIC_WEIGHT` | `0.65` | Vector score weight |
| `PALIMIND_MEMORY_LEXICAL_WEIGHT` | `0.30` | Keyword score weight |
| `PALIMIND_MEMORY_RECENCY_WEIGHT` | `0.05` | Recency score weight |
| `PALIMIND_MEMORY_CONSOLIDATE_THRESHOLD` | `0.92` | Duplicate-memory similarity threshold |
| `PALIMIND_IMAGE_BACKEND` | `off` | `off`, `comfyui`, or `sdcpp` |
| `PALIMIND_COMFYUI_URL` | `http://127.0.0.1:8188` | Local ComfyUI endpoint |
| `PALIMIND_COMFYUI_CHECKPOINT` | (empty) | Checkpoint name used in the ComfyUI workflow |
| `PALIMIND_SDCPP_BINARY` | `sd` | stable-diffusion.cpp executable |
| `PALIMIND_SDCPP_MODEL` | (empty) | Optional sd.cpp model path |
| `PALIMIND_IMAGE_TIMEOUT` | `240` | Generation timeout (s) |
| `PALIMIND_IMAGE_MAX_SIDE` | `1024` | Maximum image side (px) |
| `PALIMIND_SEARCH_PROVIDER` | `auto` | `auto`, `searxng`, or `ddg` |
| `PALIMIND_SEARXNG_URL` | `http://127.0.0.1:8080` | Local SearXNG base URL |
| `PALIMIND_SEARCH_TIMEOUT` | `8` | Search request timeout (s) |
| `PALIMIND_BACKUP_DIR` | `~/.palimind/backups` | Local backup archive directory |

Phase 4 (agent intelligence & automation) tuning (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `PALIMIND_ADAPTIVE_REASONING` | `true` | Dynamic reasoning-effort allocation |
| `PALIMIND_ADAPTIVE_ESCALATE_ON_STUCK` | `true` | Escalate effort when an agent gets stuck |
| `PALIMIND_REASONING_CLASSIFIER_MODEL` | (light model) | Model for the complexity classifier |
| `PALIMIND_ORCHESTRATOR_MAX_AGENTS` | `8` | Max fan-out agents per orchestration |
| `PALIMIND_ORCHESTRATOR_MAX_CONCURRENCY` | `0` | Max parallel orchestrated agents (`0` = auto) |
| `PALIMIND_ORCHESTRATOR_CONFLICT_RESOLUTION` | `true` | Resolve agent disagreements before synthesis |
| `PALIMIND_SKILLS_ENABLE_MARKETPLACE` | `true` | Allow installing skills from the bundled catalog |
| `PALIMIND_SKILL_MAX_INSTRUCTIONS` | `20000` | Max instruction length for a validated skill |
| `PALIMIND_PLANNING_MODE` | `off` | Default planning mode (`off`/`review`/`auto`) |
| `PALIMIND_PLAN_MAX_STEPS` | `30` | Hard ceiling on generated plan steps |
| `PALIMIND_GOALS_MAX_TASKS` | `50` | Max live background tasks |
| `PALIMIND_GOALS_MAX_DURATION_DAYS` | `7` | Max lifetime of a background task/loop |
| `PALIMIND_GOALS_TICK` | `15` | Background-task runner poll interval (s) |
| `PALIMIND_SELF_CRITIQUE_THRESHOLD` | `0.6` | Min confidence before a result is accepted |
| `PALIMIND_SELF_CRITIQUE_MAX_RETRIES` | `1` | Automatic retries on low confidence |

---

## Security & privacy

- **Local API authentication** — every `/api/*` request needs a per-install bearer token. It is generated on first run at `~/.palimind/api_token` (mode `0600`) and can be overridden with `PALIMIND_API_TOKEN`. The UI receives an HttpOnly same-origin cookie; scripts should send `Authorization: Bearer <token>` or `X-Palimind-Token`.
- **Loopback by default** — the API binds `127.0.0.1` and rejects non-loopback clients unless `PALIMIND_ALLOW_REMOTE=1`. The Docker Compose file publishes the port on loopback and requires `PALIMIND_API_TOKEN`.
- **Proxy authentication** — the OpenCode proxy (`:11435`) requires a separate per-install token (`~/.palimind/opencode_proxy_token` / `OPENCODE_PROXY_TOKEN`), so other local processes cannot spend your key.
- **Approval gate** — new and existing agents require human approval for risky tools (`write_file`, `search_replace`, `run_python`, `run_shell`, browser mutations) by default. Opt out explicitly per agent by setting `human_in_loop_threshold: 0` with `approval_explicit: true`.
- **Execution sandbox** — `run_shell` and `run_python` run under the strongest
  available OS boundary: Linux bubblewrap, a deny-by-default macOS
  `sandbox-exec` profile, or a Windows Job Object with memory/process limits.
  Network is denied and the workspace is read-only unless the agent has write
  access. If no backend can be constructed the tools fail closed;
  `PALIMIND_ALLOW_UNSANDBOXED_EXEC=1` is an explicit, unsafe opt-out.
- **At-rest encryption** — general session/index storage is not encrypted and
  relies on OS account/filesystem permissions. Backup archives support optional
  passphrase encryption (scrypt + AES-GCM).

**Platform support:** the desktop shell builds on Linux, macOS and Windows.
Agent shell/Python execution uses bubblewrap on Linux, `sandbox-exec` on macOS,
and a Job Object on Windows. On unsupported/restricted systems the tools fail
closed unless the unsafe opt-out above is set.

## Tech Stack

| Layer | Technology |
|---|---|
| Desktop shell | Tauri 2 (Rust), Tauri global shortcut plugin |
| Frontend | React, TypeScript, Vite |
| Backend | Python 3.12+, FastAPI, Uvicorn |
| CLI | Typer, Rich |
| AI / Inference | Ollama (Gemma, nomic-embed-text) |
| Embeddings | Ollama embeddings (default `bge-m3`), FAISS HNSW; TurboVec for chat memory |
| STT / TTS | Faster-Whisper, Kokoro-ONNX |
| OCR | EasyOCR (optional extra) |
| Database | SQLite with FTS5 + WAL |
| Encryption at rest | Not implemented — data is protected by OS filesystem permissions only |
| Sandboxing | bubblewrap (`bwrap`) on Linux; shell/Python tools fail closed elsewhere |

---

## Project Structure

```
.
├── packages/
│   ├── backend/            # Python FastAPI backend
│   │   └── palimind/
│   │       ├── agents/     # agent runtime, registry, scheduler, tools
│   │       ├── audio/      # speech-to-text, text-to-speech
│   │       ├── cli/        # Typer CLI (commands, UI)
│   │       ├── core/       # shared infra: embedder, reranker, web search
│   │       ├── document/   # document engine, graph, stream
│   │       ├── generative/ # summariser, responder
│   │       ├── hwfit/      # hardware fitting / recommendations
│   │       ├── ingestion/  # chunkers, parsers, OCR, crawler, video
│   │       ├── llm/        # streaming + mixture-of-expert orchestration
│   │       ├── memory/     # session persistence, hierarchical memory
│   │       ├── opencode/   # OpenCode CLI auth + model routing
│   │       ├── rag/        # index lifecycle, retrieval + generation
│   │       ├── storage/    # SQLite, vector store, chat store
│   │       ├── api_server.py  # FastAPI application (entry point)
│   │       ├── api.py      # public library facade
│   │       ├── config.py   # per-workspace configuration
│   │       ├── settings.py # env-overridable app settings
│   │       ├── opencode_proxy.py  # standalone OpenCode proxy (entry point)
│   │       └── ...
│   └── frontend/           # React + TypeScript + Vite UI
│       └── src/            # components, views
├── apps/
│   └── desktop/            # Tauri 2 Rust shell
├── scripts/                # helper scripts
├── tests/                  # Python tests
└── pyproject.toml          # Python package + CLI entry point
```

---

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/your-feature`.
3. Commit your changes: `git commit -m "feat: add feature"`. Pre-commit hooks
   (ruff fix+format, whitespace, gitleaks) run automatically on commit.
4. Push and open a pull request — CI re-runs the same gates on a clean runner.

Before opening a PR, verify locally:

```bash
make lint              # ruff (backend) + oxlint (frontend)
make check-imports     # no legacy import names
make test              # backend pytest + frontend build/lint
make typecheck         # mypy on gated modules
ruff format --check .  # backend formatting gate (run from packages/backend)
```

- Unit tests: `cd packages/backend && python -m pytest -m "not integration"`
  (the fast local suite). The full suite (`pytest`) needs a running
  backend/Ollama — mark such tests `@pytest.mark.integration`.
- Run the checks above locally before opening a PR. Build installers locally
  with `make build`.

Note: Core backend changes should degrade gracefully when Ollama is not running.

---

PaliMind is an open-source project. Contributions are welcome.
