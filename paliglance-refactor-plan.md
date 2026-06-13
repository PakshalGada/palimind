# PaliGlance → Full Refactor & Feature Plan
**Branch:** `palivision` | **Date:** Jun 13, 2026

---

## Phase 0 — Codebase Audit

### Files Touched by This Feature

| File | Role |
|---|---|
| `electron/main.js` | Creates `glanceWindow`, registers `Ctrl+Shift+V`, handles `glance:hide` IPC |
| `electron/preload.js` | Exposes `window.glanceAPI` and `window.electronBridge` bridges |
| `ui/template/glance.html` | PaliGlance popup window HTML |
| `ui/static/glance.css` | Popup styles |
| `ui/static/glance.js` | Popup logic — IPC bridge, screenshot receive, SSE streaming |
| `ui/template/index.html` | Contains `#glance-workspace` two-column layout (sidebar + main) |
| `ui/static/glance-workspace.css` | Workspace panel styles |
| `ui/static/app.js` | Workspace JS — session loading, sidebar render, `glanceWsSend`, mode switching |
| `ui/static/palivision.css` | OLD PaliVision panel styles (not removed yet, now unused) |
| `ui/static/palivision.js` | OLD PaliVision live-stream feature (not removed yet) |
| `core/palivision_router.py` | Backend — `/analyze`, `/session/save`, `/sessions`, `/memory/update` |

---

## Phase 1 — Bug & Inconsistency Audit

### 1.1 CSS / Design Token Mismatch (Critical)

`palivision.css` uses **completely different CSS variables** that don't exist in Palimind's token system:

| palivision.css uses | Palimind actual token | Effect |
|---|---|---|
| `--bg-primary` | `--bg-color` | Falls back to hardcoded `#0f0f0f` |
| `--bg-secondary` | `--panel-bg` | Falls back to `#161616` |
| `--border` | `--border-color` | Falls back to `#2a2a2a` |
| `--text-primary` | `--text-main` | Falls back to `#e0e0e0` |
| `--accent` | `--primary-color` | Falls back to `#6c7efa` (Tailwind Indigo — completely wrong) |

**Result:** PaliVision renders in a blue-accent, grey-bg theme completely detached from Palimind's monochrome black/white system. Light mode does nothing to PaliVision.

`glance-workspace.css` has a partial fix — it uses correct tokens — but `#glance-ws-send-btn` still has `background: var(--primary-color, #6366f1)`, which falls back to Tailwind Indigo if `--primary-color` isn't resolved.

### 1.2 glance.html Loads email.css (Bug)

```html
<!-- glance.html line 14 — wrong file -->
<link rel="stylesheet" href="/ui/static/email.css" />
```

`email.css` is a 24K stylesheet for PaliMail. It's being loaded into the popup window. This causes style pollution and slows down popup load time.

### 1.3 Continue Analysis: No Conversation History Sent (Critical Bug)

`glanceWsSend()` in `app.js` calls `/api/palivision/analyze` with:
```js
body: JSON.stringify({
    user_prompt: text,
    image_b64: _glanceWsActiveSess.screenshot_b64 || '',
    chat_model: _glanceWsActiveSess.chat_model || 'gemma4:e2b',
    web_search: false,
})
```

**No `messages` history is passed.** The backend builds a fresh prompt every call. Every "continue analysis" question is answered with zero memory of the conversation — the model has never seen the prior turns.

The fix: add `messages: _glanceWsActiveSess.messages` to the request body, and extend `PalivisionRequest` to accept optional `messages: list[dict]` and prepend them to the Ollama chat payload.

### 1.4 Continue Analysis: chat_model Never Persisted

`glanceWsSend` calls `session/save` without sending `chat_model`. The `GlanceSessionSaveRequest` schema has no `chat_model` field either. So when a session is restored, the model defaults to `'gemma4:e2b'` even if the user picked something else.

### 1.5 Session Card Active State Bug

```js
function openGlanceSession(sess) {
    // ...
    event?.currentTarget?.classList.add('active'); // BUG: 'event' is the global event
}
```

`openGlanceSession` is called from a click listener as `card.addEventListener('click', () => openGlanceSession(sess))`. The inner arrow function doesn't receive `event` as an argument, so `event` refers to `window.event` (deprecated global). This is unreliable and silently fails in most cases, meaning the active card never gets the `.active` class added by the function (though the prior `querySelectorAll` removal still runs correctly). The effect is that the selected card sometimes doesn't visually highlight.

### 1.6 No Model Selector in Workspace

The popup has a `glance-model-pill` that displays the current model, but it's read-only (`cursor: default`). The workspace has no model selector anywhere — not in new sessions, not in history sessions, not in the continue-analysis bar.

### 1.7 No "Open PaliGlance" Button

The only way to trigger a new capture is `Ctrl+Shift+V`. There's no button in the workspace's welcome or sidebar that launches the popup + capture flow.

### 1.8 No Countdown Modal Flow

The requirements specify: button click → centered modal → 3…2…1… countdown → instruction text → trigger capture. This doesn't exist at all.

### 1.9 Missing IPC Handler for Button-Triggered Glance

`window.electronBridge` only exposes `onSwitchMode`. There's no `triggerGlance()` call exposed to the main window renderer. A new IPC handler (`glance:open`) needs to be added to `main.js` and bridged via `preload.js`.

### 1.10 Screen History UX Issues

- Thumbnails are 52×38px — too small to be useful previews
- No message count badge visible on cards
- Meta section in conversation view uses emoji (`🕒 📝 💬`) instead of SVG icons — inconsistent with rest of Palimind
- No way to delete a session from the sidebar
- No "New Analysis" CTA in sidebar header
- Sidebar empty state only mentions keyboard shortcut — no button affordance

### 1.11 Screenshot Persistence Gap (Subtle Bug)

When `glanceWsSend` persists after a follow-up message, it calls `session/save` with empty `screenshot_b64`:
```js
fetch('/api/palivision/session/save', {
    body: JSON.stringify({
        session_id: ...,
        title: ...,
        messages: ...,
        screen_summary: ...,
        // screenshot_b64 not sent → backend skips overwrite → OK
    }),
})
```
The backend correctly skips screenshot overwrite when empty, so the screenshot is preserved on disk. **However**, the in-memory `_glanceWsActiveSess.screenshot_b64` is NOT updated either — it holds whatever was loaded at session-open time. If the session was loaded with a valid screenshot, this works. But if the fetch returned a session where `screenshot_b64` is empty (e.g., a session saved before the screenshot field was added), then continue-analysis sends an empty image to the vision model. The fix is to load the full session JSON including `screenshot_b64` from the API on open, and validate presence before analysis.

### 1.12 palivision.css / palivision.js Are Dead Code

These files implement the old "live stream" PaliVision feature (live video preview panel). The current `palivision` branch has replaced this with PaliGlance (hotkey + screenshot). These files are still loaded in `glance.html` (via `email.css` — actually this loads email.css not palivision.css, so palivision.css isn't even loaded in glance). The old `palivision.css`/`palivision.js` are referenced nowhere in the current active templates. They should be deleted or archived.

---

## Phase 2 — Implementation Plan

### Task 1 — Fix palivision.css Token Mapping
**Files:** `ui/static/palivision.css`

Replace all wrong variables:

```css
/* OLD → NEW */
--bg-primary  → --bg-color
--bg-secondary → --panel-bg
--border      → --border-color
--text-primary → --text-main
--accent      → --primary-color
```

Also replace the send button colors:
```css
/* OLD */
#pv-send-btn { background: var(--accent, #6c7efa); }
/* NEW */
#pv-send-btn { background: var(--primary-color); color: var(--primary-text); }
```

---

### Task 2 — Fix glance.html: Remove email.css, Fix Send Button Fallback
**Files:** `ui/template/glance.html`, `ui/static/glance-workspace.css`

Remove:
```html
<link rel="stylesheet" href="/ui/static/email.css" />
```

In `glance-workspace.css`, fix the send button:
```css
/* OLD */
#glance-ws-send-btn { background: var(--primary-color, #6366f1); }
/* NEW */
#glance-ws-send-btn {
    background: var(--primary-color);
    color: var(--primary-text);
}
#glance-ws-send-btn:hover { background: var(--primary-hover); }
```

---

### Task 3 — Add IPC for Button-Triggered Glance
**Files:** `electron/main.js`, `electron/preload.js`

**main.js** — add new IPC handler alongside the existing `glance:hide`:
```js
ipcMain.handle('glance:open', async () => {
    await toggleGlanceWindow();
});
```

**preload.js** — expose to main window renderer:
```js
contextBridge.exposeInMainWorld('electronBridge', {
    onSwitchMode: (callback) =>
        ipcRenderer.on('switch-mode', (_event, mode) => callback(mode)),
    // NEW
    openGlance: () => ipcRenderer.invoke('glance:open'),
});
```

---

### Task 4 — Add "Open PaliGlance" Button + Countdown Modal
**Files:** `ui/template/index.html`, `ui/static/glance-workspace.css`, `ui/static/app.js`

#### 4.1 Add button to workspace welcome screen

In `index.html`, inside `.glance-ws-welcome-inner`, add:
```html
<button id="glance-ws-launch-btn" class="glance-launch-btn">
  <svg><!-- camera/screen icon --></svg>
  Open PaliGlance
</button>
<span class="glance-ws-kbd-hint">or press <kbd>Ctrl+Shift+V</kbd></span>
```

Add to sidebar header alongside the title:
```html
<button id="glance-ws-new-btn" class="glance-icon-btn" title="New Analysis">
  <!-- plus icon -->
</button>
```

#### 4.2 Add countdown modal HTML (inject via JS, not static HTML)

In `app.js`, create a `showGlanceCountdown()` function:

```js
function showGlanceCountdown() {
    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'glance-countdown-overlay';
    overlay.innerHTML = `
        <div class="glance-countdown-modal">
            <div class="glance-countdown-number" id="glance-countdown-num">3</div>
            <p class="glance-countdown-label">Select or focus the screen or window you want PaliGlance to analyze</p>
        </div>
    `;
    document.body.appendChild(overlay);

    let count = 3;
    const numEl = document.getElementById('glance-countdown-num');
    const tick = setInterval(() => {
        count--;
        if (count > 0) {
            numEl.textContent = count;
            numEl.classList.remove('glance-countdown-pop');
            void numEl.offsetWidth; // force reflow to re-trigger animation
            numEl.classList.add('glance-countdown-pop');
        } else {
            clearInterval(tick);
            overlay.remove();
            // Fire the IPC to trigger the actual capture
            if (window.electronBridge?.openGlance) {
                window.electronBridge.openGlance();
            }
        }
    }, 1000);
}

document.getElementById('glance-ws-launch-btn')?.addEventListener('click', showGlanceCountdown);
document.getElementById('glance-ws-new-btn')?.addEventListener('click', showGlanceCountdown);
```

#### 4.3 Countdown modal CSS (in glance-workspace.css)

```css
.glance-countdown-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    animation: glanceFadeIn 0.2s ease;
    backdrop-filter: blur(4px);
}

.glance-countdown-modal {
    background: var(--panel-bg);
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 48px 56px;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 24px;
    box-shadow: 0 32px 80px rgba(0, 0, 0, 0.5);
    max-width: 480px;
}

.glance-countdown-number {
    font-size: 6rem;
    font-weight: 700;
    color: var(--text-main);
    line-height: 1;
    font-variant-numeric: tabular-nums;
    animation: glanceCountPop 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.glance-countdown-pop {
    animation: glanceCountPop 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes glanceCountPop {
    from { transform: scale(1.3); opacity: 0.5; }
    to   { transform: scale(1); opacity: 1; }
}

.glance-countdown-label {
    font-size: 0.95rem;
    color: var(--text-muted);
    line-height: 1.6;
    max-width: 340px;
}

.glance-launch-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 20px;
    background: var(--primary-color);
    color: var(--primary-text);
    border: none;
    border-radius: 10px;
    font-size: 0.9rem;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.15s, transform 0.1s;
}

.glance-launch-btn:hover { background: var(--primary-hover); }
.glance-launch-btn:active { transform: scale(0.97); }

.glance-ws-kbd-hint {
    font-size: 0.75rem;
    color: var(--text-muted);
}
.glance-ws-kbd-hint kbd {
    background: var(--bg-active);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 1px 5px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
}
```

---

### Task 5 — Fix Continue Analysis: Pass Conversation History
**Files:** `core/palivision_router.py`, `ui/static/app.js`

#### 5.1 Backend: extend PalivisionRequest

```python
class PalivisionRequest(BaseModel):
    image_b64: str
    user_prompt: str
    chat_model: str = DEFAULT_CHAT_MODEL
    web_search: bool = False
    # NEW: optional prior conversation turns
    messages: list[dict] = []
```

In `generate_sse()`, when building the Ollama payload, prepend history:

```python
ollama_messages = [{"role": "system", "content": system_prompt}]

# Inject prior conversation history (skip the last user message — it's sent separately)
for prior in req.messages:
    role = prior.get("role")
    content = prior.get("content", "")
    if role in ("user", "assistant") and content:
        ollama_messages.append({"role": role, "content": content})

# Current user turn
ollama_messages.append({"role": "user", "content": req.user_prompt})
```

#### 5.2 Frontend: send history in glanceWsSend

```js
async function glanceWsSend() {
    // ...
    const res = await fetch('/api/palivision/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_prompt: text,
            image_b64: _glanceWsActiveSess.screenshot_b64 || '',
            chat_model: _glanceWsActiveSess.chat_model || 'gemma4:e2b',
            web_search: false,
            messages: _glanceWsActiveSess.messages || [],  // ADD THIS
        }),
    });
    // ...
}
```

---

### Task 6 — Persist chat_model in Sessions
**Files:** `core/palivision_router.py`, `ui/static/glance.js`, `ui/static/app.js`

#### 6.1 Backend: add chat_model to schema

```python
class GlanceSessionSaveRequest(BaseModel):
    session_id: str
    title: str
    messages: list[dict]
    screen_summary: str = ""
    screenshot_b64: str = ""
    ocr_text: str = ""
    chat_model: str = ""   # NEW
```

In `save_glance_session`:
```python
if existing:
    # ...existing update logic...
    if req.chat_model:
        existing["chat_model"] = req.chat_model
else:
    data["sessions"].insert(0, {
        # ...existing fields...
        "chat_model": req.chat_model,
    })
```

#### 6.2 glance.js: include chat_model in save calls

```js
fetch('/api/palivision/session/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        session_id: _glanceSessionId,
        title: `Screen — ${...}`,
        messages: _glanceMessages,
        screen_summary: _glanceScreenSummary,
        screenshot_b64: _g.screenshotB64 || '',
        ocr_text: _glanceScreenSummary || '',
        chat_model: _g.activeModel,  // ADD
    }),
})
```

---

### Task 7 — Fix Session Card Active State
**Files:** `ui/static/app.js`

Change `openGlanceSession` to accept the card element directly:

```js
// OLD: card.addEventListener('click', () => openGlanceSession(sess));
// NEW:
card.addEventListener('click', function() {
    openGlanceSession(sess, this);
});

function openGlanceSession(sess, cardEl) {
    _glanceWsActiveSess = sess;

    // Remove active from all, add to clicked card
    document.querySelectorAll('.glance-ws-session-card').forEach(c => c.classList.remove('active'));
    if (cardEl) cardEl.classList.add('active');

    // ... rest of function unchanged
}
```

---

### Task 8 — Add Model Selector to Workspace
**Files:** `ui/template/index.html`, `ui/static/app.js`, `ui/static/glance-workspace.css`

#### 8.1 Add model selector to workspace input bar

In `index.html`, inside `.glance-ws-input-bar`:
```html
<div class="glance-ws-input-bar">
    <!-- NEW: model selector pill -->
    <select id="glance-ws-model-select" class="glance-ws-model-select" title="Select model"></select>
    <textarea id="glance-ws-input" placeholder="Continue this analysis…" rows="1"></textarea>
    <button id="glance-ws-send-btn" title="Send">...</button>
</div>
```

#### 8.2 Populate model selector

In `loadGlanceWorkspace()`, after loading sessions, also fetch available models:
```js
async function loadGlanceWorkspace() {
    // ...existing session load...
    await populateGlanceWsModelSelect();
}

async function populateGlanceWsModelSelect() {
    const sel = document.getElementById('glance-ws-model-select');
    if (!sel) return;
    try {
        const res = await fetch('/api/config');
        const data = await res.json();
        const models = data.available_models || [data.chat_model || 'gemma4:e2b'];
        sel.innerHTML = models.map(m =>
            `<option value="${m}">${m}</option>`
        ).join('');
        // Default to active session's model if available
        if (_glanceWsActiveSess?.chat_model) sel.value = _glanceWsActiveSess.chat_model;
    } catch (e) {}
}
```

In `glanceWsSend()`, read model from selector:
```js
chat_model: document.getElementById('glance-ws-model-select')?.value
    || _glanceWsActiveSess.chat_model
    || 'gemma4:e2b',
```

#### 8.3 CSS for model selector

```css
.glance-ws-model-select {
    background: var(--input-bg);
    border: 1px solid var(--border-color);
    color: var(--text-muted);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 0.78rem;
    font-family: 'JetBrains Mono', monospace;
    cursor: pointer;
    flex-shrink: 0;
    outline: none;
    transition: border-color 0.15s;
    max-width: 160px;
}
.glance-ws-model-select:focus { border-color: var(--text-muted); }
```

Also make the model pill in `glance.css` interactive (clickable to open cookbook):

Change from:
```css
.glance-model-pill { cursor: default; }
```
To:
```css
.glance-model-pill { cursor: pointer; }
.glance-model-pill:hover { border-color: var(--text-muted); }
```

---

### Task 9 — Screen History Redesign
**Files:** `ui/static/glance-workspace.css`, `ui/static/app.js`

#### 9.1 Larger thumbnails

```css
.glance-ws-card-thumb,
.glance-ws-card-thumb--empty {
    width: 72px;   /* was 52px */
    height: 48px;  /* was 38px */
}
```

#### 9.2 Message count badge on cards

In `renderGlanceWsSidebar`, add badge to card HTML:
```js
const msgCount = (sess.messages || []).length;
const badge = msgCount > 0
    ? `<span class="glance-ws-card-badge">${msgCount}</span>`
    : '';

card.innerHTML = `
    ${thumbHtml}
    <div class="glance-ws-card-body">
        <div class="glance-ws-card-header">
            <span class="glance-ws-card-title">${sess.title || 'Screen — ' + ts}</span>
            ${badge}
        </div>
        <span class="glance-ws-card-preview">${preview}</span>
        <span class="glance-ws-card-ts">${ts}</span>
    </div>`;
```

```css
.glance-ws-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
}
.glance-ws-card-badge {
    font-size: 0.62rem;
    color: var(--text-muted);
    background: var(--bg-active);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 1px 5px;
    flex-shrink: 0;
    font-family: 'JetBrains Mono', monospace;
}
```

#### 9.3 Delete session from sidebar

Add delete button to each card (shows on hover):
```js
card.innerHTML = `
    ...
    <button class="glance-ws-card-del" title="Delete" data-id="${sess.id}">
        <!-- X icon 12x12 -->
    </button>`;
```

Wire deletion:
```js
card.querySelector('.glance-ws-card-del')?.addEventListener('click', async (e) => {
    e.stopPropagation();
    const id = e.currentTarget.dataset.id;
    await fetch(`/api/palivision/session/${id}`, { method: 'DELETE' });
    _glanceWsSessions = _glanceWsSessions.filter(s => s.id !== id);
    if (_glanceWsActiveSess?.id === id) {
        _glanceWsActiveSess = null;
        document.getElementById('glance-ws-welcome').style.display = '';
        document.getElementById('glance-ws-convo').style.display = 'none';
    }
    renderGlanceWsSidebar(_glanceWsSessions);
});
```

Add DELETE endpoint to backend:
```python
@router.delete("/session/{session_id}")
async def delete_glance_session(session_id: str):
    data = load_glance_sessions()
    data["sessions"] = [s for s in data["sessions"] if s["id"] != session_id]
    save_glance_sessions(data)
    return {"status": "deleted"}
```

CSS for delete button:
```css
.glance-ws-card-del {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 20px;
    height: 20px;
    border-radius: 4px;
    border: none;
    background: var(--bg-active);
    color: var(--text-muted);
    display: none;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 0.7rem;
    transition: background 0.15s, color 0.15s;
}
.glance-ws-session-card { position: relative; }
.glance-ws-session-card:hover .glance-ws-card-del { display: flex; }
.glance-ws-card-del:hover { background: #dc2626; color: #fff; }
```

#### 9.4 Replace emoji meta with SVG icons

In `openGlanceSession`, replace:
```js
// OLD
ts ? `<span class="glance-meta-item">🕒 ${ts}</span>` : '',
sess.ocr_text ? `<span class="glance-meta-item">📝 ${sess.ocr_text.slice(0, 80)}...</span>` : '',
`<span class="glance-meta-item">💬 ${msgCount} message...</span>`,

// NEW
ts ? `<span class="glance-meta-item">
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
    </svg> ${ts}</span>` : '',
sess.ocr_text ? `<span class="glance-meta-item">
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    </svg> ${sess.ocr_text.slice(0, 80)}${sess.ocr_text.length > 80 ? '…' : ''}</span>` : '',
`<span class="glance-meta-item">
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg> ${msgCount} message${msgCount !== 1 ? 's' : ''}</span>`,
```

---

### Task 10 — Chat Improvements (Popup + Workspace)

#### 10.1 Better message bubbles in workspace

Add typing indicator animation when streaming:
```css
.glance-ws-msg--assistant.streaming::after {
    content: '▋';
    display: inline-block;
    animation: blink 0.8s step-end infinite;
    color: var(--text-muted);
    margin-left: 2px;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
```

Add `.streaming` class during token delivery, remove when done.

#### 10.2 Screenshot rendering in workspace

Current: image is shown in a fixed top panel that takes up space even when not scrolled to. Better pattern: make the screenshot panel collapsible.

Add a toggle button to `glance-ws-screenshot-panel`:
```html
<button id="glance-ws-toggle-screenshot" class="glance-icon-btn" title="Toggle screenshot">
    <!-- chevron icon -->
</button>
```

```css
.glance-ws-screenshot-panel.collapsed .glance-ws-screenshot-thumb { display: none; }
.glance-ws-screenshot-panel.collapsed .glance-ws-meta { display: none; }
.glance-ws-screenshot-panel.collapsed { padding: 8px 24px; }
```

#### 10.3 Markdown in popup messages

`glance.js` already uses `formatMarkdown()` with `marked` + `DOMPurify`. But user messages are set with `.textContent` which loses formatting. Fix:

```js
// In appendMessage():
if (role === 'user') {
    div.textContent = text;  // Keep as-is (user text shouldn't run markdown)
} else {
    // Already handled via streaming, but for initial render:
    div.innerHTML = formatMarkdown(text);
}
```

#### 10.4 Consistent message width in popup

Current popup: user messages `max-width: 90%`, assistant `max-width: 95%` — nearly full width, looks cramped. Adjust:

```css
.glance-msg-user { max-width: 80%; }
.glance-msg-assistant { max-width: 100%; padding: 9px 6px; }
```

---

### Task 11 — Dark/Light Mode Consistency

The popup window (`glance.html`) already syncs theme via `localStorage.getItem('theme')` on init and on `glance:shown`. This is correct. However:

1. The `light-mode` class needs to be applied to `<html>`, not `<body>` (currently `document.documentElement.classList.add('light-mode')` — correct).
2. `palivision.css` has NO `.light-mode` block at all — its hardcoded fallback variables are always dark. After the variable rename in Task 1, this resolves since Palimind's main token system handles light mode.
3. The workspace (inside `index.html`) inherits the main app's theme toggle correctly since it shares the same document. No action needed here.

---

### Task 12 — Remove Dead Code
**Files:** `ui/static/palivision.css`, `ui/static/palivision.js`

These implement the old live-stream feature that was replaced by the hotkey+screenshot approach. Neither file is referenced in any currently active template. Delete or move to `ui/static/archive/`.

Also clean up `ui/template/index.html` — check if `#palivision-workspace` still exists and remove it.

---

## Phase 3 — Implementation Order

Execute tasks in this order to avoid regressions:

```
1 → Token fix (CSS foundation — everything else depends on this)
2 → email.css removal + send button fix (quick wins)
3 → IPC handler (needed before Task 4)
4 → Countdown modal + launch button
5 → Continue Analysis history fix (backend + frontend together)
6 → chat_model persistence (backend + both frontends)
7 → Session card active state bug
8 → Model selector in workspace
9 → Screen History redesign (thumbnails, badge, delete, SVG meta)
10 → Chat improvements
11 → Light mode verification pass
12 → Dead code removal
```

---

## Phase 4 — File-by-File Change Summary

| File | Changes |
|---|---|
| `electron/main.js` | Add `ipcMain.handle('glance:open', ...)` |
| `electron/preload.js` | Expose `electronBridge.openGlance()` |
| `ui/template/glance.html` | Remove `email.css` link |
| `ui/static/glance.css` | Make model pill interactive; fix message widths |
| `ui/static/glance.js` | Include `chat_model` in session save |
| `ui/template/index.html` | Add launch button, new-analysis button, model select, screenshot toggle |
| `ui/static/glance-workspace.css` | Fix send button tokens; add countdown, launch btn, badge, delete btn styles; larger thumbnails |
| `ui/static/app.js` | Fix card active state; add `showGlanceCountdown()`; pass history in `glanceWsSend`; model select population; SVG meta; delete session |
| `ui/static/palivision.css` | Fix all CSS variable names |
| `core/palivision_router.py` | Extend `PalivisionRequest` with `messages`; extend `GlanceSessionSaveRequest` with `chat_model`; add `DELETE /session/{id}` endpoint; inject history into Ollama payload |
| `ui/static/palivision.js` | Delete (dead code) |

---

## Phase 5 — Testing Checklist

- [ ] `Ctrl+Shift+V` still works (regression test)
- [ ] "Open PaliGlance" button shows modal with 3-2-1 countdown
- [ ] After countdown, glance popup opens with fresh screenshot
- [ ] Model pill in popup is clickable and opens cookbook
- [ ] Popup correctly inherits dark/light theme
- [ ] Closing popup → PaliSpace sidebar shows new session with thumbnail
- [ ] Clicking session → screenshot displayed, messages rendered, model select set to session model
- [ ] "Continue this analysis…" sends history → model references prior turns
- [ ] Changing model select → new queries use selected model
- [ ] Delete button removes session from sidebar and clears main view
- [ ] Light mode: all PaliGlance/PaliVision elements match PaliSpace appearance
- [ ] Session with no screenshot: shows empty-thumb placeholder (not broken image)
- [ ] Long OCR text in meta is truncated at 80 chars with ellipsis
