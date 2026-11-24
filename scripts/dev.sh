#!/usr/bin/env bash
# Palimind dev launcher — Linux/macOS parity with dev.ps1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"

# 1. Kill stale backends on :8000
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8000/tcp 2>/dev/null || true
fi

# 2. Ensure backend deps exist
if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "[dev] Backend deps missing — installing palimind (editable)…"
  pip install --quiet -e "packages/backend" || {
    echo "[dev] Install failed. Create a venv: python3 -m venv .venv && source .venv/bin/activate"; exit 1; }
fi

# 3. Start backend in background (log to /tmp)
LOG="${TMPDIR:-/tmp}/palimind-backend.log"
echo "[dev] Starting backend (log: $LOG)…"
# Cap glibc arenas before Python starts: dozens of threads otherwise create
# 64 MB heaps that are never returned to the OS.
export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-4}"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$BACKEND_PID" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL "$BACKEND_PID" 2>/dev/null || true
  fi
}
# HUP covers closing the terminal; TERM/INT cover Ctrl+C and `kill`.
trap cleanup EXIT INT TERM HUP

# `exec` so $! is the Python process itself (not a wrapping subshell), which
# makes the cleanup reliable and lets the backend's parent-death watchdog fire
# if this script is killed without running the trap.
( cd packages/backend && exec "$PY" -m palimind.api_server ) >"$LOG" 2>&1 &
BACKEND_PID=$!

# 4. Launch tauri dev
echo "[dev] Starting tauri dev…"
npm run dev --prefix apps/desktop
echo "[dev] Backend stopped."
