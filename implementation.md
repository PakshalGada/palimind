# PaliMind — Production Implementation Plan

Master roadmap for taking PaliMind from a working prototype to a **top-tier, cross-platform (Windows / macOS / Linux) production desktop app**: scalable codebase, a pluggable in-app agent-tools system, dedicated **developer skills** (SKILL.md) for AI coding assistants, strong brand identity, and a full Docker + CI/CD developer workflow.

> **Terminology (important):** this plan distinguishes two different kinds of "skills":
> - **Developer skills** (`/skills`, `SKILL.md` files) — consumed by *AI coding agents* (Claude Code, OpenCode, etc.) to build & maintain this repo. They are **not** shipped in the app.
> - **In-app agent tools** (`packages/backend/palimind/agents/tools/`) — the capabilities the app's own agents can invoke (web search, shell exec, etc.). These live **inside the agents folder**, not in `/skills`.

---

## Table of Contents

1. [Current State Audit](#1-current-state-audit)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [Target Repository Structure](#3-target-repository-structure)
4. [Key Decisions (ADRs)](#4-key-decisions-adrs)
5. [Phase 1 — Repo Restructure & Tooling](#5-phase-1--repo-restructure--tooling)
6. [Phase 2 — Developer Skills + Agent Tools](#6-phase-2--developer-skills--agent-tools)
7. [Phase 3 — Backend Scalability & Hardening](#7-phase-3--backend-scalability--hardening)
8. [Phase 4 — Frontend Architecture](#8-phase-4--frontend-architecture)
9. [Phase 5 — Brand, Design System, Icons & Fonts](#9-phase-5--brand-design-system-icons--fonts)
10. [Phase 6 — Cross-Platform Packaging](#10-phase-6--cross-platform-packaging)
11. [Phase 7 — Docker & Local Dev Environment](#11-phase-7--docker--local-dev-environment)
12. [Phase 8 — GitHub Actions CI/CD](#12-phase-8--github-actions-cicd)
13. [Phase 9 — Testing & Quality Gates](#13-phase-9--testing--quality-gates)
14. [Phase 10 — Developer Onboarding](#14-phase-10--developer-onboarding)
15. [Migration & Backward Compatibility](#15-migration--backward-compatibility)
16. [Risk Register](#16-risk-register)
17. [Success Metrics](#17-success-metrics)
18. [Execution Order & Milestones](#18-execution-order--milestones)

---

## 1. Current State Audit

### Repo inventory (verified)

| Area | Files | Status | Pain points |
|---|---|---|---|
| Backend | `core/`, ~14k LOC | ✅ Works | `core/api_server.py` is a **1344-line** god-module |
| Frontend | `frontend/` (React 19 + Vite) | ✅ Works | Single `AppContext.tsx`, only one view (`Agents.tsx`), no router, no tests |
| Desktop shell | `src-tauri/` (`main.rs` 339 lines, `lib.rs` 7) | ✅ Works | All logic in one file; fragile Python discovery |
| CLI | `core/cli/` (Typer) | ✅ Works | — |
| Tests | 1 real test (`test_opencode_auth.py`) + stray `scripts/test_hierarchical_memory.py` | ⚠️ Minimal | <1% coverage |
| CI/CD | — | ❌ None | No `.github/` |
| Docker | — | ❌ None | |
| Brand | `assets/logo.svg`, ad-hoc screenshots | ⚠️ Partial | `tauri.conf.json` references `icons/` that **don't exist** |
| Docs | `README.md` | ⚠️ Only README | `dev.ps1` is Windows-only; no Linux/macOS parity |

### Specific defects found (blocking production)

1. **Hardcoded port `8000` everywhere** — `src-tauri/src/main.rs:189,235` and `tauri.conf.json` both assume `127.0.0.1:8000`. A port collision silently breaks launch; `pm ui --port 8001` is not honored by the Tauri shell.
2. **Deprecated FastAPI lifecycle** — `@app.on_event("startup"/"shutdown")` (`api_server.py:366,380`). Must move to `lifespan`.
3. **Manual env parsing** — `settings.py` hand-rolls `_env_int/_env_bool/_env_list`; replace with `pydantic-settings`.
4. **Fragile Python discovery in Rust** — `main.rs:48-90` probes venvs then falls back to `sh -lc` login-shell hacks. Unreliable on production machines; should be replaced by a bundled interpreter.
5. **Backend spawn requires a dev tree** — `main.rs:223` runs `python -m core.api_server` from the repo root. A shipped binary must not require the user to have Python installed.
6. **`"csp": null`** in `tauri.conf.json` — insecure default.
7. **`frontendDist` is a URL** (`http://127.0.0.1:8000/ui`) — release builds depend on the backend serving HTML; should be static assets.
8. **No updater, no signing, no notarization** — installers can't be distributed through normal channels.
9. **Tools are hard-coded imports** (`core/tools/*`) — adding a capability means editing core code; should move under `agents/tools/`.
10. **`__pycache__/` and `target/` risk** — `.gitignore` covers them, but `.opencode-proxy.log` is committed (a runtime artifact).

---

## 2. Goals & Non-Goals

### Goals

- Fresh clone → running desktop app on **any** OS in < 15 min.
- Every PR runs full matrix CI; every tag ships signed installers for all 3 OSes automatically.
- Adding an in-app agent tool = creating one folder under `agents/tools/`, zero core edits, CI-validated.
- Developer skills (`/skills`) ship in-repo so any AI coding assistant can build & contribute the app consistently.
- Branded icons/fonts/theming consistent across platforms.
- Clear separation: `apps/` (desktop), `packages/` (backend/frontend/shared), `skills/` (developer skills), `brand/`, `docs/`.

### Non-Goals (kept out on purpose, to stay scoped)

- No rewrite of the RAG/retrieval internals — only restructuring + hardening.
- No migration off SQLite → Postgres for the desktop app (SQLite is correct for local-first; server mode gets its own story).
- No cloud backend / multi-tenant SaaS — local-first remains the core promise.
- No native mobile.

---

## 3. Target Repository Structure

```
palimind/
├── .github/
│   ├── workflows/{ci,release,docker,security}.yml
│   ├── ISSUE_TEMPLATE/{bug_report,feature_request}.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS
├── apps/
│   └── desktop/                       # Tauri shell (moved from src-tauri/)
│       └── src-tauri/
│           ├── src/
│           │   ├── main.rs            # builder wiring only
│           │   ├── lib.rs             # public entry + generate_context!
│           │   ├── backend.rs         # child-process lifecycle
│           │   ├── discovery.rs       # Python/interpreter discovery
│           │   ├── hotkeys.rs
│           │   ├── capture.rs
│           │   └── tray.rs
│           ├── icons/                 # generated icon set (Phase 5)
│           ├── tauri.conf.json
│           └── Cargo.toml
├── packages/
│   ├── backend/                       # Python package (moved from core/)
│   │   ├── palimind/
│   │   │   ├── api/
│   │   │   │   │   ├── main.py            # create_app() factory + lifespan
│   │   │   │   │   ├── deps.py
│   │   │   │   │   └── routers/{workspaces,chat,agents,vision,voice,graph,media,settings,health}.py
│   │   │   ├── agents/
│   │   │   │   ├── runtime.py             # agent runtime, scheduler, memory
│   │   │   │   └── tools/                 # ★ IN-APP AGENT TOOLS live here
│   │   │   │       ├── base.py            # Tool ABC + ToolContext + ToolResult
│   │   │   │       ├── registry.py        # scans tools/* + pip entry points
│   │   │   │       ├── loader.py
│   │   │   │       ├── sandbox.py         # permissions, timeout, audit
│   │   │   │       └── <tool>/            # web-search/, shell-exec/, …
│   │   │   ├── rag/                   # ingestion, chunking, retrieval, rerank
│   │   │   ├── llm/                   # ollama client, MoE, streaming
│   │   │   ├── storage/               # vector store, sqlite, metadata
│   │   │   ├── services/              # ocr, vision, stt, tts
│   │   │   ├── cli/                   # pm CLI
│   │   │   └── settings.py            # pydantic-settings
│   │   ├── pyproject.toml
│   │   └── migrations/                # 00X_*.sql
│   ├── frontend/                      # React app (moved from frontend/)
│   │   ├── src/
│   │   │   ├── app/                   # shell, routing, providers
│   │   │   ├── features/{chat,spaces,agents,glance,settings}/
│   │   │   ├── components/ui/         # design-system primitives
│   │   │   ├── lib/{api,sse,tauri}.ts
│   │   │   ├── styles/tokens.css
│   │   │   └── main.tsx
│   │   └── package.json
│   └── shared/                        # generated FE↔BE contract
│       └── src/index.ts               # openapi-typescript output
├── skills/                            # ★ DEVELOPER SKILLS — for AI coding agents (SKILL.md)
│   ├── architecture/SKILL.md          # how the codebase is structured
│   ├── backend/SKILL.md               # Python/FastAPI conventions
│   ├── frontend/SKILL.md              # React/TS conventions
│   ├── tauri/SKILL.md                 # Rust shell conventions
│   ├── rag/SKILL.md                   # retrieval pipeline internals
│   ├── agent-tools/SKILL.md           # how to author an in-app agent tool
│   ├── testing/SKILL.md               # how to run & write tests
│   ├── release/SKILL.md               # how releases are cut & signed
│   └── _template/SKILL.md             # scaffold for new skills
├── brand/
│   ├── icons/{icon.svg + generation config}
│   ├── fonts/
│   ├── tokens/tokens.json
│   └── logo/
├── docker/{backend.Dockerfile,docker-compose.yml,.dockerignore}
├── docs/{onboarding,architecture,agent-tools-authoring,contributing,releasing,security}.md
├── scripts/{bootstrap.sh,bootstrap.ps1,dev.sh,dev.ps1,generate-icons.sh}
├── .devcontainer/devcontainer.json
├── .editorconfig
├── .pre-commit-config.yaml
├── .gitignore
├── CHANGELOG.md · CONTRIBUTING.md · SECURITY.md · LICENSE
├── README.md
└── implementation.md                  # this file
```

**Migration rule:** move with `git mv` only (preserves history), one focused PR per area. The `core` → `palimind` package rename happens here, and every import is updated mechanically (`ruff` has a `--fix` for unused imports but the rename itself is a scripted find/replace + `make check-imports` gate).

---

## 4. Key Decisions (ADRs)

These lock in the choices so reviewers don't re-litigate them.

| # | Decision | Rationale | Alternatives rejected |
|---|---|---|---|
| D1 | Monorepo with `apps/` + `packages/` + `skills/` | Clear ownership, independent CI caching, matches Tauri multi-app conventions | Keep flat layout; Nx/Turborepo (heavier than needed for 3 packages) |
| D2 | **PyInstaller** for backend distribution | Ships a self-contained interpreter; users need no Python | embedded uv venv (still needs Python shim), Nuitka (slow builds), serverless backend |
| D3 | **Pydantic-settings** for config | Typed, env-var precedence, replaces hand-rolled `_env_*` | Environs, custom loader |
| D4 | **Developer skills = `/skills/*/SKILL.md`** (frontmatter: `name` + `description`), **in-app agent tools = `agents/tools/*/`** (manifest + entry-point) | Dev skills are consumed by AI coding agents (Claude/OpenCode); agent tools are runtime capabilities sandboxed & discoverable via a registry | Mixing the two; YAML-only tools; WASM sandbox (overkill v1) |
| D5 | **openapi-typescript** generated client | One source of truth; CI fails on drift | Hand-written types (drift), tRPC (not applicable to Python) |
| D6 | **TanStack Query + Zustand** | Server-state vs local-state split; replaces ad-hoc `AppContext` | Redux Toolkit (heavier), SWR |
| D7 | **Tailwind CSS v4 + CSS tokens** | Single token source → utility classes; matches design-system goals | CSS Modules, styled-components |
| D8 | **GitHub Actions** matrix + Release Please | Ubiquitous, free for OSS, conventional-commit release automation | GitLab CI, self-hosted runners |
| D9 | SQLite stays (desktop), Postgres optional (server mode only) | Local-first promise; WAL + migrations are enough | Full ORM rewrite |
| D10 | Inter + JetBrains Mono (bundled, OFL) | Legibility, cross-platform rendering, legal to bundle | System font stack (inconsistent), paid fonts |

---

## 5. Phase 1 — Repo Restructure & Tooling

**Goal:** clean separation + a single `make` entry point that works on all 3 OSes.

- [ ] `git mv core packages/backend/palimind`; rename `core` → `palimind` across `pyproject.toml`, `[project.scripts]`, all imports, and the Rust spawn command (`main.rs` `-m core.api_server` → `-m palimind.api.main`).
- [ ] `git mv frontend packages/frontend`, `git mv src-tauri apps/desktop/src-tauri`.
- [ ] Split `api_server.py` into `api/routers/` (workspaces, chat, agents, vision, voice, graph, media, settings, health) + `main.py` app factory.
- [ ] Root `Makefile`: `dev`, `build`, `test`, `lint`, `fmt`, `icons`, `typecheck`, `check-imports`.
- [ ] Add `.editorconfig`, `ruff` + `ruff format` + `mypy` (start with `ignore_missing_imports`, gate only `palimind/api` + `palimind/agents`), keep `oxlint` for FE.
- [ ] `.pre-commit-config.yaml`: ruff, ruff-format, mypy (fast), oxlint, trailing-whitespace, `check-added-large-files`, secret scan.
- [ ] Harden `.gitignore`: `__pycache__/`, `*.py[cod]`, `dist/`, `target/`, `node_modules/`, `.venv/`, `.env*`, `*.db`, `.palimind/`, `*.log`. Remove committed `.opencode-proxy.log`.
- [ ] Move `scripts/test_hierarchical_memory.py` → `tests/`.

**Exit criteria:** `make dev` works on all 3 OSes; zero references to old paths (`grep -r "core\."` returns nothing); CI green on restructured tree.

---

## 6. Phase 2 — Developer Skills + Agent Tools

This phase delivers **two distinct systems** that must not be confused:

- **Developer skills** (`/skills`) — `SKILL.md` files consumed by **AI coding agents** to build & maintain this repo. Not shipped in the app.
- **In-app agent tools** (`packages/backend/palimind/agents/tools/`) — runtime capabilities the app's own agents invoke.

### 6a. Developer skills (`/skills/*/SKILL.md`)

Each skill is a folder with a `SKILL.md` using the same frontmatter convention as Claude Code / OpenCode skills (`name` + `description` that states *when* to use it):

```markdown
---
name: palimind-backend
description: >
  Python/FastAPI conventions for the Palimind backend. Use when editing
  packages/backend/palimind, adding an API router, or wiring a new
  in-app agent tool. Triggers: FastAPI, uvicorn, router, Ollama, retrieval.
---
# Palimind Backend

## When this skill MUST be used
- Editing anything under packages/backend/palimind/
- Adding a route, dependency, or settings field
- Authoring an agent tool in agents/tools/
...
```

Initial skill set (one per concern, kept small and focused):

| Skill | Teaches the coding agent |
|---|---|
| `architecture` | repo layout, data flow (Tauri → API → Ollama → stores), module ownership |
| `backend` | FastAPI router split, `create_app()`, deps, error shape, settings |
| `frontend` | feature folders, TanStack Query, design tokens, SSE client |
| `tauri` | Rust shell modules, backend spawn, hotkeys, tray, packaging |
| `rag` | ingestion → chunking → embed → retrieve → rerank pipeline |
| `agent-tools` | how to author a tool in `agents/tools/` (manifest + ABC + sandbox) |
| `testing` | pytest markers, Vitest, Playwright, how to run locally |
| `release` | versioning, signing, release pipeline |

**Exit criteria:** an AI coding agent given only `/skills` + the repo can (a) locate the right code, (b) follow conventions, (c) author a new agent tool correctly — without reading docs/ by hand.

### 6b. In-app agent tools (`agents/tools/`)

**Goal:** every capability the app's agents can invoke becomes a self-contained folder under `agents/tools/`, discoverable without core edits.

```python
# agents/tools/_template/tool.py — canonical shape every tool follows
from palimind.agents.tools.base import Tool, ToolContext, ToolResult

class WebSearch(Tool):
    name = "web-search"
    permissions = ["network"]          # network | fs-read | fs-write | shell
    timeout_s = 30
    async def run(self, ctx: ToolContext, **kwargs) -> ToolResult:
        ...
```

- `base.py` — `Tool` ABC, `ToolContext` (workspace, allowed paths, audit sink), `ToolResult`.
- `registry.py` — scans `tools/*/tool.json` (name, version, permissions, timeout, input/output schema), validates against a JSON Schema, and merges pip-installed packages exposing a `palimind.agent_tools` entry point (third-party tools).
- `sandbox.py` — enforces permission allow-list, timeouts, output-size caps, and audit logging (reuses `core/tools/audit.py` semantics). Platform-agnostic (timeout + memory via subprocess + path allowlists) so behavior is identical on Win/macOS/Linux.
- Agents resolve tools **only** through the registry — remove direct `core/tools/*` imports.
- CLI: `pm tools list | info <name> | doctor <name>`.
- Frontend: tools browser view (installed tools, permissions, enable/disable).

**Migration (11 tools):** port each `core/tools/*.py` → `agents/tools/<name>/`: `arxiv-search`, `browse-url`, `csv-query`, `fetch-rss`, `mqtt`, `query-graph`, `shell-exec` (`run_shell`), `python-exec` (`run_python`), `sqlite-query`, `web-search`, `knowledge-graph`. Keep a thin legacy adapter during migration.

**Exit criteria:** `pm tools list` shows all 11; a brand-new tool requires zero core edits; `pm tools doctor` passes for all.

---

## 7. Phase 3 — Backend Scalability & Hardening

- [ ] **App factory + `lifespan`:** replace `@app.on_event` and module-globals with `create_app()`; init Ollama client, DB pools, watcher in `lifespan` startup/shutdown.
- [ ] **Settings:** migrate `settings.py` + `config.py` → `pydantic-settings` (`PalimindSettings`, `WorkspaceConfig`), preserve `PALIMIND_*` env names as aliases for backward compat.
- [ ] **Port flexibility:** read port from env/CLI (`PALIMIND_PORT`); Tauri shell picks it up (stop hardcoding 8000) — see Phase 6.
- [ ] **Structured logging:** `structlog` (JSON optional), request-ID middleware, rotation, no secrets.
- [ ] **Error handling:** central handlers mapping `exceptions.py` → RFC-7807 error shape.
- [ ] **Async correctness:** wrap blocking calls (EasyOCR, Whisper, sentence-transformers) in `anyio.to_thread`; make SSE generators cancellation-safe (`async def` generators already used — verify all close DB handles on disconnect).
- [ ] **SQLite hardening:** WAL mode, `busy_timeout`, single-writer guard, `migrations/00X_*.sql` runner.
- [ ] **Security:**
  - Loopback default; token auth required when LAN mode is on (extend existing PaliTeams auth to all routers).
  - Real CSP in `tauri.conf.json`; serve frontend from static assets (Phase 6).
  - Shell/python agent-tool limits portable across OSes.
- [ ] **Performance:** lazy-import heavy models (OCR/vision/TTS); `/health` (liveness) + `/ready` (models loaded, Ollama reachable).
- [ ] **Observability:** optional OpenTelemetry around retrieval + LLM (off by default).

**Exit criteria:** mypy passes on `palimind/api` + `palimind/agents`; all routers behind typed deps; latency unchanged or better; port configurable end-to-end.

---

## 8. Phase 4 — Frontend Architecture

- [ ] Feature folders (`features/chat|spaces|agents|glance|settings`).
- [ ] TanStack Query (server state) + Zustand (local UI) replacing `AppContext.tsx`.
- [ ] Generate typed API client via `openapi-typescript` → `packages/shared`; CI drift check.
- [ ] Centralize SSE in `lib/sse.ts` (reconnect/backoff, abort on unmount).
- [ ] Router (TanStack Router or React Router) + code splitting so the Glance popup (`glance/` today) loads instantly.
- [ ] Vitest + React Testing Library; Playwright smoke test.
- [ ] Error boundaries per feature + global toast system.
- [ ] Accessibility pass (keyboard nav, focus rings, ARIA, contrast-checked themes).

---

## 9. Phase 5 — Brand, Design System, Icons & Fonts

### Identity

- **Feel:** calm intelligence — dark-first, glassy, one confident accent.
- **Palette:** Teal `#14B8A6` primary (matches existing CLI theme), Violet `#8B5CF6` secondary. Full palette as tokens.
- **Typography:** **Inter** (UI, variable) + **JetBrains Mono** (code), bundled via `@fontsource-variable/inter` + `@fontsource/jetbrains-mono` (OFL — legal to ship).
- **Shape:** 12px card radius, 8px controls, subtle borders over shadows, `backdrop-blur` accents.

### Tokens

`brand/tokens/tokens.json` → generated `packages/frontend/src/styles/tokens.css` + Tailwind v4 config. Themes: `dark` (default), `light`; runtime accent swappable (teal/purple/amber/blue/coral — mirrors existing `pm config theme`).

### Icons (fixes the missing `icons/` referenced by `tauri.conf.json`)

- One `brand/icons/icon.svg` (rounded-square gradient tile, "mind node" mark from current `logo.svg`).
- Generate with Tauri CLI:
  ```
  scripts/generate-icons.sh  # npx @tauri-apps/cli icon brand/icons/icon.svg -o apps/desktop/src-tauri/icons
  ```
  → `32x32.png`, `128x128.png`, `128x128@2x.png`, `icon.icns`, `icon.ico`, tray + Store assets.
- In-app icons: **Lucide** (`lucide-react`).
- Add `brand/brand-guidelines.md`; refresh `assets/` screenshots after redesign.

**Exit criteria:** correct icon on dock/taskbar/tray/installer on all OSes; identical font rendering; instant theme switch.

---

## 10. Phase 6 — Cross-Platform Packaging

- [ ] **Static frontend in release:** `frontendDist` → built `dist/`; keep `devUrl` proxy for `tauri dev`. Decouples release from a live backend serving HTML.
- [ ] **Bundled backend:** PyInstaller onefile per-OS in CI → Tauri `resources/`; `backend.rs` spawns from resource dir with a bundled interpreter (kills the fragile `find_python` logic and the `python -m core.api_server` requirement).
- [ ] **Port handshake:** shell chooses a free port, passes it to the backend, health-polls until ready (replaces hardcoded 8000).
- [ ] **Auto-updater:** `tauri-plugin-updater` + signed manifests (minisign key as GitHub secret).
- [ ] Per-OS:
  - **Windows:** NSIS + MSI; sign with Azure Trusted Signing (documented).
  - **macOS:** DMG + universal binary (aarch64 + x86_64); Developer ID signing + notarization (CI-ready via secrets, skip with warning if absent).
  - **Linux:** AppImage (exists) + `.deb` + `.rpm`; verify WebKitGTK 4.1; test Wayland + X11 (polish the existing hotkey fallback).
- [ ] Tray semantics parity (close-to-tray vs quit).
- [ ] First-run experience: hardware detection via `hwfit`, model download progress, permission explainer.

---

## 11. Phase 7 — Docker & Local Dev Environment

### `docker/backend.Dockerfile`

Multi-stage, CPU-first: builder `python:3.12-slim` → venv; runtime adds `libgl1`/`libglib2.0` (EasyOCR), `USER nonroot`, `HEALTHCHECK /health`, `EXPOSE 8000`.

### `docker/docker-compose.yml`

```yaml
services:
  backend:   # palimind API :8000
  ollama:    # ollama/ollama :11434, volume ollama_models
  # optional NVIDIA GPU profile via deploy.resources.reservations.devices
```

**Purpose:** consistent contributor env + headless/server deployments (e.g., run indexing on a home server; desktop connects remotely). Desktop packaging does **not** use Docker.

- [ ] `.dockerignore` (exclude `.venv`, `node_modules`, `target`, images).
- [ ] Publish `ghcr.io/<org>/palimind-backend:{sha,latest}` on main + tags.
- [ ] `.devcontainer/` reusing compose → "Open in Codespaces" button in README.
- [ ] `scripts/bootstrap.sh|ps1` — idempotent, OS-detected, installs Python/Node/Rust/Ollama/pre-commit then `make dev`.

---

## 12. Phase 8 — GitHub Actions CI/CD

### `ci.yml` (PR + push to main; matrix `ubuntu-24.04`, `windows-2022`, `macos-14`)

Parallel jobs, paths-filtered, concurrency-cancelled:
1. **backend-lint** — ruff check/format + mypy (pip cache).
2. **backend-test** — pytest + coverage (threshold 40% ratcheting up); `ollama` service container for integration markers.
3. **frontend** — `npm ci && lint && build` + Vitest + `tsc -b`.
4. **openapi-drift** — regenerate TS client, `git diff --exit-code`.
5. **desktop-check** — `cargo clippy -D warnings` + `cargo fmt --check` + Linux debug build.
6. **security** — `pip-audit`, `npm audit --production`, `gitleaks`.

### `release.yml` (on tag `v*`; Release Please manages versions + CHANGELOG)

Matrix → artifacts → draft GitHub Release (auto-generated notes):
- Linux: AppImage + `.deb` + `.rpm`
- Windows: NSIS + MSI
- macOS: DMG universal

Steps per OS: build FE → PyInstaller backend → `tauri build` (with updater signing key) → notarize macOS → `SHA256SUMS`.

### `docker.yml` — buildx build/push GHCR on main + tags.

### Branch protection

PR required + all checks green + 1 approval + up-to-date; squash-merge; conventional-commit title check.

---

## 13. Phase 9 — Testing & Quality Gates

| Layer | Tool | Scope |
|---|---|---|
| Python unit | pytest + pytest-asyncio | tools registry, chunkers, config, memory |
| Python integration | pytest `integration` marker + `respx` | routers vs temp workspace, mocked Ollama |
| Contract | schemathesis (later) | fuzz OpenAPI endpoints |
| FE unit | Vitest + RTL | hooks, SSE parser, critical components |
| E2E | Playwright | launch → index sample → ask question |
| Rust | cargo test + clippy | backend spawn lifecycle |
| Load (optional) | locust | concurrent SSE chats |

Also: coverage badge, `SECURITY.md`, `CONTRIBUTING.md` quality bar.

---

## 14. Phase 10 — Developer Onboarding

### `docs/onboarding.md` — the 15-minute setup

1. Prereqs (auto-installed where possible by bootstrap).
2. `git clone … && ./scripts/bootstrap.sh` (`.ps1` on Windows).
3. `ollama pull nomic-embed-text gemma4:e2b`.
4. `make dev` — what success looks like.
5. Verify: `curl localhost:8000/health` → `{"status":"ok"}`.
6. Troubleshooting matrix (port busy, Ollama down, WebKitGTK on Linux, PowerShell execution policy).
7. "First PR" walkthrough tied to `docs/agent-tools-authoring.md` (add a hello-world agent tool end-to-end).

### Collaboration

- `.github/CODEOWNERS`; issue templates; PR checklist (tests + docs + conventional title).
- `docs/contributing.md` (branching, conventional commits, review SLAs, release process).
- `docs/architecture.md` (updated diagram: Tauri → API → Ollama → stores + agent-tools lifecycle).
- GitHub Project board, discussion categories, `good first issue` automation.

---

## 15. Migration & Backward Compatibility

Existing users have `.palimind/` workspaces and `config.json`. The restructure must not break them.

- [ ] Keep `.palimind/` layout, DB filename, and `config.json` keys unchanged.
- [ ] `config.py` DEFAULTS preserved as the `WorkspaceConfig` model defaults; unknown keys tolerated (warn, not fail).
- [ ] Keep `PALIMIND_*` env names working (map to new pydantic-settings fields as aliases).
- [ ] CLI surface `pm …` unchanged (add, not remove, commands).
- [ ] OpenCode auth (`~/.local/share/opencode/auth.json`) integration untouched.
- [ ] Ship a `db` schema version; migration runner applies idempotently.

---

## 16. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| PyInstaller misses a native dep (EasyOCR/Whisper) | High | Med | CI smoke test launches the bundled backend on all 3 OSes |
| Code signing/notarization friction on macOS/Windows | High | Med | Degrade gracefully (unsigned dev builds), document Azure Trusted Signing + Apple notary |
| `core`→`palimind` rename breaks imports mid-flight | Med | High | Mechanical rename + `make check-imports` gate in the same PR |
| Agent-tool sandbox too permissive → security hole | High | Low | Allow-list permissions by default, audit log, `doctor` tests, security review on `shell`/`python` tools |
| SQLite under concurrent agent + UI writes | Med | Med | WAL + busy_timeout + single-writer guard |
| Wayland global hotkeys unreliable | Low | Med | Existing fallback path polished; document per-compositor quirks |
| Mono-repo CI slow/costly | Low | Med | Paths-filters, per-job pip/npm/cargo caching, concurrency cancel |

---

## 17. Success Metrics

| Metric | Target |
|---|---|
| Fresh-clone → running app | < 15 min, all 3 OSes |
| CI matrix runtime | < 12 min per PR |
| Test coverage (backend) | ≥ 60% after M7 (40% at M2) |
| Agent tools: add-a-tool effort | 1 folder, 0 core edits |
| Release cadence | tagged release → installers in < 30 min |
| Type safety | mypy clean on `api`/`agents`; zero openapi drift |
| Security gates | gitleaks + pip-audit + npm audit green |

---

## 18. Execution Order & Milestones

| Milestone | Contents | Depends on | Effort |
|---|---|---|---|
| **M0 — Foundations** | Phase 1 restructure, Makefile, lint/typecheck/pre-commit, gitignore | — | 1–2 d |
| **M1 — Skills & Tools** | Phase 2: developer skills (`/skills`) + agent tools (`agents/tools/`) + migrate 11 tools | M0 | 2–3 d |
| **M2 — CI** | ci.yml + branch protection | M0 | 1 d |
| **M3 — Backend hardening** | Phase 3 (router split starts in M0) | M0 | 3–4 d |
| **M4 — Brand & FE** | Phases 5 + 4 (tokens/fonts/icons → state mgmt) | M0 | 3–5 d |
| **M5 — Packaging** | Phase 6 cross-platform builds + updater | M3, M4 | 3–5 d |
| **M6 — Docker & DX** | Phase 7 + devcontainer + bootstrap | M0 | 1–2 d |
| **M7 — Release pipeline** | release.yml + GHCR + docs | M5, M6 | 2 d |

**Definition of production-ready:** every `make dev`/`make test`/`make build` green on Win/macOS/Linux; tags → signed installers automatically; in-app agent tools are folder-only additions under `agents/tools/`; developer skills ship in `/skills` for AI coding agents; branded and consistent everywhere; zero secrets in repo.

---

*Suggested first PR: M0 restructure (pure `git mv` moves + Makefile + lint config). Everything else builds on it.*
