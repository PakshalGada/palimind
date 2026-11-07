#!/usr/bin/env bash
# Build palimind-desktop and stage it in the Tauri sidecar layout.
#
# Tauri expects `externalBin` entries as `binaries/<name>-<target-triple>`.
# Add the staged path to apps/desktop/src-tauri/tauri.conf.json when enabling
# the packaged sidecar:
#
#   "bundle": { "externalBin": ["binaries/palimind-desktop"] }
#
# The Python backend locates the same binary via PALIMIND_DESKTOP_BIN or PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRIPLE="$(rustc -vV | awk '/^host:/{print $2}')"
TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT/packages/desktop-native/target}"
DEST="$ROOT/apps/desktop/src-tauri/binaries"

cd "$ROOT/packages/desktop-native"
cargo build --release -p palimind-desktop
mkdir -p "$DEST"
cp "$TARGET_DIR/release/palimind-desktop" "$DEST/palimind-desktop-$TRIPLE"
chmod 0755 "$DEST/palimind-desktop-$TRIPLE"
echo "staged $DEST/palimind-desktop-$TRIPLE"
