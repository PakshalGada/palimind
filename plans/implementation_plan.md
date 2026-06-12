# Palimind Desktop — Tauri + FastAPI Migration Plan

> **Scope**: Convert PaliMind from a browser-based RAG application into a production-grade Windows desktop app using Tauri v2 + FastAPI sidecar.

---

## Executive Summary

PaliMind is a mature local-first RAG system with ~37K LOC across FastAPI, HTML/CSS/JS frontend, and a deep Python AI pipeline (embeddings, vector search, agent planner, email, TTS/STT). The migration wraps this in a Tauri v2 shell that:

1. **Bundles** the Python backend as a PyInstaller sidecar binary
2. **Manages** the FastAPI process lifecycle (spawn → health check → monitor → restart → shutdown)
3. **Preserves** all existing business logic untouched
4. **Ships** as a single NSIS installer with auto-update support

The architecture is: **Tauri (Rust) → spawns Python sidecar → frontend talks to localhost FastAPI**.

See the detailed sections in companion artifacts:
- [Part 2: Architecture & Diagrams](file:///C:/Users/prath/.gemini/antigravity/brain/cc038595-527f-44d6-8297-f2b63dc1a5bd/plan_part2_architecture.md)
- [Part 3: Startup, FastAPI, Data & UX](file:///C:/Users/prath/.gemini/antigravity/brain/cc038595-527f-44d6-8297-f2b63dc1a5bd/plan_part3_runtime.md)
- [Part 4: Security, Performance, Installer, CI/CD & Roadmap](file:///C:/Users/prath/.gemini/antigravity/brain/cc038595-527f-44d6-8297-f2b63dc1a5bd/plan_part4_production.md)

---

## Open Questions

> [!IMPORTANT]
> Please clarify these before implementation begins:

1. **Ollama Bundling**: Should Palimind check for/install Ollama automatically, or require users to install it separately? (Ollama is ~500MB and has its own installer.)
2. **Email Module**: Should the email module be included in the desktop app, or kept CLI-only for now? It adds significant surface area.
3. **Code Signing**: Do you have a Windows code signing certificate, or should we use self-signed for initial builds?
4. **Update Server**: Will you use GitHub Releases for the update endpoint, or a custom server?
5. **Target Python Version**: Confirm Python 3.11+ for PyInstaller bundling?
6. **sentence-transformers**: The reranker uses `cross-encoder/ms-marco-MiniLM-L-6-v2` — should this ~80MB model be bundled inside the installer, or downloaded on first run?

---

## User Review Required

> [!WARNING]
> **Breaking Change — Folder Picker**: The current folder picker uses `tkinter.filedialog` via subprocess. In Tauri, this MUST be replaced with Tauri's native `dialog` plugin (`tauri-plugin-dialog`). This is the only breaking change to existing backend code.

> [!IMPORTANT]
> **Installer Size**: With PyInstaller + sentence-transformers + numpy + torch (for reranker), the installer will be **~800MB–1.2GB**. If we externalize model downloads to first-run, installer drops to ~200MB.
