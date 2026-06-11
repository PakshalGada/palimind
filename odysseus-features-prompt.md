# Odysseus — Feature Implementation Prompt & Architecture Analysis
## In-Chat Model Switcher UI + Cookbook (Hardware-Aware, 270+ Models, One-Click Serve)

---

## PART 1 — CLAUDE CODE PROMPT (paste this into Claude Code)

```
You are working inside the Odysseus self-hosted AI workspace repo
(https://github.com/pewdiepie-archdaemon/odysseus, dev branch).
The stack is: FastAPI (app.py) · Python backend in core/, src/, routes/, services/ ·
Vanilla JS frontend in static/index.html + static/app.js + static/js/ · SQLite via SQLAlchemy.

Implement TWO features below. Read every file you touch before editing.
Do not rewrite files wholesale — make surgical additions only.
Run `python -m py_compile` on every .py you change and
`node --check` on every .js you change before finishing.

─────────────────────────────────────────
FEATURE 1 — IN-CHAT MODEL SWITCHER UI
─────────────────────────────────────────

Goal: The user must be able to switch the active model from the chat interface
itself without going to Settings. Currently model selection is a settings-only
flow. Add a lightweight inline switcher that:

  1. Shows the currently active model name as a clickable badge / pill
     in the chat toolbar (near the send button or below the input box).
  2. On click, opens a compact dropdown/popover listing:
       – All configured providers and their available models
         (fetched from the existing GET /api/models or equivalent endpoint).
       – A search/filter input at the top of the dropdown.
       – The currently active model highlighted.
  3. Selecting a model updates the active model for that chat session
     immediately (no page reload). Persist the choice to the session
     and to user settings via the existing PATCH /api/settings or
     session update endpoint.
  4. The badge reflects the new model name instantly after selection.
  5. If the model list is loading show a spinner; on error show a toast.

Files to read first (do not skip):
  - static/index.html            — locate the chat toolbar DOM structure
  - static/app.js                — find where currentModel / selectedModel is stored
  - static/js/chat.js            — (if it exists) chat send/receive logic
  - routes/model_routes.py       — model list + update endpoints
  - routes/chat_routes.py        — how model param is passed into chat completions
  - core/database.py             — session/settings schema

Implementation plan:
  A. Backend (routes/model_routes.py or routes/chat_routes.py):
       – Ensure GET /api/models returns {provider, model_id, display_name}[]
         for all configured providers (Ollama, vLLM, llama.cpp, OpenAI, etc.).
       – Add or confirm PATCH /api/session/{session_id}/model  {model_id}
         that updates the active model for a session.

  B. Frontend (static/js/ — add static/js/model-switcher.js):
       – Create ModelSwitcher class/module.
       – On init: fetch /api/models, build dropdown DOM, inject into toolbar.
       – On model select: call PATCH endpoint, update in-memory currentModel,
         re-render badge. Emit a custom event `odysseus:model-changed` so
         other modules (agent, document editor) can react.
       – Keyboard: ArrowUp/Down to navigate list, Enter to confirm, Escape to close.
       – CSS: add rules to static/style.css — use existing CSS variables
         (--bg-secondary, --text-primary, --accent, --border-color) so it
         respects all themes including dark mode.

  C. Wire it up in static/app.js or static/index.html:
       – Import / call ModelSwitcher.init() after DOM ready.
       – Pass current session model to it on session load.

  D. Do NOT touch the Settings page model list — it remains as-is.
     The new switcher is additive, not a replacement.

─────────────────────────────────────────
FEATURE 2 — COOKBOOK (HARDWARE-AWARE, 270+ MODELS, ONE-CLICK SERVE)
─────────────────────────────────────────

The Cookbook already exists in this repo. The goal here is to EXTEND it:

Read these files first (do not skip):
  - services/hwfit/              — entire directory (hardware detection, model catalog, fit scoring)
  - routes/cookbook_routes.py    — Cookbook REST endpoints
  - routes/hwfit_routes.py       — hwfit/hardware endpoints
  - static/js/cookbook.js        — Cookbook frontend (if exists; may be cookbook*.js)
  - scripts/odysseus-cookbook    — background serve script

────────────────────────────────
2A. Hardware Detection (services/hwfit/)
────────────────────────────────

  Ensure the hardware probe covers:
    - NVIDIA GPUs: use `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader`
    - AMD GPUs:    use `rocm-smi --showmeminfo vram` OR `rocminfo`
    - Apple Metal: use `system_profiler SPDisplaysDataType` (macOS only)
    - CPU RAM:     use psutil.virtual_memory() as fallback
    - VRAM-less / iGPU: detect and flag for CPU-only quantisations (Q4_K_M, Q3_K_S)

  Windows-specific probe additions:
    - Primary: `nvidia-smi.exe` (same flags, works natively on Windows)
    - Fallback: `wmic path win32_VideoController get AdapterRAM,Name`
    - Do NOT call `rocm-smi` or `rocminfo` on Windows — ROCm has no Windows userspace.
    - AMD VRAM on Windows: use `wmic` or `dxdiag /t dxdiag_output.txt` parsing.
    - Detect presence of WSL2 by checking for /proc/version containing "Microsoft"
      when running under Python on Linux — if found, flag that vLLM serving is
      available (WSL2 with CUDA passthrough).

  Expose detected hardware via GET /api/cookbook/hardware → {
    gpus: [{name, vram_mb, backend}],   # backend = cuda|rocm|metal|cpu
    total_ram_mb,
    os_platform,               # linux | windows | macos
    wsl2_detected,
    serve_engines_available    # ["llama.cpp", "vllm", "ollama", "sglang"]
  }

────────────────────────────────
2B. Model Catalog (270+ models)
────────────────────────────────

  The catalog lives in services/hwfit/ (likely catalog.py or models.json/yaml).
  Verify and extend to 270+ entries. Each entry must have:
    {
      id:          "bartowski/Llama-3.1-8B-Instruct-GGUF",
      name:        "Llama 3.1 8B Instruct",
      family:      "llama",
      params_b:    8,
      quants: [
        { tag: "Q4_K_M",  vram_mb: 5200,  quality: "good",    file_size_gb: 4.9  },
        { tag: "Q8_0",    vram_mb: 9100,  quality: "best",    file_size_gb: 8.5  },
        { tag: "FP8",     vram_mb: 10200, quality: "fp8",     file_size_gb: 9.6  },
        { tag: "AWQ",     vram_mb: 6400,  quality: "awq",     file_size_gb: 6.0  }
      ],
      hf_repo:     "bartowski/Llama-3.1-8B-Instruct-GGUF",
      use_cases:   ["chat", "coding", "reasoning"],
      min_vram_mb: 4096,   # minimum to run any quant
      tags:        ["popular", "instruct"]
    }

  Families to cover (ensure at least these are in catalog):
    Llama 3.x (8B, 70B, 405B variants) · Qwen 2.5 (0.5B–72B) · Mistral v0.3 / Mixtral ·
    Phi-3/3.5/4 · Gemma 2/3 (2B, 9B, 27B) · DeepSeek-R1/V3 distills · Falcon ·
    CodeLlama / DeepSeek-Coder · Wizard · OpenChat · StarCoder2 · Yi · InternLM ·
    Nous-Hermes · Command-R · solar-pro · SmolLM · TinyLlama · (vision:) LLaVA ·
    MiniCPM-V · InternVL · Qwen-VL.

────────────────────────────────
2C. Fit Scoring
────────────────────────────────

  For each catalog entry, compute a fit_score(hardware, quant):
    - VRAM fit:    1.0 if quant.vram_mb ≤ detected_vram_mb * 0.90 else penalise
    - Speed score: rough tokens/sec estimate from (vram_mb / quant.vram_mb) ratio
    - Quality:     q8 > fp8 > awq > q5 > q4 > q3 (ordinal weight)
    - Context fit: penalise if model context > available_vram allows

  Return models sorted by fit_score DESC. Flag:
    - FITS_PERFECTLY  — runs with headroom
    - FITS_TIGHT      — runs but ≤10% headroom
    - CPU_FALLBACK    — exceeds VRAM, will run on RAM (slow)
    - TOO_LARGE       — even Q3 won't fit RAM

  Expose via GET /api/cookbook/recommendations?top=20 → ranked list with scores.

────────────────────────────────
2D. One-Click Download & Serve
────────────────────────────────

  Download flow (already exists — verify and extend):
    POST /api/cookbook/download  { hf_repo, quant_tag }
      → spawns background job (scripts/odysseus-cookbook download)
      → streams progress via GET /api/cookbook/download/{job_id}/progress (SSE)
      → on completion, registers model in local model registry

  Serve flow:
    POST /api/cookbook/serve  { model_id, engine, n_gpu_layers?, context_size? }
      → selects engine based on platform + detected hardware:
          Linux + NVIDIA CUDA  → vLLM (preferred for large) or llama.cpp --cuda
          Linux + AMD ROCm     → vLLM (ROCm build) or llama.cpp --rocm
          Linux CPU-only       → llama.cpp (--cpu)
          macOS Apple Silicon  → llama.cpp (--metal) or Ollama
          Windows + NVIDIA     → llama.cpp.exe --cuda  (NOT vLLM — CUDA-only Windows)
          Windows + no GPU     → llama.cpp.exe --cpu   or Ollama
          Windows + AMD        → Ollama (ROCm on Windows has no vLLM support)
      → starts process, returns { endpoint_url, model_id }
      → auto-registers endpoint in Settings so it immediately appears
        in the Model Switcher (Feature 1)

  Platform-specific engine launch:
    Linux:   subprocess with tmux (existing scripts/odysseus-cookbook)
    Windows: subprocess with `cmd /c start /b` or PowerShell Start-Process
             (tmux is NOT available natively on Windows — do NOT use it)
             store PID in data/cookbook_processes.json for stop/restart
    macOS:   existing tmux path (Homebrew tmux is available)

  Stop/restart:
    POST /api/cookbook/serve/{model_id}/stop
    POST /api/cookbook/serve/{model_id}/restart

────────────────────────────────
2E. Frontend (static/js/cookbook*.js)
────────────────────────────────

  The Cookbook UI page should have three panels:

  Panel A — "What fits my hardware?"
    - Auto-fetches /api/cookbook/hardware on load, shows GPU/RAM summary card.
    - Calls /api/cookbook/recommendations, renders grid of model cards.
    - Each card: model name, family badge, param count, best-fit quant tag,
      estimated VRAM, fit badge (FITS / TIGHT / CPU), download button.
    - Filter bar: search by name, filter by family / use-case / size.

  Panel B — "Manage Downloads"
    - Lists all models in data/huggingface/ with quant tags and file sizes.
    - Per model: Serve button (opens engine picker), Delete button.
    - Active serves shown with green status dot + current endpoint URL.
    - "Add to Chat" button calls Model Switcher to switch to this model.

  Panel C — "Servers" (existing remote-server SSH flow — do not break)
    - Keep as-is; just ensure it does not conflict with local serve state.

─────────────────────────────────────────
CROSS-CUTTING CONCERNS
─────────────────────────────────────────

  1. When a Cookbook serve completes, auto-call POST /api/models/register
     { provider: "llama.cpp"|"vllm", url: endpoint_url, model_id }
     so the new model appears instantly in the Model Switcher dropdown.

  2. The Model Switcher should poll GET /api/cookbook/serves (list of active
     serves) on open and prepend a "🍳 Local" section above API models.

  3. All new API routes must be auth-guarded with the existing
     `Depends(get_current_user)` pattern from core/auth.py.

  4. Write no new dependencies unless absolutely necessary. Prefer stdlib
     subprocess, psutil (already in requirements.txt), and platform.system().

  5. After all changes: run the full test suite `python -m pytest` and fix any
     broken tests. Add at least 2 tests for the hardware probe (mock subprocess).

─────────────────────────────────────────
DELIVERABLE CHECKLIST
─────────────────────────────────────────

  [ ] static/js/model-switcher.js      — new file
  [ ] static/style.css                 — model-switcher CSS additions
  [ ] static/app.js                    — ModelSwitcher.init() wired
  [ ] routes/model_routes.py           — verified/extended model list endpoint
  [ ] routes/cookbook_routes.py        — extended with hardware, serve, register
  [ ] routes/hwfit_routes.py           — hardware probe endpoint
  [ ] services/hwfit/hardware.py       — Windows + AMD + WSL2 probes added
  [ ] services/hwfit/catalog.py        — 270+ model entries verified
  [ ] services/hwfit/fit.py            — fit_score function with flags
  [ ] scripts/odysseus-cookbook        — updated for Windows subprocess fallback
  [ ] tests/test_hwfit.py              — hardware probe tests (mocked)
```

---

## PART 2 — FOLDER STRUCTURE ANALYSIS

```
odysseus/
├── app.py                        # FastAPI entry — mounts all route blueprints
│
├── core/                         # Shared infrastructure
│   ├── auth.py                   # JWT + session auth; get_current_user dependency
│   ├── database.py               # SQLAlchemy models, session factory
│   ├── middleware.py             # CORS, logging, rate-limit middleware
│   └── constants.py              # App-wide constants (paths, defaults)
│
├── src/                          # Domain logic (not HTTP)
│   ├── llm_core.py               # LLM provider abstraction (calls Ollama/vLLM/OpenAI)
│   ├── agent_loop.py             # Agent task runner
│   ├── agent_tools.py            # Tool definitions (shell, web, files)
│   ├── chat_processor.py         # Pre/post-processing for chat messages
│   └── search/                   # SearXNG + DDG search wrappers
│
├── routes/                       # FastAPI routers (one file per feature area)
│   ├── chat_routes.py            # POST /api/chat, streaming completions
│   ├── model_routes.py           # GET /api/models, model registry CRUD
│   ├── session_routes.py         # Session create/list/delete
│   ├── document_routes.py        # Document editor endpoints
│   ├── memory_routes.py          # ChromaDB vector memory
│   ├── cookbook_routes.py        # ★ Cookbook: download, serve, catalog
│   ├── hwfit_routes.py           # ★ Hardware probe endpoint
│   └── research_routes.py        # Deep Research pipeline
│
├── services/                     # Heavier stateful services
│   ├── hwfit/                    # ★ COOKBOOK ENGINE
│   │   ├── hardware.py           #   GPU/RAM detection (nvidia-smi, rocm-smi, psutil)
│   │   ├── catalog.py            #   270+ model catalog with quant metadata
│   │   ├── fit.py                #   VRAM-aware fit scoring algorithm
│   │   └── serve.py              #   Engine launcher (vLLM / llama.cpp / Ollama)
│   ├── docs/                     # Document extraction (markitdown, PyMuPDF)
│   ├── memory/                   # ChromaDB + fastembed wrapper
│   ├── search/                   # Search provider abstraction
│   └── research/                 # Deep Research (Tongyi adapted)
│
├── static/                       # Entire frontend (no build step — vanilla JS)
│   ├── index.html                # Single-page app shell
│   ├── app.js                    # ★ Main JS: routing, state, module init
│   ├── style.css                 # ★ CSS with theme variables
│   └── js/                       # ★ Modular JS (one file per feature)
│       ├── chat.js               # Chat UI + streaming
│       ├── cookbook.js           # ★ Cookbook UI panels
│       ├── cookbook-serve.js     # ★ Serve control panel
│       ├── agent.js              # Agent task UI
│       ├── document.js           # Document editor
│       ├── memory.js             # Memory/skills UI
│       └── model-switcher.js     # ★ NEW: in-chat model switcher
│
├── scripts/
│   ├── odysseus-cookbook         # ★ Shell script: bg download/serve (Linux/macOS)
│   ├── check-docker-gpu.sh       # NVIDIA GPU Docker passthrough diagnostic
│   └── check-docker-amd-gpu.sh   # AMD GPU Docker passthrough diagnostic
│
├── docker/
│   ├── gpu.nvidia.yml            # NVIDIA overlay
│   └── gpu.amd.yml               # AMD overlay
│
├── config/searxng/               # SearXNG config
├── companion/                    # opencode agent companion
├── integrations/                 # Third-party integration configs
├── mcp_servers/                  # Built-in MCP server definitions
├── tests/                        # pytest suite
├── data/                         # Runtime data (gitignored)
│   ├── app.db                    # SQLite database
│   ├── huggingface/              # Downloaded model files (GGUF etc.)
│   ├── local/                    # Cookbook-installed CLIs (llama.cpp, vLLM)
│   ├── ssh/                      # SSH keypair for remote Cookbook servers
│   └── cookbook_processes.json   # ★ NEW (Windows): active serve PID registry
│
├── launch-windows.ps1            # ★ Windows one-command launcher
├── update_windows.bat            # Windows update helper
├── install-service.sh            # Linux systemd service installer
├── odysseus-ui.service           # systemd unit file
├── start-macos.sh                # macOS native launcher
├── build-macos-app.sh            # macOS .app wrapper builder
├── Dockerfile
├── docker-compose.yml
├── docker-compose.gpu-nvidia.yml
├── docker-compose.gpu-amd.yml
├── app.py
├── setup.py
├── requirements.txt
└── pyproject.toml
```

---

## PART 3 — PLATFORM DIFFERENCES (Windows vs Linux)

### Where they diverge for Model Switching

| Concern | Linux | Windows |
|---|---|---|
| **Model list fetch** | Identical — `/api/models` HTTP route | Identical |
| **Session update** | Identical — SQLite write | Identical |
| **Frontend switcher** | Identical — vanilla JS, no OS dependency | Identical |

Model switching itself is **purely frontend + HTTP**, so there is **no platform difference** there. Both platforms run the same FastAPI server and the same `static/js/model-switcher.js`.

---

### Where they diverge for Cookbook

| Concern | Linux | Windows |
|---|---|---|
| **GPU detection** | `nvidia-smi`, `rocm-smi`, `rocminfo` | `nvidia-smi.exe`, `wmic` for AMD; NO rocm-smi |
| **Background processes** | `tmux` new-window (existing `scripts/odysseus-cookbook`) | `subprocess` + `cmd /c start /b` or `Start-Process` (PowerShell); NO tmux natively |
| **PID tracking** | tmux session name = job ID | `data/cookbook_processes.json` stores PIDs |
| **vLLM serving** | ✅ Full support (CUDA + ROCm builds) | ❌ Not supported natively; WSL2 needed |
| **SGLang serving** | ✅ Full support | ❌ Not supported natively |
| **llama.cpp serving** | ✅ via pip / prebuilt `.so` | ✅ via `llama-cpp-python` wheel (CUDA-enabled on Windows with CUDA Toolkit) |
| **Ollama serving** | ✅ works; extra step for VRAM passthrough in Docker | ✅ first-class Windows support; easiest GPU path |
| **Engine auto-selection logic** | NVIDIA → vLLM preferred; AMD → vLLM/ROCm; CPU → llama.cpp | NVIDIA → llama.cpp CUDA or Ollama; AMD → Ollama only; CPU → llama.cpp or Ollama |
| **Shell script (odysseus-cookbook)** | bash, tmux — works natively | Needs `bash.exe` from Git for Windows; tmux absent; PowerShell fallback path needed |
| **AMD support** | ROCm userspace tools available | No ROCm on Windows → Ollama is the only AMD path |
| **WSL2 detection** | Check `/proc/version` for "Microsoft" | `platform.system() == 'Windows'` + check if running in WSL2 via env |
| **CUDA Toolkit for llama.cpp** | `apt install nvidia-cuda-toolkit` | Must install CUDA Toolkit manually; `nvcc` must be in PATH |
| **Path separators** | `/` everywhere | Use `pathlib.Path` throughout — never hard-code `/` |
| **Port conflicts** | 7000 generally free | AV/firewall may block; launcher uses 7000 (macOS uses 7860 due to AirPlay conflict; Windows has no such constraint) |

### Recommended engine selection logic (Python pseudocode)

```python
import platform, shutil

def select_serve_engine(hardware):
    os_name = platform.system()  # 'Linux', 'Windows', 'Darwin'
    has_nvidia = any(g.backend == 'cuda' for g in hardware.gpus)
    has_amd   = any(g.backend == 'rocm' for g in hardware.gpus)
    has_metal = any(g.backend == 'metal' for g in hardware.gpus)

    if os_name == 'Linux':
        if has_nvidia:
            return 'vllm' if shutil.which('vllm') else 'llama.cpp'
        if has_amd:
            return 'vllm'   # vLLM ROCm build
        return 'llama.cpp'  # CPU

    if os_name == 'Windows':
        if has_amd:
            return 'ollama'  # only sane AMD path on Windows
        # NVIDIA or CPU: prefer Ollama if installed, else llama.cpp
        return 'ollama' if shutil.which('ollama') else 'llama.cpp'

    if os_name == 'Darwin':
        return 'llama.cpp'  # Metal via llama.cpp; vLLM unavailable on macOS
```

### Background process launch — Linux vs Windows

```python
import subprocess, platform, json, os
from pathlib import Path

PROC_REGISTRY = Path('data/cookbook_processes.json')

def launch_serve(cmd_args: list[str], job_id: str):
    if platform.system() == 'Linux':
        # existing: tmux new-window
        subprocess.Popen(['tmux', 'new-window', '-n', job_id,
                          ' '.join(cmd_args)])
    elif platform.system() == 'Windows':
        # No tmux — detach with CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            cmd_args,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.DETACHED_PROCESS,
            stdout=open(f'data/logs/{job_id}.log', 'w'),
            stderr=subprocess.STDOUT,
        )
        # Persist PID so we can stop/restart later
        registry = {}
        if PROC_REGISTRY.exists():
            registry = json.loads(PROC_REGISTRY.read_text())
        registry[job_id] = proc.pid
        PROC_REGISTRY.write_text(json.dumps(registry, indent=2))
    else:
        # macOS — same as Linux (Homebrew tmux)
        subprocess.Popen(['tmux', 'new-window', '-n', job_id,
                          ' '.join(cmd_args)])
```

---

## PART 4 — QUICK REFERENCE: FILES TO TOUCH PER FEATURE

### Feature 1 — Model Switcher UI

| File | Change |
|---|---|
| `static/js/model-switcher.js` | **New file** — ModelSwitcher class |
| `static/style.css` | Add `.model-switcher-*` CSS using existing CSS vars |
| `static/app.js` | Call `ModelSwitcher.init()` on session load |
| `routes/model_routes.py` | Confirm/add `GET /api/models` returns full provider+model list |
| `routes/chat_routes.py` | Confirm model param is read from session, not hardcoded |

### Feature 2 — Cookbook Extensions

| File | Change |
|---|---|
| `services/hwfit/hardware.py` | Add Windows (`wmic`/`nvidia-smi.exe`) + AMD + WSL2 probes |
| `services/hwfit/catalog.py` | Extend to 270+ models with quant + VRAM metadata |
| `services/hwfit/fit.py` | Add `fit_score()` with FITS/TIGHT/CPU_FALLBACK/TOO_LARGE flags |
| `services/hwfit/serve.py` | Platform-aware engine selection + Windows subprocess launch |
| `routes/cookbook_routes.py` | `GET /api/cookbook/hardware`, `GET /api/cookbook/recommendations`, `POST /api/cookbook/serve`, `POST /api/cookbook/serve/{id}/stop` |
| `routes/hwfit_routes.py` | Wire hardware probe into `/api/cookbook/hardware` |
| `routes/model_routes.py` | `POST /api/models/register` for auto-registration after serve |
| `static/js/cookbook.js` | Panel A (recommendations grid), Panel B (manage downloads+serves) |
| `scripts/odysseus-cookbook` | Windows-compatible fallback (detect no-tmux, use subprocess) |
| `data/cookbook_processes.json` | Auto-created at runtime on Windows |
| `tests/test_hwfit.py` | **New file** — mocked hardware probe tests |
