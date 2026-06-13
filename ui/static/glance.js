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
    webSearchEnabled: false,
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
const modelPillEl = document.getElementById('glance-model-pill');

const micBtn = document.getElementById('glance-mic-btn');
const webSearchBtn = document.getElementById('glance-web-search-btn');

const cookbookBtn = document.getElementById('glance-cookbook-btn');
const cookbookPanel = document.getElementById('glance-cookbook-panel');
const cookbookClose = document.getElementById('glance-cookbook-close');
const cookbookList = document.getElementById('glance-cookbook-list');

let _cookbookLoaded = false;

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
    if (modelPillEl) modelPillEl.textContent = _g.activeModel;
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
    div.textContent = text;
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

// ── Cookbook Logic ─────────────────────────────────────────────────────────
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

if (webSearchBtn) {
    webSearchBtn.addEventListener('click', () => {
        _g.webSearchEnabled = !_g.webSearchEnabled;
        webSearchBtn.classList.toggle('active', _g.webSearchEnabled);
        webSearchBtn.title = _g.webSearchEnabled ? 'Web Search ON' : 'Web Search OFF';
    });
}

if (micBtn) {
    micBtn.addEventListener('click', async () => {
        if (_isRecording) {
            await stopGlanceRecording();
        } else {
            await startGlanceRecording();
        }
    });
}

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
