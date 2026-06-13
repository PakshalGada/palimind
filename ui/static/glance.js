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
    screenshotB64: null,   // Raw base64 PNG from main process (no data-URL prefix)
    isBusy: false,         // True while streaming a response
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const messagesEl = document.getElementById('glance-messages');
const inputEl    = document.getElementById('glance-input');
const sendBtn    = document.getElementById('glance-send-btn');
const statusDot  = document.getElementById('glance-status-dot');
const statusText = document.getElementById('glance-status-text');

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

    // Show assistant thinking bubble
    const assistantBubble = appendMessage('assistant', '');
    assistantBubble.innerHTML = '<span class="glance-thinking">Analyzing screen…</span>';

    const payload = {
        user_prompt: userText,
        image_b64: _g.screenshotB64 || '',
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
                if (payload === '[DONE]') break;

                try {
                    const parsed = JSON.parse(payload);
                    const token  = parsed.token || '';
                    if (token) {
                        if (firstToken) {
                            assistantBubble.innerHTML = '';
                            firstToken = false;
                        }
                        fullText += token;
                        assistantBubble.textContent = fullText;
                        messagesEl.scrollTop = messagesEl.scrollHeight;
                    }
                } catch (_) { /* ignore malformed */ }
            }
        }

        if (!fullText) {
            assistantBubble.textContent = '(No response. Is Ollama running?)';
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
