# Odysseus Features → Palimind Implementation Plan

## Architecture Mapping

| Odysseus | Palimind |
|----------|----------|
| `app.py` + `routes/` | `core/api_server.py` (monolithic) |
| `static/app.js` + `static/js/` | `ui/static/app.js` (single file) |
| `static/style.css` | `ui/static/styles.css` |
| `static/index.html` | `ui/template/index.html` |
| `core/database.py` (SQLAlchemy) | `core/config.py` (JSON config) |
| `services/hwfit/` | **NEW**: `core/hwfit/` |
| Auth via `get_current_user` | No auth (local-only) |

---

## Feature 1 — In-Chat Model Switcher UI

### Backend (api_server.py — additive endpoints)
1. `GET /api/models` — Fetch available models from the Ollama API (`ollama_base_url/api/tags`)
2. `PATCH /api/config/model` — Update `chat_model` in active field config + global config
3. `GET /api/config` — Return current config (model, url, etc.)

### Frontend
1. **Model pill badge** below the chat input showing current model name
2. **Dropdown/popover** on click with:
   - Search/filter input
   - List of available Ollama models
   - Currently active model highlighted
3. **Instant switch** — updates config via PATCH, updates badge text
4. **Loading spinner** while fetching models, toast on error

### Files to modify
- `core/api_server.py` — Add 3 new endpoints
- `ui/template/index.html` — Add model switcher DOM element
- `ui/static/app.js` — Add ModelSwitcher logic
- `ui/static/styles.css` — Add model-switcher CSS

---

## Feature 2 — Cookbook (Hardware-Aware, 270+ Models, One-Click Serve)

### 2A. Hardware Detection (`core/hwfit/hardware.py`)
- NVIDIA: `nvidia-smi.exe` on Windows
- AMD: `wmic path win32_VideoController` on Windows
- CPU RAM: `psutil.virtual_memory()`
- Expose via `GET /api/cookbook/hardware`

### 2B. Model Catalog (`core/hwfit/catalog.py`)
- 270+ model entries with quant metadata (VRAM, quality, file sizes)
- Families: Llama 3.x, Qwen 2.5, Mistral, Phi, Gemma, DeepSeek, etc.

### 2C. Fit Scoring (`core/hwfit/fit.py`)
- VRAM fit, quality, speed scoring
- Flags: FITS_PERFECTLY, FITS_TIGHT, CPU_FALLBACK, TOO_LARGE
- Expose via `GET /api/cookbook/recommendations?top=20`

### 2D. One-Click Download & Serve (`core/hwfit/serve.py`)
- Download via `ollama pull` command
- Serve via Ollama (primary for Windows)
- Platform-aware engine selection
- `POST /api/cookbook/serve`, `POST /api/cookbook/serve/{model_id}/stop`

### 2E. Frontend (Cookbook page/panel)
- Panel A: Hardware summary + recommended models grid
- Panel B: Manage downloaded models, serve/stop
- Integrated with Model Switcher

### Files to create
- `core/hwfit/__init__.py`
- `core/hwfit/hardware.py`
- `core/hwfit/catalog.py`
- `core/hwfit/fit.py`
- `core/hwfit/serve.py`

### Files to modify
- `core/api_server.py` — Add cookbook endpoints
- `ui/template/index.html` — Add cookbook UI section
- `ui/static/app.js` — Add cookbook panel logic
- `ui/static/styles.css` — Add cookbook CSS

---

> [!IMPORTANT]
> All existing RAG logic, querying, indexing, and model configuration remain **completely untouched**.
> These features are **purely additive**.
