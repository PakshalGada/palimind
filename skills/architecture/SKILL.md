---
name: palimind-architecture
description: >
  Repo map and data flow for the Palimind codebase. Use when locating where a
  change belongs, understanding how the desktop shell, API, and AI pipeline
  connect, or onboarding to the project. Triggers: architecture, repo layout,
  structure, data flow, where do I add X, monorepo.
---

# Palimind Architecture

Palimind is a local-first AI workspace: Tauri 2 desktop shell + FastAPI backend
+ React frontend. All inference runs locally via Ollama.

## Monorepo layout

```
apps/desktop/src-tauri/    Rust/Tauri shell — spawns backend, hotkeys, tray, capture
packages/backend/          Python package "palimind" (FastAPI + Typer CLI)
  palimind/api_server.py   FastAPI app (routers split planned → api/routers/)
  palimind/agents/         agent runtime, scheduler, memory, tools/
  palimind/rag|ingestion/  document parsing, chunking, retrieval
  palimind/llm/            Ollama client, MoE orchestration, SSE streaming
  palimind/storage/        SQLite (FTS5) + vector store
  palimind/services/       OCR, vision, STT, TTS
  palimind/cli/            `pm` Typer CLI
packages/frontend/         React 19 + TypeScript + Vite UI (incl. Glance popup)
skills/                    Developer skills (SKILL.md) for AI coding agents — NOT shipped in app
brand/                     Icons, fonts, design tokens
docs/                      Onboarding, architecture, contributing
docker/                    Backend image + compose (dev/server use)
```

## Runtime data flow

```
Tauri shell (Rust)
  ├─ spawns FastAPI backend as child process (port from env, default 8000)
  ├─ polls /health until ready, then loads WebView at /ui
  └─ registers global shortcuts; captures screen for Glance
FastAPI (127.0.0.1:8000)
  ├─ REST + SSE streaming endpoints (/api/*)
  └─ proxies provider traffic via opencode_router/opencode_proxy (:11435)
Ollama (127.0.0.1:11434)
  └─ chat / embed / vision inference
Local storage: SQLite FTS5 index (.palimind/index.db), vector store, files
```

## Key rules

- Backend binds loopback by default (`palimind/settings.py` SERVER_HOST).
- Per-workspace config lives in `.palimind/config.json`; never commit it.
- The frontend is served BY THE BACKEND at `/ui` in dev; release builds will
  move to static assets (see implementation.md Phase 6).
- OpenCode integration shares `~/.local/share/opencode/auth.json` — do not
  break that file's schema.
