# palicode handoff

Session: what is the purpose of palimind (`e9696eae-7c13-494c-ab52-975994bfc7da`)
Provider: opencode / deepseek-v4.1-flash
Working directory: /home/pakshal/palimind
Approval mode: suggest

## Goal

what is the purpose of palimind

## Recent conversation

**user:** what is the purpose of palimind

**assistant:** I'll explore the repository to understand what palimind is.

**assistant:** **PaliMind is a local-first, open-source AI productivity desktop app** — a suite of AI tools bundled around locally-run LLMs (via Ollama), so no cloud subscription or API key is needed for local-only use.

From `README.md`:

**What it does (three pillars):**
1. **PaliSpace — RAG workspace.** Index any folder into a local vector store (FAISS HNSW + SQLite/FTS5), then query it in natural language. Parses PDF/DOCX/PPTX/XLSX/Markdown/code/CSV/video (Whisper transcription), plus knowledge-graph extraction, per-file summaries, episodic chat memory, and web search augmentation.
2. **PalIAgents — agent runtime.** Create/run/schedule specialized agents that call tools (shell, Python, web browse/search, arxiv, RSS, CSV, SQLite, knowledge graph, MQTT). Ships an intelligence layer: adaptive reasoning effort, multi-agent orchestration with an arena mode, skills-as-slash-commands, plan-then-execute mode, goals/background tasks, and structured self-critique.
3. **OpenCode integration** — optional cloud provider using a stored OpenCode API key, with a local authenticated proxy.

**Shape of the system:** a Tauri 2 desktop shell that spawns a Python FastAPI backend (127.0.0.1:8000), which talks to …

## Tools

- ✓ list_dir {"path":"."}
- ✓ glob {"pattern":"*.md"}
- ✓ read_file {"path":"README.md"}

## Resume

```bash
palicode resume e9696eae-7c13-494c-ab52-975994bfc7da
```
