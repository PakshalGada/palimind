/**
 * glance.js — PaliGlance popup logic
 *
 * Self-contained. Does NOT depend on app.js or any main-app JS.
 *
 * Flow:
 *  1. Main process captures screen BEFORE showing this window.
 *  2. Main process sends screenshot via IPC 'glance:screenshot'.
 *  3. User types a question and presses Enter or clicks Send.
 *  4. We POST to /api/palivision/analyze with the stored image + prompt.
 *  5. We stream the SSE response and render tokens in real time.
 *  6. Escape hides the window (via IPC 'glance:hide').
 */

'use strict';

// ── Module state ──────────────────────────────────────────────────────────────
const _g = {
    screenshotB64: null,
    isBusy: false,
    activeModel: 'gemma4:e2b',
};

let _glanceSessionId = generateSessionId(); // initialize eagerly; reset on each show
let _glanceMessages = [];
let _glanceScreenSummary = '';

function generateSessionId() {
    return 'glance_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
}

// ── DOM refs ──────────────────────────────────────────────────────────────────
const messagesEl = document.getElementById('glance-messages');
const inputEl    = document.getElementById('glance-input');
const sendBtn    = document.getElementById('glance-send-btn');
const statusDot  = document.getElementById('glance-status-dot');
const statusText = document.getElementById('glance-status-text');

(function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    if (savedTheme === 'light') {
        document.documentElement.classList.add('light-mode');
    }
})();

async function fetchActiveModel() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();
        _g.activeModel = data.chat_model || 'gemma4:e2b';
        updateModelPill();
    } catch (e) {
        console.warn('[PaliGlance] Could not fetch active model:', e);
    }
}

function updateModelPill() {
    // Update both the popup pill label and the gmsNameSpan
    const nameEl = document.getElementById('glance-model-name');
    if (nameEl) nameEl.textContent = _g.activeModel;
}

fetchActiveModel();

// ── IPC bridge (set up by preload.js) ─────────────────────────────────────────

// Receive screenshot from main process
if (window.glanceAPI) {
    window.glanceAPI.onScreenshot((dataUrl) => {
        // dataUrl is a full data URL like "data:image/png;base64,<base64>"
        // Strip the prefix so we send raw base64 to the backend
        const prefix = 'data:image/png;base64,';
        if (dataUrl && dataUrl.startsWith(prefix)) {
            _g.screenshotB64 = dataUrl.slice(prefix.length);
        } else if (dataUrl && dataUrl.startsWith('data:image')) {
            // Other formats — extract base64 part after the comma
            _g.screenshotB64 = dataUrl.split(',')[1] || null;
        } else {
            _g.screenshotB64 = dataUrl || null;
        }

        if (_g.screenshotB64) {
            statusDot.classList.add('captured');
            statusText.textContent = 'Screen captured';
        } else {
            statusDot.classList.remove('captured');
            statusText.textContent = 'No capture';
        }
    });

    // Reset UI each time the window is re-shown
    window.glanceAPI.onWindowShown(() => {
        const savedTheme = localStorage.getItem('theme') || 'dark';
        if (savedTheme === 'light') {
            document.documentElement.classList.add('light-mode');
        } else {
            document.documentElement.classList.remove('light-mode');
        }

        fetchActiveModel();

        _glanceSessionId = generateSessionId();
        _glanceMessages = [];
        _glanceScreenSummary = '';
        _cookbookLoaded = false; // allow cookbook to reload on each window open

        _g.screenshotB64 = null;
        statusDot.classList.remove('captured');
        statusText.textContent = 'Capturing…';
        resetMessages();
        inputEl.value = '';
        inputEl.focus();
    });
} else {
    // Not running inside Electron (dev/browser testing fallback)
    console.warn('[PaliGlance] window.glanceAPI not available — running outside Electron?');
}

// ── UI helpers ────────────────────────────────────────────────────────────────

function resetMessages() {
    messagesEl.innerHTML = `
        <div class="glance-empty">
            <p>Ask anything about your screen.</p>
            <span class="glance-hint">Press <kbd>Esc</kbd> to dismiss</span>
        </div>
    `;
}

function appendMessage(role, text) {
    // Remove empty state on first message
    const emptyEl = messagesEl.querySelector('.glance-empty');
    if (emptyEl) emptyEl.remove();

    const div = document.createElement('div');
    div.className = `glance-msg glance-msg-${role}`;
    if (role === 'user') {
        div.textContent = text;
    } else {
        div.innerHTML = formatMarkdown(text);
    }
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
}

function setInputDisabled(disabled) {
    inputEl.disabled = disabled;
    sendBtn.disabled = disabled;
    _g.isBusy = disabled;
}

// ── Core send logic ───────────────────────────────────────────────────────────

async function sendQuery() {
    if (_g.isBusy) return;

    const userText = inputEl.value.trim();
    if (!userText) return;

    // Render user message immediately
    inputEl.value = '';
    setInputDisabled(true);
    appendMessage('user', userText);

    _glanceMessages.push({ role: 'user', content: userText, ts: Date.now() });

    // Show assistant thinking bubble
    const assistantBubble = appendMessage('assistant', '');
    assistantBubble.innerHTML = '<span class="glance-thinking">Analyzing screen…</span>';

    const payload = {
        user_prompt: userText,
        image_b64: _g.screenshotB64 || '',
        chat_model: _g.activeModel,
        web_search: _g.webSearchEnabled,
    };

    try {
        const response = await fetch('/api/palivision/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }

        // Stream SSE tokens
        const reader   = response.body.getReader();
        const decoder  = new TextDecoder('utf-8');
        let buffer     = '';
        let fullText   = '';
        let firstToken = true;
        let streamDone = false;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete line

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed.startsWith('data: ')) continue;

                const payload = trimmed.slice(6);
                if (payload === '[DONE]') { streamDone = true; break; }

                try {
                    const parsed = JSON.parse(payload);
                    if (parsed.type === 'screen_context') {
                        _glanceScreenSummary = parsed.summary || '';
                        continue;
                    }

                    const token  = parsed.token || '';
                    if (token) {
                        if (firstToken) {
                            assistantBubble.innerHTML = '';
                            firstToken = false;
                        }
                        fullText += token;
                        assistantBubble.innerHTML = formatMarkdown(fullText);
                        messagesEl.scrollTop = messagesEl.scrollHeight;
                    }
                } catch (_) { /* ignore malformed */ }
            }
            if (streamDone) break;
        }


        if (!fullText) {
            assistantBubble.textContent = '(No response. Is Ollama running?)';
        } else {
            _glanceMessages.push({ role: 'assistant', content: fullText, ts: Date.now() });

            if (_glanceSessionId) {
                // Save session to backend (fire-and-forget)
                fetch('/api/palivision/session/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: _glanceSessionId,
                        title: `Screen — ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`,
                        messages: _glanceMessages,
                        screen_summary: _glanceScreenSummary,
                        screenshot_b64: _g.screenshotB64 || '',
                        ocr_text: _glanceScreenSummary || '',
                        chat_model: _g.activeModel,
                    }),
                }).catch(err => console.warn('[PaliGlance] Session save failed:', err));


                // Memory update — fire-and-forget, only when conversation has substance
                if (fullText.length > 50) {
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
            }
        }

    } catch (err) {
        console.error('[PaliGlance] Query error:', err);
        assistantBubble.textContent = `Error: ${err.message}`;
    } finally {
        setInputDisabled(false);
        inputEl.focus();
    }
}

// ── Event wiring ──────────────────────────────────────────────────────────────

// Markdown parser using marked, katex, and dompurify
let markedConfigured = false;

function formatMarkdown(text) {
  if (!text) return "";

  if (!markedConfigured && typeof marked !== "undefined") {
    const renderer = new marked.Renderer();

    renderer.code = function (code, language) {
      const langLabel = language ? language.toUpperCase() : "CODE";
      const escapedCode = code
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

      return `
        <div class="code-box">
          <div class="code-box-header">
            <span class="code-box-lang">${langLabel}</span>
            <button class="code-box-copy" type="button" aria-label="Copy code" onclick="copyCode(this)">Copy</button>
          </div>
          <pre><code>${escapedCode}</code></pre>
        </div>
      `;
    };

    if (typeof markedKatex !== "undefined") {
      marked.use(markedKatex({ throwOnError: false }));
    }
    marked.use({ renderer: renderer, breaks: true });
    markedConfigured = true;
  }

  if (typeof marked === "undefined") {
    return text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  let htmlResult = marked.parse(text);

  if (typeof DOMPurify !== "undefined") {
    htmlResult = DOMPurify.sanitize(htmlResult, {
      ADD_TAGS: ["math", "mi", "mo", "mn", "ms", "mspace", "mtext", "menclose", "merror", "mpadded", "mphantom", "mroot", "mrow", "msqrt", "mstyle", "mmultiscripts", "mover", "mprescripts", "msub", "msubsup", "msup", "munder", "munderover", "none", "semantics", "annotation", "annotation-xml"],
      ADD_ATTR: ["class", "style", "aria-hidden", "mathvariant", "encoding", "display", "xmlns"],
    });
  }

  return htmlResult;
}

window.copyCode = function (button) {
  const codeBox = button.closest(".code-box");
  const code = codeBox.querySelector("code").innerText;
  navigator.clipboard.writeText(code).then(() => {
    button.innerText = "Copied!";
    setTimeout(() => { button.innerText = "Copy"; }, 2000);
  });
};

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

// ── Unified Model Selector (popup) ────────────────────────────────────────────

const _gms = {
    open: false,
    models: [],
    cookbookLoaded: false,
};

const gmsBtn        = document.getElementById('glance-model-btn');
const gmsDropdown   = document.getElementById('glance-model-dropdown');
const gmsSearch     = document.getElementById('glance-model-search');
const gmsModelList  = document.getElementById('glance-model-list');
const gmsCookbook   = document.getElementById('glance-cookbook-recs');
const gmsNameSpan   = document.getElementById('glance-model-name');

function gmsOpen() {
    if (!gmsDropdown) return;
    _gms.open = true;
    gmsDropdown.style.display = 'flex';
    gmsSwitchTab('models');
    if (gmsSearch) { gmsSearch.value = ''; gmsSearch.focus(); }
    gmsFetchModels();
}

function gmsClose() {
    if (!gmsDropdown) return;
    _gms.open = false;
    gmsDropdown.style.display = 'none';
}

function gmsSwitchTab(tab) {
    const modelsPanel   = document.getElementById('glance-ms-models');
    const cookbookPanel = document.getElementById('glance-ms-cookbook');
    document.querySelectorAll('.glance-ms-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tab);
    });
    if (modelsPanel)   modelsPanel.style.display   = tab === 'models'   ? 'flex' : 'none';
    if (cookbookPanel) cookbookPanel.style.display = tab === 'cookbook' ? 'flex' : 'none';
    if (tab === 'cookbook' && !_gms.cookbookLoaded) {
        _gms.cookbookLoaded = true;
        gmsLoadCookbook();
    }
}

async function gmsFetchModels() {
    if (gmsModelList) gmsModelList.innerHTML = '<span class="glance-loading">Fetching models...</span>';
    try {
        const res  = await fetch('/api/models');
        const data = await res.json();
        _gms.models = data.models || [];
        _g.activeModel = data.current_model || _g.activeModel;
        if (gmsNameSpan) gmsNameSpan.textContent = _g.activeModel;
        updateModelPill();

        if (_gms.models.length === 0) {
            const msg  = data.status === 'offline' ? 'Ollama is offline' : 'No models installed';
            const hint = data.status === 'offline' ? 'Start Ollama and retry' : 'Run: ollama pull llama3.2';
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
        if (gmsModelList) gmsModelList.innerHTML = '<span class="glance-loading">Connection error</span>';
    }
}

function gmsRenderModels() {
    if (!gmsModelList) return;
    const q = gmsSearch ? gmsSearch.value.toLowerCase() : '';
    const filtered = q
        ? _gms.models.filter(m => m.model_id.toLowerCase().includes(q))
        : _gms.models;

    gmsModelList.innerHTML = '';
    if (filtered.length === 0) {
        gmsModelList.innerHTML = '<span class="glance-loading">No match</span>';
        return;
    }
    filtered.forEach(m => {
        const item = document.createElement('div');
        item.className = 'glance-model-item' + (m.model_id === _g.activeModel ? ' active' : '');
        item.innerHTML = `
            <span class="glance-model-item-name">${m.display_name || m.model_id}</span>
            <span class="glance-model-item-meta">${m.parameter_size || ''} ${m.size_gb ? m.size_gb + 'GB' : ''}</span>
        `;
        item.addEventListener('click', () => gmsSelectModel(m.model_id));
        gmsModelList.appendChild(item);
    });
}

async function gmsSelectModel(modelId) {
    _g.activeModel = modelId;
    if (gmsNameSpan) gmsNameSpan.textContent = modelId;
    updateModelPill();
    gmsClose();
    try {
        await fetch('/api/config/model', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId }),
        });
    } catch (e) { /* fire and forget */ }
}

async function gmsLoadCookbook() {
    if (!gmsCookbook) return;
    try {
        const res  = await fetch('/api/cookbook/recommendations?top=8');
        const data = await res.json();
        const recs = data.recommendations || [];
        if (recs.length === 0) {
            gmsCookbook.innerHTML = '<span class="glance-loading">No recommendations</span>';
            return;
        }
        gmsCookbook.innerHTML = '';
        recs.forEach(rec => {
            const card = document.createElement('div');
            card.className = 'glance-rec-card' + (rec.name === _g.activeModel ? ' selected' : '');
            card.innerHTML = `
                <span class="glance-rec-name">${rec.name}</span>
                <span class="glance-rec-size">${rec.params_b}B · ${rec.fit}</span>`;
            card.addEventListener('click', () => gmsSelectModel(rec.name));
            gmsCookbook.appendChild(card);
        });
    } catch (e) {
        gmsCookbook.innerHTML = '<span class="glance-loading">Failed to load</span>';
    }
}

if (gmsBtn) {
    gmsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        _gms.open ? gmsClose() : gmsOpen();
    });
}
document.addEventListener('click', (e) => {
    if (_gms.open && gmsDropdown && !gmsDropdown.contains(e.target) && e.target !== gmsBtn) {
        gmsClose();
    }
});
if (gmsSearch) {
    gmsSearch.addEventListener('input', gmsRenderModels);
}
document.querySelectorAll('.glance-ms-tab').forEach(tab => {
    tab.addEventListener('click', (e) => {
        e.stopPropagation();
        gmsSwitchTab(tab.dataset.tab);
    });
});

// (web search and mic removed from popup — not available in minimal mode)


sendBtn.addEventListener('click', sendQuery);

inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendQuery();
    }

    // Escape → hide the popup window
    if (e.key === 'Escape') {
        if (window.glanceAPI) window.glanceAPI.hide();
    }
});

// Also catch Escape at document level (in case input isn't focused)
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (window.glanceAPI) window.glanceAPI.hide();
    }
});

// Auto-grow textarea
inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
});

// Focus input on load
window.addEventListener('DOMContentLoaded', () => {
    inputEl.focus();
});
