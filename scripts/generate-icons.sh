#!/usr/bin/env bash
# Generate all Palimind app icons from the single brand source SVG.
# Requires: node + @tauri-apps/cli (installed at repo root).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/brand/icons/icon.svg"
OUT="$ROOT/apps/desktop/src-tauri/icons"

if [ ! -f "$SRC" ]; then
  echo "[icons] Source not found: $SRC" >&2
  exit 1
fi

mkdir -p "$OUT"
npx --prefix "$ROOT" @tauri-apps/cli icon "$SRC" -o "$OUT"
echo "[icons] Generated icon set in $OUT"
