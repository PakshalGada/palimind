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
( cd packages/backend && "$PY" -m palimind.api_server ) >"$LOG" 2>&1 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT

# 4. Launch tauri dev
echo "[dev] Starting tauri dev…"
npm run dev --prefix apps/desktop

# 5. Cleanup on exit (trap handles it)
kill "$BACKEND_PID" 2>/dev/null || true
echo "[dev] Backend stopped."
