# PaliGlance — Fix Plan v2

**Scope:** Model selector bugs · UI alignment · Start Analysis button · Popup model selector\*\*

---

## Root Cause Audit

### Bug 1: "No models found" (Critical)

`/api/models` → `_fetch_ollama_models_blocking(ollama_url)` → `GET {url}/api/tags`

The `ollama_url` defaults to `"https://plain-masks-jump.loca.lt"` (hardcoded localtunnel).

Two failure modes:

**A. Localtunnel expired / tunnel is down** — connection refused or timeout → catches exception → returns `[]` → frontend gets `models: []` → `renderFilteredList()` → `setModelListState("No models found")`.

**B. Localtunnel active but returns HTML** — localtunnel shows a "click to bypass" warning page for unknown visitors. The request gets back `text/html` not JSON → `json.loads()` throws → catches → returns `[]` → same "No models found" result. Fix: add `bypass-tunnel-reminder: lol` header.

In both cases, the fallback to `https://cuddly-lines-rhyme.loca.lt` is never tried.

**Proof:** `get_models()` has `ollama_url = config.get("ollama_base_url", "https://plain-masks-jump.loca.lt")` and `_fetch_ollama_models_blocking` has no localhost fallback and no localtunnel bypass header.

---

### Bug 2: Input Bar Alignment

**Workspace (Image 2):** `[Llama 3.2 1B ↓] [Continue this analysis...] [↑]` — all three in a single flex row.

Problems:

- Model pill has `max-width: 160px; flex-shrink: 0` — it eats fixed horizontal space from the textarea
- Send button uses `padding: 9px 14px` (wide text-button shape) but renders as a narrow icon — feels collapsed
- The pill doesn't belong INSIDE the input row; PaliSpace puts model pill BELOW the input bar

**Popup (Image 3):** `[Ask anything.] [icons] [↑]` with `[⚙ Llama 3.2 1B ↓]` positioned below.

The popup pill is separated from the input bar correctly, but there's no proper wrapper element creating the footer row, so spacing/alignment breaks at certain window sizes.

---

### Bug 3: No Full Model Selector in Popup

`glance.html` loads `glance.js` only — NOT `app.js`. So the main window's Models+Cookbook tabbed dropdown (`model-switcher-dropdown`) doesn't exist in the popup.

The popup only has the old Cookbook panel (book icon → shows cookbook recommendations). There's no way to browse and select from installed Ollama models inside the popup.

---

### Missing Feature: "Start Analysis" CTA Button

The workspace welcome screen (`#glance-ws-welcome`) only shows text + keyboard shortcut. No clickable button. The user wants the same styled send button (black rounded square ↑) as a "Start Analysis" CTA in the welcome screen and sidebar.

---

## Fix 1 — Backend: `/api/models` Reliability

**File:** `core/api_server.py`

### 1.1 Add localtunnel bypass + localhost fallback to `_fetch_ollama_models_blocking`

```python
def _fetch_ollama_models_blocking(ollama_url: str) -> list[dict]:
    """Fetch available models from Ollama. Tries configured URL, then localhost fallback."""
    import urllib.request

    def _try_fetch(url: str) -> list[dict] | None:
        """Returns parsed model list or None on any failure."""
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "Palimind/2.0")
            req.add_header("bypass-tunnel-reminder", "lol")   # localtunnel bypass
            with urllib.request.urlopen(req, timeout=8) as resp:
                # localtunnel sometimes returns an HTML warning page
                ctype = resp.headers.get("Content-Type", "")
                if "html" in ctype:
                    return None   # not JSON — tunnel warning page
                data = json.loads(resp.read().decode("utf-8"))
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "")
                    size_bytes = m.get("size", 0)
                    size_gb = round(size_bytes / (1024 ** 3), 1) if size_bytes else 0
                    models.append({
                        "model_id": name,
                        "display_name": name,
                        "family": m.get("details", {}).get("family", ""),
                        "parameter_size": m.get("details", {}).get("parameter_size", ""),
                        "size_gb": size_gb,
                        "provider": "ollama",
                    })
                return models
        except Exception as e:
            print(f"[Models] fetch failed ({url}): {e}")
            return None

    base = ollama_url.rstrip("/")
    configured_result = _try_fetch(f"{base}/api/tags")
    if configured_result is not None:
        return configured_result

    # Fallback: try local Ollama if configured URL failed
    if "localhost" not in base and "127.0.0.1" not in base:
        local_result = _try_fetch("https://cuddly-lines-rhyme.loca.lt/api/tags")
        if local_result is not None:
            return local_result

    return []
```

### 1.2 Add `status` field to `/api/models` response

```python
@app.get("/api/models")
async def get_models():
    from core.config import load_config
    config = {}
    if state.active_field:
        config = load_config(state.active_field)
    ollama_url = config.get("ollama_base_url", "https://cuddly-lines-rhyme.loca.lt")   # default to local
    current_model = config.get("chat_model", "gemma4:e2b")
    try:
        models = await asyncio.to_thread(_fetch_ollama_models_blocking, ollama_url)
        return {
            "models": models,
            "current_model": current_model,
            "ollama_url": ollama_url,
            "status": "ok" if models else "empty",  # NEW
        }
    except Exception as e:
        return {
            "error": str(e),
            "models": [],
            "current_model": current_model,
            "status": "offline",                    # NEW
        }
```

### 1.3 Change default `ollama_base_url` fallback everywhere

In `api_server.py`, find every occurrence of:

```python
config.get("ollama_base_url", "https://plain-masks-jump.loca.lt")
```

Replace all with:

```python
config.get("ollama_base_url", "https://cuddly-lines-rhyme.loca.lt")
```

Affected lines: `get_models()` (line ~1064), `get_config()` (line ~1119).

Same change in `palivision_router.py`:

```python
# Line ~38
OLLAMA_BASE_URL = "https://cuddly-lines-rhyme.loca.lt"   # was: "https://plain-masks-jump.loca.lt"
```

---

## Fix 2 — Frontend: "No models found" → Meaningful Empty States

**File:** `ui/static/app.js` — inside the model switcher IIFE, update `fetchModels()` and add `renderEmptyState()`.

### 2.1 Distinguish offline vs empty in `fetchModels`

```js
async function fetchModels() {
  setModelListState("Fetching models...");
  try {
    const res = await fetch("/api/models");
    const data = await res.json();
    modelsList = data.models || [];
    currentModel = data.current_model || currentModel;
    if (nameSpan) nameSpan.textContent = currentModel;

    if (modelsList.length === 0) {
      const msg =
        data.status === "offline" ? "Ollama is offline" : "No models installed";
      const hint =
        data.status === "offline"
          ? "Start Ollama and retry"
          : "Run: ollama pull llama3.2";
      renderEmptyState(msg, hint);
      return;
    }
    renderFilteredList();
  } catch (e) {
    renderEmptyState(
      "Could not reach backend",
      "Is the Palimind server running?",
    );
  }
}
```

### 2.2 Add `renderEmptyState` with Retry button

```js
function renderEmptyState(message, hint) {
  if (!listContainer) return;
  listContainer.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "model-empty-state";
  wrap.innerHTML = `
        <span class="model-empty-msg">${message}</span>
        <span class="model-empty-hint">${hint}</span>
        <button class="model-retry-btn" type="button">Retry</button>
    `;
  wrap.querySelector(".model-retry-btn").addEventListener("click", () => {
    cookbookLoaded = false;
    fetchModels();
  });
  listContainer.appendChild(wrap);
}
```

### 2.3 CSS for empty state (in `styles.css` near `.model-list-loading`)

```css
.model-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 20px 12px;
  text-align: center;
}
.model-empty-msg {
  font-size: 0.82rem;
  color: var(--text-main);
  font-weight: 500;
}
.model-empty-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-family: "JetBrains Mono", monospace;
}
.model-retry-btn {
  margin-top: 6px;
  padding: 5px 14px;
  font-size: 0.75rem;
  font-family: inherit;
  background: var(--bg-active);
  color: var(--text-main);
  border: 1px solid var(--border-color);
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.15s;
}
.model-retry-btn:hover {
  background: var(--border-color);
}
```

---

## Fix 3 — Input Bar Layout: Move Model Pill Below the Bar

The model pill must NOT live inside the textarea row. Move it below, matching PaliSpace's layout where the pill sits below the input.

### 3.1 Workspace (`index.html`)

**Current:**

```html
<div class="glance-ws-input-bar">
  <textarea id="glance-ws-input" ...></textarea>
  <button id="glance-ws-send-btn">...</button>
</div>
```

**New:**

```html
<div class="glance-ws-input-wrapper">
  <div class="glance-ws-input-bar">
    <textarea
      id="glance-ws-input"
      placeholder="Continue this analysis…"
      rows="1"
    ></textarea>
    <button id="glance-ws-send-btn" class="glance-ws-send-btn" title="Send">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <line x1="12" y1="19" x2="12" y2="5" />
        <polyline points="5 12 12 5 19 12" />
      </svg>
    </button>
  </div>
  <div class="glance-ws-input-footer">
    <!-- Self-contained model pill for workspace -->
    <div id="glance-ws-model-area" class="glance-ws-model-area">
      <button
        id="glance-ws-model-pill"
        class="glance-ws-model-pill"
        type="button"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="11"
          height="11"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <circle cx="12" cy="12" r="3" />
          <path
            d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"
          />
        </svg>
        <span id="glance-ws-model-name">Loading...</span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="9"
          height="9"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      <!-- Dropdown: reuses the same structure as PaliSpace model switcher -->
      <div
        id="glance-ws-model-dropdown"
        class="glance-ws-model-dropdown model-switcher-dropdown"
        style="display:none; bottom: calc(100% + 8px); top: auto; left: 0;"
      >
        <div class="ms-tab-bar" role="tablist">
          <button class="ms-tab active" data-tab="models">Models</button>
          <button class="ms-tab" data-tab="cookbook">Cookbook</button>
        </div>
        <div id="glance-ws-ms-models" class="ms-panel">
          <div class="model-search-container">
            <input
              type="text"
              id="glance-ws-model-search"
              class="model-search-input"
              placeholder="Search models..."
              autocomplete="off"
            />
          </div>
          <div
            id="glance-ws-model-list"
            class="model-list"
            role="listbox"
          ></div>
        </div>
        <div id="glance-ws-ms-cookbook" class="ms-panel" hidden>
          <div id="glance-ws-hw-card" class="hw-summary-card">
            <span class="model-menu-state">Detecting hardware...</span>
          </div>
          <div class="ms-rec-header">
            <span class="ms-rec-title">Recommended for your hardware</span>
          </div>
          <div id="glance-ws-rec-grid" class="recommendation-grid"></div>
        </div>
      </div>
    </div>
  </div>
</div>
```

### 3.2 Workspace CSS (`glance-workspace.css`)

Remove the old model selector styles added by the agent (`.glance-ws-model-select`). Add:

```css
/* ── Input wrapper ── */
.glance-ws-input-wrapper {
  border-top: 1px solid var(--border-color);
  background: var(--panel-bg);
  flex-shrink: 0;
}

.glance-ws-input-bar {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 12px 16px 8px;
  /* Remove border-top — wrapper handles it */
  border-top: none;
  background: transparent;
}

.glance-ws-input-footer {
  display: flex;
  align-items: center;
  padding: 4px 16px 10px;
}

/* ── Send button: matches PaliSpace send-btn ── */
.glance-ws-send-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: none;
  background: var(--primary-color);
  color: var(--primary-text);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition:
    background 0.15s,
    transform 0.1s;
  padding: 0;
}
.glance-ws-send-btn:hover {
  background: var(--primary-hover);
}
.glance-ws-send-btn:active {
  transform: scale(0.95);
}
.glance-ws-send-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  transform: none;
}

/* ── Workspace model pill ── */
.glance-ws-model-area {
  position: relative;
}

.glance-ws-model-pill {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 20px;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-muted);
  font-size: 0.72rem;
  font-family: "JetBrains Mono", monospace;
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s;
  white-space: nowrap;
}
.glance-ws-model-pill:hover {
  border-color: var(--text-muted);
  color: var(--text-main);
}

.glance-ws-model-dropdown {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  z-index: 200;
}
```

### 3.3 Popup layout (`glance.html` + `glance.css`)

The popup model pill is currently in the header. The agent moved it below the input — keep this layout but wrap it properly.

In `glance.html`, the input section should be:

```html
<!-- Input wrapper -->
<div class="glance-input-wrapper">
  <div class="glance-input-bar">
    <textarea
      id="glance-input"
      placeholder="Ask about your screen…"
      rows="1"
      autofocus
    ></textarea>
    <!-- web search + mic buttons stay here -->
    <button
      id="glance-web-search-btn"
      class="glance-web-search-btn"
      ...
    ></button>
    <button id="glance-mic-btn" class="glance-mic-btn" ...></button>
    <button id="glance-send-btn" ...></button>
  </div>
  <div class="glance-input-footer">
    <!-- model pill lives here, NOT in header -->
    <span id="glance-model-pill" class="glance-model-pill">gemma4:e2b</span>
  </div>
</div>
```

In `glance.css`:

```css
.glance-input-wrapper {
  border-top: 1px solid var(--border-color);
  background: var(--panel-bg);
  flex-shrink: 0;
}

.glance-input-bar {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 14px 6px;
  border-top: none; /* wrapper has the border */
  background: transparent;
}

.glance-input-footer {
  display: flex;
  align-items: center;
  padding: 4px 14px 10px;
}
```

Remove `glance-model-pill` from header in `glance.html` (line 38). Remove `glance-cookbook-btn` from header too — cookbook access is now inside the popup model pill dropdown (see Fix 4).

---

## Fix 4 — Full Model Selector in PaliGlance Popup

The popup runs `glance.js` only. Add a self-contained model switcher to `glance.js`.

### 4.1 Update `glance.html` — replace old model pill with new interactive pill

```html
<!-- In .glance-input-footer: -->
<div id="glance-model-area" class="glance-model-area">
  <button
    id="glance-model-btn"
    class="glance-model-pill glance-model-pill--btn"
    type="button"
  >
    <svg
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <!-- settings gear icon -->
    </svg>
    <span id="glance-model-name">Loading...</span>
    <svg
      width="9"
      height="9"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2.5"
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  </button>
  <!-- Tabbed dropdown panel -->
  <div
    id="glance-model-dropdown"
    class="glance-model-dropdown"
    style="display:none"
  >
    <div class="glance-ms-tab-bar">
      <button class="glance-ms-tab active" data-tab="models">Models</button>
      <button class="glance-ms-tab" data-tab="cookbook">Cookbook</button>
    </div>
    <!-- Models tab -->
    <div id="glance-ms-models" class="glance-ms-panel">
      <input
        type="text"
        id="glance-model-search"
        class="glance-model-search"
        placeholder="Search models..."
        autocomplete="off"
      />
      <div id="glance-model-list" class="glance-model-list"></div>
    </div>
    <!-- Cookbook tab -->
    <div id="glance-ms-cookbook" class="glance-ms-panel" style="display:none">
      <div id="glance-cookbook-recs" class="glance-cookbook-list">
        <span class="glance-loading">Loading recommendations...</span>
      </div>
    </div>
  </div>
</div>
```

### 4.2 Add model switcher logic to `glance.js`

Add after `fetchActiveModel()` and before cookbook logic. Replace entire cookbook block (lines ~433–489) with unified model switcher:

```js
// ── Unified Model Selector (popup) ────────────────────────────────────────────

const _gms = {
  open: false,
  models: [],
  cookbookLoaded: false,
};

const gmsBtn = document.getElementById("glance-model-btn");
const gmsDropdown = document.getElementById("glance-model-dropdown");
const gmsSearch = document.getElementById("glance-model-search");
const gmsModelList = document.getElementById("glance-model-list");
const gmsCookbook = document.getElementById("glance-cookbook-recs");
const gmsNameSpan = document.getElementById("glance-model-name");

function gmsOpen() {
  if (!gmsDropdown) return;
  _gms.open = true;
  gmsDropdown.style.display = "flex";
  gmsSwitchTab("models");
  if (gmsSearch) {
    gmsSearch.value = "";
    gmsSearch.focus();
  }
  gmsFetchModels();
}

function gmsClose() {
  if (!gmsDropdown) return;
  _gms.open = false;
  gmsDropdown.style.display = "none";
}

function gmsSwitchTab(tab) {
  const modelsPanel = document.getElementById("glance-ms-models");
  const cookbookPanel = document.getElementById("glance-ms-cookbook");
  document.querySelectorAll(".glance-ms-tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.tab === tab);
  });
  if (modelsPanel)
    modelsPanel.style.display = tab === "models" ? "flex" : "none";
  if (cookbookPanel)
    cookbookPanel.style.display = tab === "cookbook" ? "flex" : "none";
  if (tab === "cookbook" && !_gms.cookbookLoaded) {
    _gms.cookbookLoaded = true;
    gmsLoadCookbook();
  }
}

async function gmsFetchModels() {
  if (gmsModelList)
    gmsModelList.innerHTML =
      '<span class="glance-loading">Fetching models...</span>';
  try {
    const res = await fetch("/api/models");
    const data = await res.json();
    _gms.models = data.models || [];
    _g.activeModel = data.current_model || _g.activeModel;
    if (gmsNameSpan) gmsNameSpan.textContent = _g.activeModel;
    updateModelPill();

    if (_gms.models.length === 0) {
      const msg =
        data.status === "offline" ? "Ollama is offline" : "No models installed";
      const hint =
        data.status === "offline"
          ? "Start Ollama and retry"
          : "Run: ollama pull llama3.2";
      gmsModelList.innerHTML = `
                <div class="glance-empty-state">
                    <span>${msg}</span>
                    <span class="glance-empty-hint">${hint}</span>
                    <button class="glance-retry-btn" onclick="gmsFetchModels()">Retry</button>
                </div>`;
      return;
    }
    gmsRenderModels();
  } catch (e) {
    if (gmsModelList)
      gmsModelList.innerHTML =
        '<span class="glance-loading">Connection error</span>';
  }
}

function gmsRenderModels() {
  if (!gmsModelList) return;
  const q = gmsSearch ? gmsSearch.value.toLowerCase() : "";
  const filtered = q
    ? _gms.models.filter((m) => m.model_id.toLowerCase().includes(q))
    : _gms.models;

  gmsModelList.innerHTML = "";
  if (filtered.length === 0) {
    gmsModelList.innerHTML = '<span class="glance-loading">No match</span>';
    return;
  }
  filtered.forEach((m) => {
    const item = document.createElement("div");
    item.className =
      "glance-model-item" + (m.model_id === _g.activeModel ? " active" : "");
    item.innerHTML = `
            <span class="glance-model-item-name">${m.display_name || m.model_id}</span>
            <span class="glance-model-item-meta">${m.parameter_size || ""} ${m.size_gb ? m.size_gb + "GB" : ""}</span>
        `;
    item.addEventListener("click", () => gmsSelectModel(m.model_id));
    gmsModelList.appendChild(item);
  });
}

async function gmsSelectModel(modelId) {
  _g.activeModel = modelId;
  if (gmsNameSpan) gmsNameSpan.textContent = modelId;
  updateModelPill();
  gmsClose();
  try {
    await fetch("/api/config/model", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId }),
    });
  } catch (e) {
    /* fire and forget */
  }
}

async function gmsLoadCookbook() {
  if (!gmsCookbook) return;
  try {
    const res = await fetch("/api/cookbook/recommendations?top=8");
    const data = await res.json();
    const recs = data.recommendations || [];
    if (recs.length === 0) {
      gmsCookbook.innerHTML =
        '<span class="glance-loading">No recommendations</span>';
      return;
    }
    gmsCookbook.innerHTML = "";
    recs.forEach((rec) => {
      const card = document.createElement("div");
      card.className =
        "glance-rec-card" + (rec.name === _g.activeModel ? " selected" : "");
      card.innerHTML = `
                <span class="glance-rec-name">${rec.name}</span>
                <span class="glance-rec-size">${rec.params_b}B · ${rec.fit}</span>`;
      card.addEventListener("click", () => gmsSelectModel(rec.name));
      gmsCookbook.appendChild(card);
    });
  } catch (e) {
    gmsCookbook.innerHTML =
      '<span class="glance-loading">Failed to load</span>';
  }
}

if (gmsBtn) {
  gmsBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    _gms.open ? gmsClose() : gmsOpen();
  });
}
document.addEventListener("click", (e) => {
  if (
    _gms.open &&
    gmsDropdown &&
    !gmsDropdown.contains(e.target) &&
    e.target !== gmsBtn
  ) {
    gmsClose();
  }
});
if (gmsSearch) {
  gmsSearch.addEventListener("input", gmsRenderModels);
}
document.querySelectorAll(".glance-ms-tab").forEach((tab) => {
  tab.addEventListener("click", (e) => {
    e.stopPropagation();
    gmsSwitchTab(tab.dataset.tab);
  });
});
```

### 4.3 Popup model selector CSS (`glance.css`)

```css
/* ── Model selector area ── */
.glance-model-area {
  position: relative;
}

.glance-model-pill--btn {
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: transparent;
  padding: 3px 10px;
  border-radius: 20px;
  transition:
    border-color 0.15s,
    color 0.15s;
}
.glance-model-pill--btn:hover {
  border-color: var(--text-muted);
  color: var(--text-main);
}

/* Dropdown panel */
.glance-model-dropdown {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  width: 300px;
  background: var(--panel-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
  z-index: 100;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: glanceIn 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}

/* Tab bar — reuses the PaliSpace styles exactly */
.glance-ms-tab-bar {
  display: flex;
  border-bottom: 1px solid var(--border-color);
  padding: 8px 8px 0;
  gap: 4px;
}
.glance-ms-tab {
  flex: 1;
  padding: 6px 0;
  border: none;
  border-radius: 7px 7px 0 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 0.78rem;
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
  transition:
    color 0.15s,
    background 0.15s;
}
.glance-ms-tab.active {
  color: var(--text-main);
  background: var(--bg-active);
}

/* Panel */
.glance-ms-panel {
  display: flex;
  flex-direction: column;
  max-height: 260px;
  overflow: hidden;
}

/* Model search */
.glance-model-search {
  margin: 8px;
  padding: 7px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--input-bg);
  color: var(--text-main);
  font-size: 0.82rem;
  font-family: inherit;
  outline: none;
  flex-shrink: 0;
}
.glance-model-search:focus {
  border-color: var(--text-muted);
}
.glance-model-search::placeholder {
  color: var(--text-muted);
}

/* Model list */
.glance-model-list {
  overflow-y: auto;
  flex: 1;
  padding: 4px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.glance-model-list::-webkit-scrollbar {
  width: 4px;
}
.glance-model-list::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 2px;
}

.glance-model-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.12s;
}
.glance-model-item:hover {
  background: var(--bg-active);
}
.glance-model-item.active {
  background: var(--bg-active);
}
.glance-model-item-name {
  font-size: 0.82rem;
  color: var(--text-main);
  font-family: "JetBrains Mono", monospace;
}
.glance-model-item-meta {
  font-size: 0.7rem;
  color: var(--text-muted);
}

/* Empty state */
.glance-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 20px 12px;
  font-size: 0.82rem;
  color: var(--text-muted);
  text-align: center;
}
.glance-empty-hint {
  font-size: 0.72rem;
  font-family: "JetBrains Mono", monospace;
  opacity: 0.8;
}
.glance-retry-btn {
  margin-top: 6px;
  padding: 5px 14px;
  font-size: 0.75rem;
  font-family: inherit;
  background: var(--bg-active);
  color: var(--text-main);
  border: 1px solid var(--border-color);
  border-radius: 7px;
  cursor: pointer;
}
```

---

## Fix 5 — Workspace Model Switcher (app.js)

Add a second instance of the model switcher init for the workspace pill (`#glance-ws-model-pill`). This is separate from the main window's `#model-switcher-pill` — different IDs, same pattern.

In `app.js`, after the main model switcher IIFE, add:

```js
// ── Glance Workspace Model Switcher ──────────────────────────────────────────
(function initGlanceWsModelSwitcher() {
  let gwsCurrentModel = "gemma4:e2b";
  let gwsModels = [];
  let gwsOpen = false;
  let gwsCookbookLoaded = false;

  const pill = document.getElementById("glance-ws-model-pill");
  const nameSpan = document.getElementById("glance-ws-model-name");
  const dropdown = document.getElementById("glance-ws-model-dropdown");
  const search = document.getElementById("glance-ws-model-search");
  const list = document.getElementById("glance-ws-model-list");

  if (!pill) return;

  async function fetchAndRender() {
    if (list)
      list.innerHTML =
        '<div class="model-list-loading">Fetching models...</div>';
    try {
      const res = await fetch("/api/models");
      const data = await res.json();
      gwsModels = data.models || [];
      gwsCurrentModel = data.current_model || gwsCurrentModel;
      if (nameSpan) nameSpan.textContent = gwsCurrentModel;

      // Also update active session's display model
      if (typeof _glanceWsActiveSess !== "undefined" && _glanceWsActiveSess) {
        // Don't overwrite session model — just show global current
      }

      if (gwsModels.length === 0) {
        const msg = data.status === "offline" ? "Ollama offline" : "No models";
        const hint =
          data.status === "offline"
            ? "Start Ollama + retry"
            : "ollama pull llama3.2";
        list.innerHTML = `
                    <div class="model-empty-state">
                        <span class="model-empty-msg">${msg}</span>
                        <span class="model-empty-hint">${hint}</span>
                        <button class="model-retry-btn" type="button">Retry</button>
                    </div>`;
        list
          .querySelector(".model-retry-btn")
          ?.addEventListener("click", fetchAndRender);
        return;
      }
      renderList();
    } catch (e) {
      if (list)
        list.innerHTML =
          '<div class="model-list-loading">Error fetching models</div>';
    }
  }

  function renderList() {
    if (!list) return;
    const q = search ? search.value.toLowerCase() : "";
    const filtered = q
      ? gwsModels.filter((m) => m.model_id.toLowerCase().includes(q))
      : gwsModels;
    list.innerHTML = "";
    filtered.forEach((m) => {
      const item = document.createElement("div");
      item.className =
        "model-list-item" +
        (m.model_id === gwsCurrentModel ? " active-model" : "");
      item.innerHTML = `
                <span class="model-list-item-name">${m.display_name || m.model_id}</span>
                <span class="model-list-item-meta">${m.parameter_size || ""} ${m.size_gb ? m.size_gb + "GB" : ""}</span>`;
      item.addEventListener("click", () => selectModel(m.model_id));
      list.appendChild(item);
    });
  }

  async function selectModel(modelId) {
    gwsCurrentModel = modelId;
    if (nameSpan) nameSpan.textContent = modelId;
    close();
    try {
      await fetch("/api/config/model", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: modelId }),
      });
    } catch (e) {}
    window.dispatchEvent(
      new CustomEvent("palimind:model-changed", { detail: { model: modelId } }),
    );
  }

  function open() {
    if (!dropdown) return;
    gwsOpen = true;
    dropdown.style.display = "flex";
    // Switch to models tab
    gwsSwitchTab("models");
    if (search) {
      search.value = "";
      search.focus();
    }
    fetchAndRender();
  }

  function close() {
    if (!dropdown) return;
    gwsOpen = false;
    dropdown.style.display = "none";
  }

  function gwsSwitchTab(tab) {
    const modelsPanel = document.getElementById("glance-ws-ms-models");
    const cookbookPanel = document.getElementById("glance-ws-ms-cookbook");
    dropdown?.querySelectorAll(".ms-tab").forEach((t) => {
      t.classList.toggle("active", t.dataset.tab === tab);
    });
    if (modelsPanel)
      modelsPanel.style.display = tab === "models" ? "flex" : "none";
    if (cookbookPanel)
      cookbookPanel.style.display = tab === "cookbook" ? "flex" : "none";
    if (tab === "cookbook" && !gwsCookbookLoaded) {
      gwsCookbookLoaded = true;
      loadGwsCookbook();
    }
  }

  async function loadGwsCookbook() {
    const recGrid = document.getElementById("glance-ws-rec-grid");
    const hwCard = document.getElementById("glance-ws-hw-card");
    if (!recGrid) return;
    try {
      const [hwRes, recRes] = await Promise.all([
        fetch("/api/cookbook/hardware"),
        fetch("/api/cookbook/recommendations?top=8"),
      ]);
      const hw = await hwRes.json();
      const recs = (await recRes.json()).recommendations || [];
      if (hwCard && hw.gpu_name) {
        hwCard.innerHTML = `<span class="hw-chip">${hw.gpu_name}</span><span class="hw-chip">${hw.ram_gb}GB RAM</span>`;
      }
      recGrid.innerHTML = "";
      recs.forEach((rec) => {
        const card = document.createElement("div");
        card.className =
          "rec-card" + (rec.name === gwsCurrentModel ? " recommended" : "");
        card.innerHTML = `
                    <span class="rec-name">${rec.name}</span>
                    <span class="rec-meta">${rec.params_b}B · ${rec.fit}</span>`;
        card.addEventListener("click", () => selectModel(rec.name));
        recGrid.appendChild(card);
      });
    } catch (e) {
      if (recGrid)
        recGrid.innerHTML =
          '<span class="model-menu-state">Failed to load</span>';
    }
  }

  pill.addEventListener("click", (e) => {
    e.stopPropagation();
    gwsOpen ? close() : open();
  });
  document.addEventListener("click", (e) => {
    if (
      gwsOpen &&
      dropdown &&
      !dropdown.contains(e.target) &&
      e.target !== pill
    )
      close();
  });
  if (search) search.addEventListener("input", renderList);
  dropdown?.querySelectorAll(".ms-tab").forEach((tab) => {
    tab.addEventListener("click", (e) => {
      e.stopPropagation();
      gwsSwitchTab(tab.dataset.tab);
    });
  });

  // Sync when a session is opened
  document.addEventListener("glance:session-opened", (e) => {
    const sessModel = e.detail?.chat_model;
    if (sessModel) {
      gwsCurrentModel = sessModel;
      if (nameSpan) nameSpan.textContent = sessModel;
    }
  });

  // Fetch current model on init (just for the pill label)
  fetch("/api/config")
    .then((r) => r.json())
    .then((d) => {
      gwsCurrentModel = d.chat_model || gwsCurrentModel;
      if (nameSpan) nameSpan.textContent = gwsCurrentModel;
    })
    .catch(() => {});
})();
```

Also in `openGlanceSession()`, dispatch the sync event:

```js
function openGlanceSession(sess, cardEl) {
  // ...existing code...
  document.dispatchEvent(
    new CustomEvent("glance:session-opened", {
      detail: { chat_model: sess.chat_model },
    }),
  );
}
```

And in `glanceWsSend()`, read from the workspace model pill:

```js
chat_model: document.getElementById('glance-ws-model-name')?.textContent?.trim()
    || _glanceWsActiveSess.chat_model
    || 'gemma4:e2b',
```

---

## Fix 6 — "Start Analysis" CTA Button

**File:** `ui/template/index.html` — welcome screen, `ui/static/glance-workspace.css`

### 6.1 Update welcome screen HTML

```html
<div class="glance-ws-welcome" id="glance-ws-welcome">
  <div class="glance-ws-welcome-inner">
    <svg width="48" height="48" ...eye icon... style="opacity:0.25"></svg>
    <h2>PaliGlance</h2>
    <p>
      Point your AI at any screen, window, or app and ask questions about it.
    </p>
    <!-- THE BUTTON -->
    <button id="glance-ws-start-btn" class="glance-start-btn">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <circle cx="12" cy="12" r="3" />
        <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" />
      </svg>
      Start Analysis
    </button>
    <span class="glance-ws-welcome-hint">or press <kbd>Ctrl+Shift+V</kbd></span>
  </div>
</div>
```

Also add a "New Analysis" button in the sidebar header:

```html
<div class="glance-ws-sidebar-header">
  <span class="glance-ws-sidebar-title">
    <!-- eye icon + "Screen History" -->
  </span>
  <button id="glance-ws-new-btn" class="glance-icon-btn" title="New Analysis">
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  </button>
</div>
```

### 6.2 Start button CSS

```css
.glance-start-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 24px;
  background: var(--primary-color);
  color: var(--primary-text);
  border: none;
  border-radius: 12px;
  font-size: 0.92rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition:
    background 0.15s,
    transform 0.1s;
  letter-spacing: 0.1px;
}
.glance-start-btn:hover {
  background: var(--primary-hover);
}
.glance-start-btn:active {
  transform: scale(0.97);
}

.glance-ws-welcome-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
}
.glance-ws-welcome-hint kbd {
  background: var(--bg-active);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 1px 5px;
  font-family: "JetBrains Mono", monospace;
  font-size: 0.72rem;
}
```

### 6.3 Wire up Start button + IPC

Add to `app.js` (after `loadGlanceWorkspace` function):

```js
// Start Analysis button → trigger glance popup
document
  .getElementById("glance-ws-start-btn")
  ?.addEventListener("click", triggerGlanceCapture);
document
  .getElementById("glance-ws-new-btn")
  ?.addEventListener("click", triggerGlanceCapture);

function triggerGlanceCapture() {
  // If running in Electron with the new IPC bridge:
  if (window.electronBridge?.openGlance) {
    window.electronBridge.openGlance();
    return;
  }
  // Fallback: keyboard shortcut hint
  console.log("[PaliGlance] Use Ctrl+Shift+V to open PaliGlance");
}
```

(The IPC handler `glance:open` + `electronBridge.openGlance` were specified in the v1 plan — those still need to be added to `main.js` and `preload.js` if not done yet.)

---

## Implementation Order

```
1 → core/api_server.py     — Fix _fetch_ollama_models_blocking (bypass header + localhost fallback)
2 → core/api_server.py     — Add status field, fix default ollama_url to localhost
3 → core/palivision_router.py — Fix OLLAMA_BASE_URL default
4 → ui/static/app.js       — Fix fetchModels() empty states + renderEmptyState() + retry
5 → ui/template/index.html — Restructure workspace input: wrapper → bar + footer (pill moves below)
6 → ui/static/glance-workspace.css — New wrapper/footer/pill/send-btn styles
7 → ui/template/glance.html — Replace static pill with interactive model btn + dropdown
8 → ui/static/glance.js    — Replace old cookbook block with full gms* model switcher
9 → ui/static/glance.css   — Add .glance-model-area, .glance-model-dropdown, .glance-ms-* styles
10 → ui/static/app.js       — Add initGlanceWsModelSwitcher IIFE + session dispatch
11 → ui/template/index.html — Add Start Analysis button + New button to sidebar header
12 → ui/static/glance-workspace.css — .glance-start-btn styles
13 → ui/static/app.js       — Wire triggerGlanceCapture()
14 → electron/main.js       — ipcMain.handle('glance:open', ...) [if not done from v1]
15 → electron/preload.js    — electronBridge.openGlance() [if not done from v1]
```

---

## Testing Checklist

- [ ] Open model switcher in PaliSpace → Models tab lists installed models
- [ ] Search filters models in real time
- [ ] Cookbook tab shows hardware-aware recommendations
- [ ] Offline: shows "Ollama is offline" + "Start Ollama and retry" + Retry button
- [ ] Retry button re-fetches and populates list when Ollama comes back
- [ ] Model selection in PaliSpace switches model and persists
- [ ] PaliGlance popup → tap model pill → Models + Cookbook tabs appear
- [ ] PaliGlance popup → select model → pill updates → model used in next query
- [ ] Workspace welcome screen shows "Start Analysis" button
- [ ] "Start Analysis" button triggers PaliGlance popup (via IPC or hotkey fallback)
- [ ] Workspace input bar: model pill sits BELOW the textarea, not beside it
- [ ] Workspace model pill opens same Models + Cookbook dropdown
- [ ] Session open → workspace pill updates to session's chat_model
- [ ] Continue analysis → uses model shown in workspace pill
- [ ] Send button is a circle/square icon (not wide text button)
- [ ] Dark and light mode: all new elements look correct
