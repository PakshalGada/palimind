# PaliVision → PaliMind Integration: Dumb Agent Execution Plan
## Grounded in the Actual Codebase — Branch `palivision`

> **Agent Assumption Level:** Zero. Read every file path before touching it.
> This plan is written against what actually exists — not what the spec imagined.
> Every file name, route, function name, and variable is real.

---

## WHAT THIS PROJECT ACTUALLY IS

This is NOT React. This is NOT a Next.js app. Read carefully:

| Layer | Reality |
|---|---|
| **Desktop shell** | Electron (`electron/main.js`) — Node.js, no framework |
| **Backend** | Python 3.10 + FastAPI (`core/api_server.py`) + Uvicorn |
| **Frontend** | **Vanilla JS + HTML + CSS** served as static files via FastAPI |
| **AI inference** | Ollama (local), EasyOCR, vision service |
| **Storage** | SQLite FTS5 + JSON files in `~/.palimind/` and `{field}/.palimind/` |
| **"Components"** | HTML blocks in templates + JS IIFEs — no imports, no bundler |

There is no React. There are no TypeScript imports. There are no npm components to install.
"Reusing a component" means copying/extracting HTML + CSS + JS functions.

---

## TWO WINDOWS — THIS IS THE CENTRAL ARCHITECTURAL FACT

```
┌─────────────────────────────────────────┐
│  BrowserWindow #1 — Main (1280×800)     │
│  Loads: http://localhost:8000/ui        │
│  Files: ui/template/index.html          │
│         ui/static/app.js               │
│         ui/static/styles.css           │
│  JS context: window.electronBridge      │
│  Theme: localStorage["theme"] +         │
│          .light-mode on <html>          │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  BrowserWindow #2 — PaliGlance (580×420)│
│  Loads: http://localhost:8000/ui/glance │
│  Files: ui/template/glance.html         │
│         ui/static/glance.js            │
│         ui/static/glance.css           │
│  JS context: window.glanceAPI           │
│  Theme: ??? (BROKEN — see Phase 1)      │
└─────────────────────────────────────────┘
```

These two windows have **completely separate JavaScript contexts**.
A `localStorage.setItem("theme", "light")` in Window #1 **does not** update Window #2
unless Window #2 reads its own `localStorage` or receives an IPC message.
A CSS class added to `document.documentElement` in Window #1 **does not** affect Window #2.

All IPC bridges are defined in `electron/preload.js`.

---

## CURRENT STATUS AUDIT

### What PaliGlance (`glance.js` + `glance.html` + `glance.css`) already does ✅

| Feature | Status | Code Location |
|---|---|---|
| Hotkey activation (`Ctrl+Shift+V`) | ✅ Done | `electron/main.js` → `toggleGlanceWindow()` |
| Screenshot capture before popup | ✅ Done | `electron/main.js` → `desktopCapturer.getSources()` |
| Screenshot received via IPC | ✅ Done | `glance.js` → `window.glanceAPI.onScreenshot()` |
| Window reset on re-show | ✅ Done | `glance.js` → `window.glanceAPI.onWindowShown()` |
| User message render | ✅ Done | `glance.js` → `appendMessage('user', ...)` |
| POST to `/api/palivision/analyze` | ✅ Done | `glance.js` → `sendQuery()` → `fetch(...)` |
| SSE streaming tokens to UI | ✅ Done | `glance.js` → `reader.read()` loop |
| Escape to hide window | ✅ Done | `glance.js` + `electron/main.js` |
| Auto-grow textarea | ✅ Done | `glance.js` → `inputEl` `input` event |
| OCR on screenshot (backend) | ✅ Done | `core/palivision_router.py` → `extract_text_from_b64()` |
| Vision model description (backend) | ✅ Done | `core/palivision_router.py` → `describe_screenshot()` |

### What is MISSING ❌

| Feature | Missing From | Symptom |
|---|---|---|
| Theme sync (light/dark) | `glance.css` has no `.light-mode` block; `glance.js` never reads `localStorage` | Glance stays dark even when PaliSpace switches to light mode |
| Markdown rendering | `glance.js` uses `.textContent` not `.innerHTML` | Code blocks, bold, lists rendered as raw text |
| Active model used in requests | `glance.js` never calls `/api/config`; backend defaults to `gemma4:e2b` always | Model switcher in PaliSpace has no effect on glance responses |
| Model indicator UI | No model pill in `glance.html` | User can't see or change the active model |
| Session persistence | `glance.js` never calls `/api/sessions/*` | Conversations lost after window close |
| Memory update after conversation | No call to any memory update from glance | Glance knowledge never enters PaliSpace memory/RAG |
| Voice input (mic button) | No `btn-mic` in `glance.html`, no recording logic in `glance.js` | Can't speak to PaliGlance |
| TTS output | No `enqueueTTSSentence()` in `glance.js` | Responses are silent |
| Web search toggle | No `btn-web-search` in `glance.html`; `/api/palivision/analyze` has no `web_search` param | Can't ground responses in live web data |
| Cookbook (model recommendations) | No cookbook button in `glance.html`, no `/api/cookbook/*` calls in `glance.js` | Users can't browse model recommendations from glance |
| Glance sessions visible in PaliSpace | `index.html`/`app.js` never fetches glance session data | Screen conversations are isolated |

---

## WHAT EXISTS IN PALISPACE THAT CAN BE REUSED

These are real, working things in the codebase. Extract from here, don't reinvent.

| Feature | Source File | Key Function/ID |
|---|---|---|
| Theme CSS vars (dark) | `ui/static/styles.css` | `:root { --bg-color, --panel-bg, ... }` |
| Theme CSS vars (light) | `ui/static/styles.css` | `.light-mode { ... }` |
| Theme toggle logic | `ui/static/app.js` line ~1443 | `applyTheme(theme)` — reads/writes `localStorage["theme"]` |
| Model fetch | `ui/static/app.js` → `ModelSwitcher` IIFE | `fetchCurrentModel()` — calls `/api/config` |
| Model list + switch | `ui/static/app.js` → `ModelSwitcher` IIFE | `fetchModels()`, `selectModel()` — calls `/api/models`, `/api/config/model` |
| Model switcher HTML | `ui/template/index.html` | `#model-switcher-pill`, `#model-switcher-dropdown`, `#model-switcher-area` |
| Voice mic button HTML | `ui/template/index.html` | `#btn-mic` + surrounding SVG |
| Voice recording | `ui/static/app.js` line ~1056 | `isRecording`, `audioContext`, `audioChunks`, `startRecording()` |
| STT transcription | `ui/static/app.js` | POST `/api/voice/transcribe` |
| TTS output | `ui/static/app.js` | `enqueueTTSSentence()`, `playNextTTS()` → POST `/api/voice/synthesize` |
| Web search button HTML | `ui/template/index.html` | `#btn-web-search.web-search-btn` |
| Web search flag | `ui/static/app.js` line ~936 | `btnWebSearch.classList.contains("active")` → `web_search=true` |
| Markdown rendering | `ui/static/app.js` line ~130 | `formatMarkdown(text)` — uses CDN: marked, katex, DOMPurify |
| Session creation | `ui/static/app.js` | `createNewSession()` → POST `/api/sessions/new` |
| Session load | `ui/static/app.js` | `fetchSessions()` → GET `/api/sessions` |
| Cookbook hardware | `ui/static/app.js` → `ModelSwitcher` | `loadHardware()` → GET `/api/cookbook/hardware` |
| Cookbook recommendations | `ui/static/app.js` → `ModelSwitcher` | `loadRecommendations()` → GET `/api/cookbook/recommendations` |
| Session storage (backend) | `core/api_server.py` line ~510 | `load_sessions()`, `save_sessions()`, `add_new_session()` — writes to `{field}/.palimind/sessions.json` |
| Memory update (backend) | `core/api_server.py` | `background_update_memory()` — summarises conversation + embeds into `ChatVectorStore` |

---

## IMPLEMENTATION PLAN

Work in this exact order. Commit after every phase.

---

## PHASE 1 — FIX THEME SYNC (30 minutes)

**Problem:** `glance.css` re-declares `:root` with hardcoded dark values and has no `.light-mode` override.
The glance window is a separate `BrowserWindow` — it never sees the `.light-mode` class from the main window.

### Step 1.1 — Add `.light-mode` block to `glance.css`

Open `ui/static/glance.css`. After the `:root { ... }` block, add:

```css
/* Light mode override — mirrors styles.css .light-mode block exactly */
.light-mode {
    --bg-color: #ffffff;
    --panel-bg: #f5f5f7;
    --border-color: #e5e5e7;
    --text-main: #000000;
    --text-muted: #6e6e73;
    --input-bg: #f5f5f7;
    --msg-user-bg: #e5e5ea;
    --bg-active: #e5e5e7;
}

.light-mode .glance-shell {
    box-shadow:
        0 25px 60px rgba(0, 0, 0, 0.15),
        0 0 0 1px rgba(0, 0, 0, 0.06);
}
```

### Step 1.2 — Read theme from `localStorage` on window show

In `ui/static/glance.js`, inside the `window.glanceAPI.onWindowShown()` callback (which already exists), add:

```js
window.glanceAPI.onWindowShown(() => {
    // === ADD THIS BLOCK ===
    const savedTheme = localStorage.getItem('theme') || 'dark';
    if (savedTheme === 'light') {
        document.documentElement.classList.add('light-mode');
    } else {
        document.documentElement.classList.remove('light-mode');
    }
    // === END ADDED BLOCK ===

    // (existing code below stays unchanged)
    _g.screenshotB64 = null;
    statusDot.classList.remove('captured');
    statusText.textContent = 'Capturing…';
    resetMessages();
    inputEl.value = '';
    inputEl.focus();
});
```

Also run the same theme check on initial page load (for cases where glance was already open):

```js
// Add near the top of glance.js, after the DOM refs block:
(function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    if (savedTheme === 'light') {
        document.documentElement.classList.add('light-mode');
    }
})();
```

### Step 1.3 — Verify

- Open PaliGlance with `Ctrl+Shift+V`
- Toggle theme in PaliSpace (Settings → Light/Dark)
- Close and reopen glance
- **Pass:** Glance matches PaliSpace's theme on every open

**Commit:** `fix(glance): theme sync via localStorage — add .light-mode to glance.css, read on window show`

---

## PHASE 2 — ACTIVE MODEL IN GLANCE REQUESTS (20 minutes)

**Problem:** `glance.js` → `sendQuery()` sends `{}` without `chat_model`.
The `palivision_router.py` defaults to `"gemma4:e2b"`. PaliSpace model changes have no effect.

### Step 2.1 — Fetch and store active model

In `glance.js`, add a module-level state variable and a fetch function:

```js
// Add to the _g state object at the top of glance.js:
const _g = {
    screenshotB64: null,
    isBusy: false,
    activeModel: 'gemma4:e2b',   // ← ADD THIS
};

// Add this function after the DOM refs block:
async function fetchActiveModel() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();
        _g.activeModel = data.chat_model || 'gemma4:e2b';
        updateModelPill();  // (we add this in Step 2.2)
    } catch (e) {
        console.warn('[PaliGlance] Could not fetch active model:', e);
    }
}
```

### Step 2.2 — Add a model pill to `glance.html`

In `ui/template/glance.html`, inside `.glance-header`, add after the `.glance-status` div:

```html
<!-- Model indicator — right side of header -->
<span id="glance-model-pill" class="glance-model-pill" title="Active model">gemma4:e2b</span>
```

Add to `glance.css`:

```css
.glance-model-pill {
    font-size: 0.65rem;
    color: var(--text-muted);
    background: var(--input-bg);
    border: 1px solid var(--border-color);
    padding: 2px 8px;
    border-radius: 10px;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.2px;
    -webkit-app-region: no-drag;
    cursor: default;
    max-width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
```

In `glance.js`, add DOM ref + update function:

```js
const modelPillEl = document.getElementById('glance-model-pill');

function updateModelPill() {
    if (modelPillEl) modelPillEl.textContent = _g.activeModel;
}
```

### Step 2.3 — Pass `chat_model` in every POST to analyze

In `glance.js` → `sendQuery()`, change the payload:

```js
// BEFORE:
const payload = {
    user_prompt: userText,
    image_b64: _g.screenshotB64 || '',
};

// AFTER:
const payload = {
    user_prompt: userText,
    image_b64: _g.screenshotB64 || '',
    chat_model: _g.activeModel,   // ← ADD THIS
};
```

### Step 2.4 — Fetch model on window show and on page load

```js
// In window.glanceAPI.onWindowShown(), add:
fetchActiveModel();

// Also call once on page load:
fetchActiveModel();
```

**Commit:** `feat(glance): use active Ollama model from /api/config in analyze requests`

---

## PHASE 3 — MARKDOWN RENDERING (15 minutes)

**Problem:** `assistantBubble.textContent = fullText` renders raw markdown text.
`app.js` uses `formatMarkdown()` via marked + KaTeX + DOMPurify loaded from CDN.

### Step 3.1 — Add CDN scripts to `glance.html`

Copy the exact same CDN links that `index.html` uses. In `glance.html` `<head>`, add:

```html
<!-- Markdown rendering — same CDNs as index.html -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css" />
<script defer src="https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/marked-katex-extension@4.0.0/dist/marked-katex-extension.umd.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/dompurify@3.0.6/dist/purify.min.js"></script>
```

**Important:** Place these BEFORE `<script src="/ui/static/glance.js"></script>`.
Use `defer` so scripts load without blocking rendering.

### Step 3.2 — Copy `formatMarkdown()` into `glance.js`

Copy the `formatMarkdown()` function from `app.js` (lines ~130–197) verbatim into `glance.js`.
Place it after the `updateModelPill()` function.

### Step 3.3 — Use `formatMarkdown()` instead of `textContent`

In `glance.js` → `sendQuery()`, in the streaming loop, change:

```js
// BEFORE:
fullText += token;
assistantBubble.textContent = fullText;

// AFTER:
fullText += token;
assistantBubble.innerHTML = formatMarkdown(fullText);
```

Also add `glance-msg-assistant` class a slight tweak — assistant messages should allow HTML:

In `glance.css` for `.glance-msg-assistant`, ensure it can handle HTML children:
```css
.glance-msg-assistant pre,
.glance-msg-assistant code {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
}
.glance-msg-assistant .code-box {
    background: var(--input-bg);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    margin: 6px 0;
    overflow: hidden;
}
.glance-msg-assistant .code-box-header {
    display: flex;
    justify-content: space-between;
    padding: 4px 10px;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.68rem;
    color: var(--text-muted);
}
.glance-msg-assistant .code-box pre {
    padding: 10px;
    margin: 0;
    overflow-x: auto;
}
.glance-msg-assistant .code-box-copy {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.68rem;
}
```

**Commit:** `feat(glance): markdown rendering via marked + KaTeX + DOMPurify`

---

## PHASE 4 — VOICE INPUT (STT) (45 minutes)

**Problem:** PaliGlance has no mic button. PaliSpace has full STT via Web Speech API + `/api/voice/transcribe`.

### Step 4.1 — Add mic button to `glance.html`

In `ui/template/glance.html`, inside `.glance-input-bar`, add the mic button before the send button:

```html
<button id="glance-mic-btn" class="glance-mic-btn" title="Voice Input" aria-label="Start voice input">
    <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24"
         fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
        <line x1="12" y1="19" x2="12" y2="23"></line>
        <line x1="8" y1="23" x2="16" y2="23"></line>
    </svg>
</button>
```

Add to `glance.css`:

```css
.glance-mic-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    background: var(--input-bg);
    color: var(--text-muted);
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.glance-mic-btn:hover {
    background: var(--bg-active);
    color: var(--text-main);
}
.glance-mic-btn.recording {
    background: #dc2626;
    color: #ffffff;
    border-color: #dc2626;
}
```

### Step 4.2 — Add DOM ref in `glance.js`

```js
const micBtn = document.getElementById('glance-mic-btn');
```

### Step 4.3 — Add voice recording logic to `glance.js`

Copy these variables and functions from `app.js` into `glance.js`:

```js
// ── Voice State ────────────────────────────────────────────────────────────
let _isRecording = false;
let _audioContext = null;
let _mediaStream = null;
let _processorNode = null;
let _audioChunks = [];

async function startGlanceRecording() {
    if (_isRecording) return;
    try {
        _mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        _audioContext = new AudioContext({ sampleRate: 16000 });
        const source = _audioContext.createMediaStreamSource(_mediaStream);
        _processorNode = _audioContext.createScriptProcessor(4096, 1, 1);
        _audioChunks = [];

        _processorNode.onaudioprocess = (e) => {
            const data = e.inputBuffer.getChannelData(0);
            _audioChunks.push(new Float32Array(data));
        };

        source.connect(_processorNode);
        _processorNode.connect(_audioContext.destination);

        _isRecording = true;
        if (micBtn) micBtn.classList.add('recording');
    } catch (err) {
        console.error('[PaliGlance] Mic error:', err);
    }
}

async function stopGlanceRecording() {
    if (!_isRecording) return;
    _isRecording = false;
    if (micBtn) micBtn.classList.remove('recording');

    if (_processorNode) _processorNode.disconnect();
    if (_mediaStream) _mediaStream.getTracks().forEach(t => t.stop());

    // Encode collected Float32 chunks as 16-bit PCM WAV
    const totalLen = _audioChunks.reduce((s, c) => s + c.length, 0);
    const pcm = new Int16Array(totalLen);
    let offset = 0;
    for (const chunk of _audioChunks) {
        for (const sample of chunk) {
            pcm[offset++] = Math.max(-32768, Math.min(32767, sample * 32768));
        }
    }

    const sampleRate = 16000;
    const wavBuffer = encodeWAV(pcm, sampleRate);
    const blob = new Blob([wavBuffer], { type: 'audio/wav' });

    // Transcribe via Faster-Whisper
    const formData = new FormData();
    formData.append('file', blob, 'voice.wav');

    try {
        const res = await fetch('/api/voice/transcribe', { method: 'POST', body: formData });
        const data = await res.json();
        const transcript = data.text || '';
        if (transcript) {
            inputEl.value = transcript;
            inputEl.dispatchEvent(new Event('input')); // trigger auto-grow
        }
    } catch (err) {
        console.error('[PaliGlance] Transcription error:', err);
    }
}

function encodeWAV(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeStr = (offset, str) => { for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i)); };
    writeStr(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true);
    writeStr(8, 'WAVE'); writeStr(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    writeStr(36, 'data'); view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) view.setInt16(44 + i * 2, samples[i], true);
    return buffer;
}
```

### Step 4.4 — Wire mic button

```js
if (micBtn) {
    micBtn.addEventListener('click', async () => {
        if (_isRecording) {
            await stopGlanceRecording();
        } else {
            await startGlanceRecording();
        }
    });
}
```

**Commit:** `feat(glance): voice input via /api/voice/transcribe — mic button + WAV recording`

---

## PHASE 5 — WEB SEARCH TOGGLE (30 minutes)

**Problem:** No web search button in glance. Backend `/api/palivision/analyze` ignores any web search intent.

### Step 5.1 — Add web search button to `glance.html`

In `.glance-input-bar`, add before the mic button:

```html
<button id="glance-web-search-btn" class="glance-web-search-btn" title="Toggle Web Search" aria-label="Toggle web search">
    <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24"
         fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="2" y1="12" x2="22" y2="12"></line>
        <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
    </svg>
</button>
```

Add to `glance.css`:

```css
.glance-web-search-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    background: var(--input-bg);
    color: var(--text-muted);
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.glance-web-search-btn.active {
    background: var(--bg-active);
    color: var(--text-main);
    border-color: var(--text-muted);
}
```

### Step 5.2 — Add DOM ref and toggle state in `glance.js`

```js
const webSearchBtn = document.getElementById('glance-web-search-btn');

// Add to _g state:
const _g = {
    screenshotB64: null,
    isBusy: false,
    activeModel: 'gemma4:e2b',
    webSearchEnabled: false,   // ← ADD THIS
};

// Wire toggle:
if (webSearchBtn) {
    webSearchBtn.addEventListener('click', () => {
        _g.webSearchEnabled = !_g.webSearchEnabled;
        webSearchBtn.classList.toggle('active', _g.webSearchEnabled);
        webSearchBtn.title = _g.webSearchEnabled ? 'Web Search ON' : 'Web Search OFF';
    });
}
```

### Step 5.3 — Pass `web_search` flag in the POST body

In `glance.js` → `sendQuery()`:

```js
const payload = {
    user_prompt: userText,
    image_b64: _g.screenshotB64 || '',
    chat_model: _g.activeModel,
    web_search: _g.webSearchEnabled,   // ← ADD THIS
};
```

### Step 5.4 — Accept and use `web_search` in the backend

In `core/palivision_router.py`, update `PalivisionRequest`:

```python
class PalivisionRequest(BaseModel):
    image_b64: str
    user_prompt: str
    chat_model: str = DEFAULT_CHAT_MODEL
    web_search: bool = False   # ← ADD THIS
```

In the `analyze_screen` function, after building `system_prompt`, add web search context when enabled:

```python
# After Step 3 (system_prompt is built), before Step 4 (streaming):
if req.web_search:
    try:
        from core.services.web_search_service import search_web  # create this or use existing
        web_results = await search_web(req.user_prompt)
        if web_results:
            system_prompt += f"\n\nWEB SEARCH RESULTS FOR CONTEXT:\n{web_results}"
    except Exception as e:
        logger.warning(f"[Palivision] Web search failed: {e}")
        # Continue without web results — non-fatal
```

> **Note for agent:** Check if `core/services/web_search_service.py` exists. If not, create it as a minimal wrapper that calls DuckDuckGo or the existing web search the main chat uses (search `core/` for `web_search` to find the existing implementation).

**Commit:** `feat(glance): web search toggle — button in UI + web_search param in analyze endpoint`

---

## PHASE 6 — SESSION PERSISTENCE (60 minutes)

**Problem:** `glance.js` never saves conversations. The existing session API (`/api/sessions/*`) requires `state.active_field` which is a user-selected local directory — PaliGlance has no field context.

**Architecture decision:** Save glance sessions to `~/.palimind/glance_sessions.json`.
Also show glance sessions in PaliSpace's sidebar under a "PaliGlance" section.

### Step 6.1 — Add glance session endpoints to `core/palivision_router.py`

```python
import json
from pathlib import Path

GLANCE_SESSIONS_PATH = Path.home() / ".palimind" / "glance_sessions.json"

def load_glance_sessions() -> dict:
    if GLANCE_SESSIONS_PATH.exists():
        try:
            return json.loads(GLANCE_SESSIONS_PATH.read_text("utf-8"))
        except Exception:
            pass
    return {"sessions": []}

def save_glance_sessions(data: dict):
    GLANCE_SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    GLANCE_SESSIONS_PATH.write_text(json.dumps(data, indent=2), "utf-8")


class GlanceSessionSaveRequest(BaseModel):
    session_id: str
    title: str
    messages: list[dict]        # [{"role": "user"|"assistant", "content": "...", "ts": 123}]
    screen_summary: str = ""    # OCR/vision summary — for memory retrieval


@router.post("/session/save")
async def save_glance_session(req: GlanceSessionSaveRequest):
    """
    Save or update a PaliGlance conversation to ~/.palimind/glance_sessions.json.
    Called from glance.js after each assistant response.
    """
    data = load_glance_sessions()
    existing = next((s for s in data["sessions"] if s["id"] == req.session_id), None)
    if existing:
        existing["messages"] = req.messages
        existing["title"] = req.title
        existing["updated_at"] = int(__import__("time").time())
    else:
        data["sessions"].insert(0, {
            "id": req.session_id,
            "title": req.title,
            "messages": req.messages,
            "screen_summary": req.screen_summary,
            "created_at": int(__import__("time").time()),
            "updated_at": int(__import__("time").time()),
        })
    save_glance_sessions(data)
    return {"status": "saved", "session_id": req.session_id}


@router.get("/sessions")
async def get_glance_sessions():
    """Return all saved PaliGlance sessions for the PaliSpace sidebar."""
    data = load_glance_sessions()
    return data
```

### Step 6.2 — Track session state in `glance.js`

```js
// Add to top-level state in glance.js:
let _glanceSessionId = null;
let _glanceMessages = [];
let _glanceScreenSummary = '';

function generateSessionId() {
    return 'glance_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
}
```

### Step 6.3 — Reset session state on `onWindowShown`

```js
// In onWindowShown callback, add:
_glanceSessionId = generateSessionId();
_glanceMessages = [];
_glanceScreenSummary = '';
```

### Step 6.4 — Append messages and save after each exchange

In `glance.js` → `sendQuery()`, after user message is rendered, add:

```js
// Track user message:
_glanceMessages.push({ role: 'user', content: userText, ts: Date.now() });
```

After the SSE stream completes and `fullText` is set, add:

```js
// Track assistant message:
if (fullText) {
    _glanceMessages.push({ role: 'assistant', content: fullText, ts: Date.now() });

    // Save session to backend (fire-and-forget)
    fetch('/api/palivision/session/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: _glanceSessionId,
            title: `Screen — ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`,
            messages: _glanceMessages,
            screen_summary: _glanceScreenSummary,
        }),
    }).catch(err => console.warn('[PaliGlance] Session save failed:', err));
}
```

### Step 6.5 — Store screen summary when screenshot arrives

In `glance.js` → `onScreenshot` handler, after `_g.screenshotB64` is set:

```js
// The summary isn't known until the first analyze call returns.
// Capture it from the first assistant response's context:
_glanceScreenSummary = ''; // Reset — will be updated after first response
```

The backend logs `System prompt built (N chars)` — the OCR text is available there. To expose it, add to `palivision_router.py` → `analyze_screen()`, at the start of `generate_sse()`, yield one SSE event with the screen summary:

```python
# Before the Ollama stream, yield the screen context as metadata:
yield f"data: {json.dumps({'type': 'screen_context', 'summary': ocr_text[:200]})}\\n\\n"
```

In `glance.js`, handle this in the SSE reader loop:

```js
if (parsed.type === 'screen_context') {
    _glanceScreenSummary = parsed.summary || '';
    continue;
}
const token = parsed.token || '';
```

### Step 6.6 — Show PaliGlance sessions in PaliSpace sidebar

In `ui/template/index.html`, inside `#fields-sidebar-content`, after the sessions section, add:

```html
<!-- PaliGlance History -->
<div class="sessions-sidebar-container" id="glance-sessions-section" style="display:none">
    <div class="sessions-sidebar-header">
        <h3>PaliGlance History</h3>
    </div>
    <div id="glance-session-list" class="session-list">
        <!-- Populated by app.js -->
    </div>
</div>
```

In `ui/static/app.js`, add a fetch for glance sessions (call on page load alongside `fetchSessions()`):

```js
async function fetchGlanceSessions() {
    try {
        const res = await fetch('/api/palivision/sessions');
        const data = await res.json();
        const sessions = data.sessions || [];
        renderGlanceSessions(sessions);
    } catch (e) {
        console.error('Error fetching glance sessions:', e);
    }
}

function renderGlanceSessions(sessions) {
    const listEl = document.getElementById('glance-session-list');
    const sectionEl = document.getElementById('glance-sessions-section');
    if (!listEl || !sectionEl) return;

    if (sessions.length === 0) {
        sectionEl.style.display = 'none';
        return;
    }

    sectionEl.style.display = '';
    listEl.innerHTML = '';
    sessions.slice(0, 10).forEach(sess => {
        const tab = document.createElement('div');
        tab.className = 'session-tab';
        tab.title = new Date(sess.created_at * 1000).toLocaleString();

        const nameSpan = document.createElement('span');
        nameSpan.className = 'session-tab-name';
        nameSpan.textContent = sess.title || 'Screen chat';
        tab.appendChild(nameSpan);

        // Clicking a glance session shows the messages inline
        tab.onclick = () => showGlanceSessionChat(sess);
        listEl.appendChild(tab);
    });
}

function showGlanceSessionChat(sess) {
    // Switch to main area and display the glance session messages
    // Render as read-only in the existing messages-container
    if (!chatInterface || !messagesContainer) return;
    
    welcomeScreen.style.display = 'none';
    chatInterface.style.display = 'flex';
    
    messagesContainer.innerHTML = '';
    if (activeFieldTitle) activeFieldTitle.textContent = sess.title || 'PaliGlance Session';

    sess.messages.forEach(msg => {
        const div = document.createElement('div');
        div.className = msg.role === 'user' ? 'msg user-msg' : 'msg bot-msg';
        div.innerHTML = msg.role === 'assistant' ? formatMarkdown(msg.content) : msg.content;
        messagesContainer.appendChild(div);
    });
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Call on page load:
fetchGlanceSessions();
```

**Commit:** `feat(glance): session persistence — save to ~/.palimind/glance_sessions.json, show in PaliSpace sidebar`

---

## PHASE 7 — MEMORY INTEGRATION (30 minutes)

**Problem:** PaliGlance conversations never enter the RAG/memory system.
The existing `background_update_memory()` in `api_server.py` requires a root field path and session_id.

### Step 7.1 — Add memory update endpoint to `palivision_router.py`

```python
class GlanceMemoryRequest(BaseModel):
    session_id: str
    user_message: str
    assistant_message: str
    screen_summary: str = ""


@router.post("/memory/update")
async def update_glance_memory(req: GlanceMemoryRequest, background_tasks: BackgroundTasks):
    """
    Index a PaliGlance conversation turn into the global episodic memory.
    Uses ~/.palimind as the root so memories are accessible across all fields.
    """
    from fastapi import BackgroundTasks
    import asyncio
    from pathlib import Path

    glance_root = Path.home() / ".palimind"
    glance_root.mkdir(parents=True, exist_ok=True)

    # Import the same memory pipeline used by the main chat
    from core.config import load_config
    from core.generative.summariser import summarise_conversation
    from core.storage.chat_store import ChatVectorStore
    from core.retrieval.embedder import generate_embeddings_batch
    import uuid, json

    # Load global config for model settings
    global_config_path = glance_root / "config.json"
    config = {}
    if global_config_path.exists():
        try:
            config = json.loads(global_config_path.read_text("utf-8"))
        except Exception:
            pass

    ollama_url = config.get("ollama_base_url", OLLAMA_BASE_URL)
    embed_model = config.get("embed_model", "nomic-embed-text")

    turn_content = (
        f"[PaliGlance Screen Analysis]\n"
        f"Screen context: {req.screen_summary}\n"
        f"User: {req.user_message}\n"
        f"Assistant: {req.assistant_message}"
    )

    async def do_embed():
        try:
            embs = await asyncio.to_thread(
                generate_embeddings_batch, [turn_content], ollama_url, embed_model
            )
            if embs and embs[0]:
                chunk_id = int(uuid.uuid4().int % (2**63))
                with ChatVectorStore(glance_root) as vstore:
                    vstore.insert([{
                        "vector": embs[0],
                        "chunk_id": chunk_id,
                        "session_id": req.session_id,
                        "content": turn_content
                    }])
                logger.info(f"[Palivision] Memory indexed for session {req.session_id}")
        except Exception as e:
            logger.warning(f"[Palivision] Memory update failed: {e}")

    background_tasks.add_task(do_embed)
    return {"status": "queued"}
```

### Step 7.2 — Call memory update from `glance.js` after each response

In `sendQuery()`, after the session save call, add:

```js
// Memory update — fire-and-forget, only when conversation has substance
if (fullText && fullText.length > 50) {
    fetch('/api/palivision/memory/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: _glanceSessionId,
            user_message: userText,
            assistant_message: fullText,
            screen_summary: _glanceScreenSummary,
        }),
    }).catch(err => console.warn('[PaliGlance] Memory update failed:', err));
}
```

**Commit:** `feat(glance): index conversations into PaliMind episodic memory via ChatVectorStore`

---

## PHASE 8 — COOKBOOK / MODEL RECOMMENDATIONS (30 minutes)

**Reality check:** In PaliMind, the "Cookbook" is a hardware + model recommendation panel —
it shows which Ollama models fit your hardware. It is NOT a prompt template library.
"Selecting an entry" in this context means "apply this model to the current session."

### Step 8.1 — Add cookbook button to `glance.html` header

```html
<!-- In .glance-header, after .glance-status: -->
<button id="glance-cookbook-btn" class="glance-icon-btn" title="Model Recommendations">
    <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
         fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path>
        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path>
    </svg>
</button>

<!-- Cookbook panel (hidden by default, opens over messages area) -->
<div id="glance-cookbook-panel" class="glance-cookbook-panel" style="display:none">
    <div class="glance-cookbook-header">
        <span>Recommended Models</span>
        <button id="glance-cookbook-close" class="glance-icon-btn">✕</button>
    </div>
    <div id="glance-cookbook-list" class="glance-cookbook-list">
        <span class="glance-loading">Loading recommendations...</span>
    </div>
</div>
```

### Step 8.2 — Add cookbook CSS to `glance.css`

```css
.glance-cookbook-panel {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: var(--panel-bg);
    z-index: 10;
    display: flex;
    flex-direction: column;
    padding: 12px 16px;
    gap: 8px;
}
.glance-cookbook-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--text-muted);
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border-color);
}
.glance-cookbook-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    overflow-y: auto;
    flex: 1;
}
.glance-rec-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    background: var(--input-bg);
    cursor: pointer;
    transition: background 0.15s;
}
.glance-rec-card:hover { background: var(--bg-active); }
.glance-rec-card.selected { border-color: var(--text-muted); }
.glance-rec-name { font-size: 0.8rem; color: var(--text-main); }
.glance-rec-size { font-size: 0.7rem; color: var(--text-muted); }
.glance-loading { font-size: 0.78rem; color: var(--text-muted); padding: 12px 0; }
```

### Step 8.3 — Wire cookbook in `glance.js`

```js
const cookbookBtn = document.getElementById('glance-cookbook-btn');
const cookbookPanel = document.getElementById('glance-cookbook-panel');
const cookbookClose = document.getElementById('glance-cookbook-close');
const cookbookList = document.getElementById('glance-cookbook-list');

let _cookbookLoaded = false;

async function loadCookbook() {
    if (_cookbookLoaded) return;
    _cookbookLoaded = true;
    try {
        const res = await fetch('/api/cookbook/recommendations?top=8');
        const data = await res.json();
        const recs = data.recommendations || [];
        cookbookList.innerHTML = '';
        if (recs.length === 0) {
            cookbookList.innerHTML = '<span class="glance-loading">No recommendations</span>';
            return;
        }
        recs.forEach(rec => {
            const card = document.createElement('div');
            card.className = `glance-rec-card${rec.name === _g.activeModel ? ' selected' : ''}`;
            card.innerHTML = `
                <span class="glance-rec-name">${rec.name}</span>
                <span class="glance-rec-size">${rec.params_b}B · ${rec.fit}</span>
            `;
            card.addEventListener('click', async () => {
                // Apply this model
                try {
                    await fetch('/api/config/model', {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ model_id: rec.name }),
                    });
                    _g.activeModel = rec.name;
                    updateModelPill();
                    // Update card selection state
                    cookbookList.querySelectorAll('.glance-rec-card').forEach(c => c.classList.remove('selected'));
                    card.classList.add('selected');
                } catch (e) {
                    console.error('[PaliGlance] Model switch failed:', e);
                }
                cookbookPanel.style.display = 'none';
            });
            cookbookList.appendChild(card);
        });
    } catch (e) {
        cookbookList.innerHTML = '<span class="glance-loading">Failed to load</span>';
    }
}

if (cookbookBtn) {
    cookbookBtn.addEventListener('click', () => {
        if (cookbookPanel.style.display === 'none') {
            cookbookPanel.style.display = 'flex';
            loadCookbook();
        } else {
            cookbookPanel.style.display = 'none';
        }
    });
}
if (cookbookClose) {
    cookbookClose.addEventListener('click', () => {
        cookbookPanel.style.display = 'none';
    });
}
```

**Commit:** `feat(glance): cookbook panel — hardware-aware model recommendations, click to apply model`

---

## PHASE 9 — LAYOUT SYNC (20 minutes)

**Problem:** `glance.css` defines its own input bar and shell styles independently.
Some values diverge from `styles.css` (border-radius, font-size, scrollbar).

### Step 9.1 — Audit differences

Open `ui/static/styles.css` and `ui/static/glance.css` side by side.
Check these specific values match:

| Property | `styles.css` value | `glance.css` value | Action |
|---|---|---|---|
| `font-family` | `"Inter", -apple-system, ...` | `"Inter", -apple-system, ...` | ✅ Match |
| `scrollbar-width` | `thin` | `thin` | ✅ Match |
| `scrollbar-color` | `var(--border-color) var(--panel-bg)` | `var(--border-color) transparent` | ⚠️ Fix |
| `border-radius` on input | Check `styles.css` input styles | Compare with `.glance-input-bar textarea` | Fix if different |
| Button border-radius | Check `.icon-btn` radius in `styles.css` | Compare with `.glance-send-btn` | Fix if different |

### Step 9.2 — Fix scrollbar `glance.css`

```css
/* In glance.css, update the scrollbar rule: */
* {
    scrollbar-color: var(--border-color) var(--panel-bg); /* match styles.css */
}
```

### Step 9.3 — Match button and input border-radius

Verify `.glance-send-btn` border-radius matches the equivalent button in `styles.css`.
Verify `.glance-input-bar textarea` border-radius matches `#chat-input` in `styles.css`.

Update `glance.css` to match exactly.

**Commit:** `fix(glance): layout sync — scrollbar, border-radius, button styles match PaliSpace`

---

## FINAL VERIFICATION CHECKLIST

Run through every item manually before closing this branch.

### Theme
- [ ] Start PaliSpace in dark mode → open PaliGlance → glance is dark
- [ ] Switch to light mode in Settings → close glance → reopen → glance is light
- [ ] No hardcoded background colors visible (open DevTools → Elements → check computed bg)

### Model
- [ ] Open glance → model pill shows current active Ollama model
- [ ] Change model in PaliSpace → close and reopen glance → pill updates
- [ ] Send a question → response comes from the correct model (check backend logs)

### Markdown
- [ ] Ask a code question → response renders with code box, copy button, syntax
- [ ] Ask a list question → renders as proper `<ul>/<li>` not `• item`
- [ ] Math expression → renders via KaTeX

### Voice
- [ ] Click mic → button turns red
- [ ] Speak → click mic again → text appears in textarea
- [ ] (Optional) Response is read aloud if TTS wired

### Web Search
- [ ] Toggle web search button → button highlights blue/active
- [ ] Send a "latest news about X" question with search ON → response contains current info
- [ ] Toggle OFF → response uses only screen + Ollama knowledge

### Session Persistence
- [ ] Chat 3+ turns in glance → close window → open PaliSpace → "PaliGlance History" section appears in sidebar
- [ ] Click the session → messages render in main chat area
- [ ] `~/.palimind/glance_sessions.json` exists and contains correct data

### Memory
- [ ] After session, check `ChatVectorStore` at `~/.palimind/` (or verify via ask query in PaliSpace referencing screen content)

### Cookbook
- [ ] Click book icon in glance header → panel slides over messages
- [ ] Model cards show with fit labels (FITS, TIGHT, CPU)
- [ ] Click a model card → model pill updates, panel closes
- [ ] Next message uses new model (check backend logs)

### Core (Regression)
- [ ] Screenshot still captured before window appears
- [ ] Status dot goes green after screenshot received
- [ ] Escape still hides window
- [ ] Hotkey `Ctrl+Shift+V` (or `Cmd+Shift+V`) still works
- [ ] Main PaliSpace window unaffected by all changes

---

## FILE CHANGE SUMMARY

| File | Type of Change |
|---|---|
| `ui/static/glance.css` | Add `.light-mode` block, fix scrollbar, add new component CSS |
| `ui/static/glance.js` | Add theme init, model fetch, markdown, voice, web-search state, session tracking, memory calls, cookbook logic |
| `ui/template/glance.html` | Add CDN scripts, mic button, web-search button, model pill, cookbook button + panel |
| `core/palivision_router.py` | Add `web_search` param to `PalivisionRequest`, add `/session/save`, `/sessions`, `/memory/update` endpoints |
| `ui/static/app.js` | Add `fetchGlanceSessions()`, `renderGlanceSessions()`, `showGlanceSessionChat()`, call on page load |
| `ui/template/index.html` | Add PaliGlance History section to sidebar |
| `electron/preload.js` | No changes needed — `glanceAPI` bridge is complete |
| `electron/main.js` | No changes needed — hotkey and IPC are complete |

---

## DO NOT DO THESE THINGS

| ❌ Wrong | ✅ Right |
|---|---|
| `import ThemeProvider from './ThemeProvider'` | Read `localStorage["theme"]` in `glance.js` |
| Create a new `SessionService` class | Add endpoints to `palivision_router.py` |
| Create a new SQLite database for glance | Write to `~/.palimind/glance_sessions.json` |
| Install React/Next.js | This is Vanilla JS. Add functions, not frameworks |
| Copy the entire `app.js` into `glance.js` | Extract only the specific functions you need |
| Load `app.js` in `glance.html` | That would load all of PaliSpace — it would break |
| Create a new vector store | Use `ChatVectorStore` from `core/storage/chat_store.py` |
| Create a new embedding pipeline | Call `generate_embeddings_batch` from `core/retrieval/embedder.py` |
| Hardcode the Ollama URL | Read from `/api/config` → `ollama_base_url` |

