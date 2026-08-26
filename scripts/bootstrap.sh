#!/usr/bin/env bash
# Palimind bootstrap — idempotent one-shot dev environment setup.
# Usage: ./scripts/bootstrap.sh        (Linux/macOS)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say()  { printf "\033[36m[bootstrap]\033[0m %s\n" "$1"; }
ok()   { printf "\033[32m[bootstrap]\033[0m %s\n" "$1"; }
warn() { printf "\033[33m[bootstrap]\033[0m %s\n" "$1"; }

have() { command -v "$1" >/dev/null 2>&1; }

# ── Python 3.12+ ─────────────────────────────────────────────────────────────
if have python3 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)'; then
  ok "Python $(python3 --version | cut -d' ' -f2)"
else
  warn "Python >= 3.12 required — install from https://python.org or your package manager"
  exit 1
fi
PY=python3

# ── Node 18+ ────────────────────────────────────────────────────────────────
if have node; then ok "Node $(node --version)"; else
  warn "Node.js missing — install from https://nodejs.org (or nvm)"; MISSING=1; fi

# ── Rust (Tauri) ────────────────────────────────────────────────────────────
if have cargo; then ok "Rust $(cargo --version)"; else
  warn "Rust missing — install via https://rustup.rs"; MISSING=1; fi

# ── Ollama ──────────────────────────────────────────────────────────────────
if have ollama; then ok "Ollama found"
else
  warn "Ollama missing — install: curl -fsSL https://ollama.com/install.sh | sh"
fi

# ── Linux system libs for Tauri ─────────────────────────────────────────────
if [ "$(uname)" = "Linux" ] && have apt-get; then
  PKGS="libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev patchelf"
  if dpkg -s $PKGS >/dev/null 2>&1; then ok "Tauri system libraries present"
  else
    say "Installing Tauri system libraries (sudo needed)…"
    sudo apt-get update && sudo apt-get install -y $PKGS || warn "apt install failed — see docs/onboarding.md"
  fi
fi

# ── Python backend (editable + dev tools) ───────────────────────────────────
say "Installing backend (editable)…"
"$PY" -m pip install -e "packages/backend[dev]"

# ── Frontend + desktop node deps ────────────────────────────────────────────
if have npm; then
  say "Installing frontend dependencies…"
  ( cd packages/frontend && npm install )
  say "Installing root/desktop dependencies…"
  npm install
else
  warn "Skipping npm installs (npm not found)"
fi

# ── Pre-commit hooks ────────────────────────────────────────────────────────
if "$PY" -m pip show pre-commit >/dev/null 2>&1 && have git; then
  git config --get core.hooksPath >/dev/null 2>&1 || pre-commit install || true
fi

# ── Models ──────────────────────────────────────────────────────────────────
if have ollama; then
  say "Pulling models (skips if already present)…"
  ollama pull nomic-embed-text || true
  ollama pull gemma4:e2b || true
fi

echo
if [ "${MISSING:-}" = "1" ]; then
  warn "Some prerequisites are missing — fix the warnings above, then run: make dev"
else
  ok "All set! Start the app with:  make dev"
fi
