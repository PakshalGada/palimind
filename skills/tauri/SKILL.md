---
name: palimind-tauri
description: >
  Rust/Tauri shell conventions. REQUIRED when editing apps/desktop/src-tauri.
  Triggers: Tauri, Rust, tray, global shortcut, hotkey, screen capture,
  backend spawn, WebView, updater, packaging.
---

# Palimind Desktop Shell (Tauri 2)

## Where things live

- `apps/desktop/src-tauri/src/main.rs` — app entry: spawns the Python backend,
  polls health, registers shortcuts, builds tray, opens Glance window.
- `tauri.conf.json` — window config, bundle targets, icons.
- Icons are generated into `src-tauri/icons/` from `brand/icons/icon.svg`
  (`make icons`). Never hand-edit generated icons.

## Conventions

- The shell treats the backend as a child process: find interpreter → spawn
  `python -m palimind.api_server` with cwd = repo `packages/backend` → poll
  `/health`. Keep cleanup on exit reliable (`BackendProcess` Drop).
- Global shortcuts are platform-aware:
  Win `Ctrl+Shift+Space/V`, macOS `Cmd+Shift+Space/V`, Linux
  `Super+Shift+Space/V`. Registration failure is non-fatal (Wayland).
- Glance popup is created hidden at startup so its JS listeners are ready;
  capture happens BEFORE showing it.
- Tray menu must work on Wayland (menu-based, no click-to-toggle assumptions).
- Prefer `eprintln!("[Palimind] ...")` for diagnostics; logs go to stderr and
  the backend log file in temp dir.

## Commands

```
npm run dev   --prefix apps/desktop   # tauri dev
npm run build --prefix apps/desktop   # tauri build (installers)
cargo check   # inside src-tauri for fast iteration
```

## Gotchas

- `frontendDist`/devUrl point at the backend-served UI; changing this affects
  both dev and release flows (see implementation.md Phase 6 before touching).
- Linux needs webkit2gtk-4.1 system libs; Windows dev uses dev.ps1 at repo root.
