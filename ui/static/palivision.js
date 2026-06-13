/**
 * palivision.js
 *
 * Vanilla JavaScript module for the Palivision screen-aware chat feature.
 *
 * This file handles everything on the frontend side of Palivision:
 *  1. Asking Electron for a list of screen/window sources (via the preload bridge)
 *  2. Starting a video stream of the selected source using getUserMedia
 *  3. Capturing the current video frame into a hidden <canvas> element
 *  4. Encoding that frame as base64 PNG
 *  5. Sending the image + user's question to POST /api/palivision/analyze
 *  6. Reading the SSE (Server-Sent Events) stream response
 *  7. Rendering each token as it arrives in the chat UI
 */

'use strict';

// ─── Module State ──────────────────────────────────────────────────────────────
// We keep all Palivision state in this object to avoid polluting the global scope.
const _pv = {
  stream: null,          // The active MediaStream from getUserMedia (or null)
  initialized: false,    // Whether pvInit() has already run
  isStreaming: false,    // Whether a video stream is currently active
};

// ─── Initialization ────────────────────────────────────────────────────────────

/**
 * pvInit() is called the first time the user clicks the Palivision sidebar button.
 * It only runs once. Sets up the source dropdown and button event listeners.
 */
async function pvInit() {
  if (_pv.initialized) return;
  _pv.initialized = true;

  console.log('[Palivision] Initializing...');

  // Wire up the "Ask" button and Enter key
  const sendBtn = document.getElementById('pv-send-btn');
  const inputEl = document.getElementById('pv-input');

  if (sendBtn) {
    sendBtn.addEventListener('click', pvSendQuery);
  }

  if (inputEl) {
    inputEl.addEventListener('keydown', (e) => {
      // Send on Enter (but not Shift+Enter, which should add a newline)
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        pvSendQuery();
      }
    });
  }

  // Wire up the source dropdown — when user picks a different screen/window, restart stream
  const sourceSelect = document.getElementById('pv-source-select');
  if (sourceSelect) {
    sourceSelect.addEventListener('change', async () => {
      const selectedId = sourceSelect.value;
      if (selectedId) {
        await pvStartStream(selectedId);
      }
    });
  }

  // Load the list of available screen/window sources
  await pvLoadSources();
}

// ─── Screen Source Listing ─────────────────────────────────────────────────────

/**
 * pvLoadSources() asks Electron for all available screen/window sources
 * and populates the dropdown select element.
 *
 * window.palivisionAPI is exposed by electron/preload.js via contextBridge.
 * If we're not running inside Electron (e.g., testing in a regular browser),
 * window.palivisionAPI won't exist — we show an error message instead.
 */
async function pvLoadSources() {
  const sourceSelect = document.getElementById('pv-source-select');
  const statusEl = document.getElementById('pv-status');

  // Check if we have the Electron bridge
  if (!window.palivisionAPI) {
    console.warn('[Palivision] window.palivisionAPI not found. Not running inside Electron?');
    pvShowStatus('Screen capture requires the Electron desktop app.', 'error');
    return;
  }

  try {
    pvShowStatus('Loading screen sources...', 'loading');
    const sources = await window.palivisionAPI.getSources();

    console.log(`[Palivision] Found ${sources.length} screen sources.`);

    if (!sources || sources.length === 0) {
      pvShowStatus('No screens found. Check your OS screen recording permissions.', 'error');
      return;
    }

    // Clear the dropdown and add all sources
    sourceSelect.innerHTML = '';
    sources.forEach((source) => {
      const option = document.createElement('option');
      option.value = source.id;       // The source ID used by getUserMedia
      option.textContent = source.name; // Human-readable name like "Entire Screen 1" or "VS Code"
      sourceSelect.appendChild(option);
    });

    // Automatically start streaming the first source
    const firstSourceId = sources[0].id;
    await pvStartStream(firstSourceId);

  } catch (err) {
    console.error('[Palivision] Failed to load sources:', err);
    pvShowStatus('Failed to get screen sources: ' + err.message, 'error');
  }
}

// ─── Video Stream Management ───────────────────────────────────────────────────

/**
 * pvStartStream() starts a video stream of the given screen/window source.
 *
 * How screen capture works in Electron:
 *   - Normally, getUserMedia only works for webcams/microphones in browsers
 *   - In Electron, you can pass a special `chromeMediaSource: 'desktop'` constraint
 *     along with a `chromeMediaSourceId` (the source ID from desktopCapturer)
 *   - This tells Chromium to capture the specified screen or window instead
 *   - The Electron main process grants permission for this via setPermissionRequestHandler
 *
 * @param {string} sourceId - The desktopCapturer source ID (from pvLoadSources)
 */
async function pvStartStream(sourceId) {
  const videoEl = document.getElementById('pv-video');

  // Stop any existing stream first to release the previous source
  pvStopStream();

  console.log(`[Palivision] Starting stream for source: ${sourceId}`);

  try {
    // This is the special Electron way to capture a screen or window
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        mandatory: {
          chromeMediaSource: 'desktop',
          chromeMediaSourceId: sourceId,
          maxWidth: 1280,   // Cap resolution to reduce memory usage
          maxHeight: 720,
        }
      }
    });

    _pv.stream = stream;
    _pv.isStreaming = true;

    // Bind the stream to the <video> element so the user can see what's being captured
    videoEl.srcObject = stream;
    await videoEl.play();

    // Update the status indicator to green (active)
    pvSetStatusDot('active');
    console.log('[Palivision] Stream started successfully.');

    // If the stream track ends (e.g., user closes the captured window), clean up
    stream.getVideoTracks()[0].addEventListener('ended', () => {
      console.log('[Palivision] Stream track ended (source window closed?).');
      pvStopStream();
    });

  } catch (err) {
    console.error('[Palivision] Failed to start stream:', err);
    pvSetStatusDot('error');
    pvShowStatus('Could not start stream: ' + err.message, 'error');
  }
}

/**
 * pvStopStream() stops the active video stream and releases the source.
 * Called when switching sources or when leaving the Palivision view.
 */
function pvStopStream() {
  if (_pv.stream) {
    _pv.stream.getTracks().forEach(track => track.stop());
    _pv.stream = null;
    _pv.isStreaming = false;
  }
  const videoEl = document.getElementById('pv-video');
  if (videoEl) {
    videoEl.srcObject = null;
  }
  pvSetStatusDot('idle');
}

// ─── Frame Capture ─────────────────────────────────────────────────────────────

/**
 * pvCaptureFrame() takes a snapshot of the current video frame.
 *
 * How it works:
 *   - The <video> element is showing a live stream of the screen
 *   - We draw the current frame onto a hidden <canvas> element
 *   - Then we export the canvas as a PNG and strip the "data:image/png;base64," prefix
 *   - The result is a raw base64 string that we can send to the Python backend
 *
 * Returns null if no stream is active.
 *
 * @returns {string|null} Raw base64-encoded PNG, or null if no stream
 */
function pvCaptureFrame() {
  const videoEl = document.getElementById('pv-video');
  const canvasEl = document.getElementById('pv-canvas');

  if (!_pv.isStreaming || !videoEl.videoWidth) {
    console.warn('[Palivision] No active stream to capture from.');
    return null;
  }

  // Set canvas size to match the video dimensions
  canvasEl.width = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;

  // Draw the current video frame onto the canvas
  const ctx = canvasEl.getContext('2d');
  ctx.drawImage(videoEl, 0, 0, canvasEl.width, canvasEl.height);

  // Export as PNG and remove the data URL prefix to get raw base64
  const dataUrl = canvasEl.toDataURL('image/png');
  const base64 = dataUrl.split(',')[1]; // Everything after the comma

  console.log(`[Palivision] Captured frame: ${canvasEl.width}x${canvasEl.height}, ${base64.length} base64 chars`);
  return base64;
}

// ─── Sending Queries ───────────────────────────────────────────────────────────

/**
 * pvSendQuery() is the main action — called when the user clicks "Ask" or presses Enter.
 *
 * It:
 *  1. Reads the user's question from the input textarea
 *  2. Captures the current screen frame (if a stream is active)
 *  3. Shows the user's message in the chat
 *  4. Posts to /api/palivision/analyze with the image + question
 *  5. Reads the SSE stream and appends each token to the assistant's message bubble
 */
async function pvSendQuery() {
  const inputEl = document.getElementById('pv-input');
  const sendBtn = document.getElementById('pv-send-btn');

  const userText = inputEl.value.trim();
  if (!userText) return;

  // Clear the input and disable the button while waiting for response
  inputEl.value = '';
  sendBtn.disabled = true;
  sendBtn.textContent = '...';

  // Show the user's message in the chat
  pvAppendMessage('user', userText);

  // Capture current frame
  const imageB64 = pvCaptureFrame(); // Will be null if no stream is active

  if (!imageB64) {
    pvAppendMessage('assistant', 
      '⚠️ No screen is being captured. Please select a screen source from the dropdown above, ' +
      'then try again. (Note: If you just want to ask a question without screen context, ' +
      'the answer may be less accurate.)'
    );
    sendBtn.disabled = false;
    sendBtn.textContent = 'Ask';
    return;
  }

  // Create an empty message bubble for the assistant's streaming response
  const assistantBubble = pvAppendMessage('assistant', '');
  assistantBubble.innerHTML = '<span class="pv-thinking">Analyzing screen...</span>';

  try {
    // POST to the Python backend
    const response = await fetch('/api/palivision/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_b64: imageB64,
        user_prompt: userText,
        // chat_model: 'gemma4:e2b'  // Uncomment to override the default model
      }),
    });

    if (!response.ok) {
      throw new Error(`Server returned ${response.status}: ${response.statusText}`);
    }

    // Read the SSE stream
    // The backend sends lines like:  data: {"token": "Hello"}
    // And a final line:              data: [DONE]
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let fullResponse = '';
    let isFirstToken = true;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE messages are separated by double newlines
      // Each line in a message starts with "data: "
      const lines = buffer.split('\n');
      buffer = lines.pop(); // Keep incomplete line in buffer

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data: ')) continue;

        const payload = trimmed.slice(6); // Remove "data: " prefix
        if (payload === '[DONE]') {
          // Stream complete
          console.log('[Palivision] Stream complete.');
          break;
        }

        try {
          const parsed = JSON.parse(payload);
          const token = parsed.token || '';
          if (token) {
            if (isFirstToken) {
              // Clear the "Analyzing screen..." placeholder on first real token
              assistantBubble.innerHTML = '';
              isFirstToken = false;
            }
            fullResponse += token;
            // Update the bubble with the accumulated text
            assistantBubble.textContent = fullResponse;
            // Auto-scroll to bottom
            const messagesEl = document.getElementById('pv-messages');
            if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
          }
        } catch (_) {
          // Ignore malformed JSON lines
        }
      }
    }

    if (!fullResponse) {
      assistantBubble.textContent = '(No response received. Is Ollama running?)';
    }

  } catch (err) {
    console.error('[Palivision] Query error:', err);
    assistantBubble.textContent = `Error: ${err.message}`;
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = 'Ask';
    inputEl.focus();
  }
}

// ─── UI Helpers ────────────────────────────────────────────────────────────────

/**
 * pvAppendMessage() adds a message bubble to the chat area.
 *
 * @param {'user'|'assistant'} role - Who is speaking
 * @param {string} text - The message content
 * @returns {HTMLElement} The created message div (so you can update it for streaming)
 */
function pvAppendMessage(role, text) {
  const messagesEl = document.getElementById('pv-messages');
  const div = document.createElement('div');
  div.className = `pv-message pv-message-${role}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

/**
 * pvSetStatusDot() updates the colored dot that shows stream status.
 *
 * @param {'idle'|'active'|'error'} state
 */
function pvSetStatusDot(state) {
  const dot = document.getElementById('pv-status-dot');
  if (!dot) return;
  dot.className = 'pv-status-dot'; // Reset
  if (state === 'active') dot.classList.add('pv-status-active');
  if (state === 'error') dot.classList.add('pv-status-error');
}

/**
 * pvShowStatus() shows a status message in the video preview area.
 * Used for errors and loading messages.
 *
 * @param {string} msg
 * @param {'error'|'loading'} type
 */
function pvShowStatus(msg, type) {
  const statusMsgEl = document.getElementById('pv-status-message');
  if (!statusMsgEl) return;
  statusMsgEl.textContent = msg;
  statusMsgEl.style.display = 'block';
  statusMsgEl.className = `pv-status-message pv-status-${type}`;
}

// ─── Public API ────────────────────────────────────────────────────────────────
// These functions are called from outside this file (from index.html inline scripts
// or from app.js when Palivision view is shown/hidden).

/**
 * Called by the sidebar click handler (wired in app.js) to initialize Palivision.
 * Safe to call multiple times — only initializes once.
 */
window.pvShow = async function() {
  await pvInit();
};

/**
 * Called by the sidebar click handler when switching AWAY from Palivision.
 * Stops the video stream to release screen capture resources.
 */
window.pvHide = function() {
  pvStopStream();
};
