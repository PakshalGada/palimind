---
name: palimind-backend
description: >
  Python/FastAPI conventions for the Palimind backend. REQUIRED when editing
  anything under packages/backend/palimind, adding API routes, changing
  settings, or touching the CLI. Triggers: FastAPI, uvicorn, router, endpoint,
  pydantic, typer, settings, config, SSE.
---

# Palimind Backend

## Where things live

- Package root: `packages/backend/palimind/` (import name is `palimind`, never `core`).
- Entry points: `palimind/api_server.py` (FastAPI, run with `python -m palimind.api_server`),
  `palimind/opencode_proxy.py` (standalone OpenCode proxy), and
  `palimind/cli/main.py` (Typer `pm`).
- Settings: `palimind/settings.py` (env vars prefixed `PALIMIND_`), workspace
  config: `palimind/config.py` → `.palimind/config.json`.
- Domain layout: `core/` (embedder, reranker, web search, persona, watcher),
  `audio/` (stt/tts), `memory/` (session store, hierarchical memory),
  `opencode/` (CLI auth + model routing), `rag/` (indexing, querying),
  plus `agents/`, `document/`, `generative/`, `hwfit/`, `ingestion/`,
  `llm/`, `storage/`.
- Shared data types live in `palimind/models.py`; domain errors in
  `palimind/exceptions.py`; `palimind/api.py` is the public library facade
  (used by the CLI) — keep it free of HTTP/framework concerns.

## Conventions

- Python >= 3.12 (code uses modern f-string syntax). Type hints everywhere.
- Lint/format with ruff (`make lint`, `make fmt`). Line length 100.
- Blocking work (OCR, Whisper, embeddings) must not run on the event loop —
  push to threads via `anyio.to_thread`/executors.
- SSE endpoints return `StreamingResponse(..., media_type="text/event-stream")`;
  generators must close DB handles when the client disconnects.
- New env-var settings go in `settings.py` with a `PALIMIND_` prefix and a
  safe default; document them in README Configuration table.
- Never log secrets or full prompts at info level.
- Errors: raise subclasses from `palimind/exceptions.py`; routers translate to
  HTTP responses.

## Commands

```
make backend          # run API on :8000
make backend-test     # pytest (unit only; integration tests need Ollama)
make lint / make fmt  # ruff
```

## Gotchas

- The Tauri shell spawns the backend with cwd = `packages/backend`; keep that
  assumption working (`python -m palimind.api_server` must resolve there).
- `api_server.py` registers the agents router directly — follow the existing
  pattern until the router split lands.
