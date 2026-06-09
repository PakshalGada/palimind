const btnAddField = document.getElementById('btn-add-field');
const fieldsList = document.getElementById('fields-list');
const btnUpdateActive = document.getElementById('btn-update-active');

const welcomeScreen = document.getElementById('welcome-screen');
const btnWelcomeAdd = document.getElementById('btn-welcome-add');
const chatInterface = document.getElementById('chat-interface');
const activeFieldTitle = document.getElementById('active-field-title');
const fileExplorerContainer = document.getElementById('file-explorer-container');
const fileTree = document.getElementById('file-tree');
const btnClearSelection = document.getElementById('btn-clear-selection');

const chatInput = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const btnMic = document.getElementById('btn-mic');
const messagesContainer = document.getElementById('messages-container');

const indexingProgressContainer = document.getElementById('indexing-progress-container');
const progressBarLabel = document.getElementById('progress-bar-label');

let activeField = null;
let activeSessionId = null;
let sessions = [];
let selectedFiles = new Set();
let lastTreeData = null;

const sessionTabs = document.getElementById('session-tabs');
const btnAddSession = document.getElementById('btn-add-session');

// Markdown parser with styled code boxes and copy buttons
function formatMarkdown(text) {
  if (!text) return "";
  
  // Escape HTML tags to prevent XSS and formatting issues, except we keep & untouched for now
  let escaped = text
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  
  // Extract and store code blocks
  const codeBlocks = [];
  escaped = escaped.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
    const index = codeBlocks.length;
    const langLabel = lang ? lang.toUpperCase() : "CODE";
    
    // We un-escape code block contents because we want it raw for displaying inside <code>
    const rawCode = code
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>');
      
    // Escape for html display inside code element
    const finalCode = rawCode
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
      
    const codeBox = `
      <div class="code-box">
        <div class="code-box-header">
          <span class="code-box-lang">${langLabel}</span>
          <button class="code-box-copy" onclick="copyCode(this)">Copy</button>
        </div>
        <pre><code>${finalCode}</code></pre>
      </div>
    `.trim();
    codeBlocks.push(codeBox);
    return `\n\n__CODE_BLOCK_PLACEHOLDER_${index}__\n\n`;
  });
  
  const lines = escaped.split('\n');
  let blocks = [];
  let currentBlock = [];
  let blockType = 'p'; // 'p', 'ul', 'ol'
  
  function flushBlock() {
    if (currentBlock.length === 0) return;
    const blockText = currentBlock.join('\n').trim();
    if (blockText.startsWith('__CODE_BLOCK_PLACEHOLDER_')) {
      blocks.push(blockText);
    } else if (blockType === 'ul') {
      blocks.push('<ul>' + currentBlock.map(line => `<li>${parseInlineMarkdown(line.substring(2))}</li>`).join('') + '</ul>');
    } else if (blockType === 'ol') {
      blocks.push('<ol>' + currentBlock.map(line => {
        const match = line.match(/^\d+\.\s+(.*)$/);
        return `<li>${parseInlineMarkdown(match ? match[1] : line)}</li>`;
      }).join('') + '</ol>');
    } else {
      // Check for headings
      if (blockText.startsWith('### ')) {
        blocks.push(`<h3>${parseInlineMarkdown(blockText.substring(4))}</h3>`);
      } else if (blockText.startsWith('## ')) {
        blocks.push(`<h2>${parseInlineMarkdown(blockText.substring(3))}</h2>`);
      } else if (blockText.startsWith('# ')) {
        blocks.push(`<h1>${parseInlineMarkdown(blockText.substring(2))}</h1>`);
      } else {
        blocks.push(`<p>${parseInlineMarkdown(blockText)}</p>`);
      }
    }
    currentBlock = [];
    blockType = 'p';
  }
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    
    if (trimmed === "") {
      flushBlock();
      continue;
    }
    
    if (trimmed.startsWith('__CODE_BLOCK_PLACEHOLDER_')) {
      flushBlock();
      currentBlock.push(trimmed);
      flushBlock();
      continue;
    }
    
    const isUlItem = trimmed.startsWith('- ') || trimmed.startsWith('* ') || trimmed.startsWith('+ ');
    const isOlItem = /^\d+\.\s+/.test(trimmed);
    
    if (isUlItem) {
      if (blockType !== 'ul') {
        flushBlock();
        blockType = 'ul';
      }
      currentBlock.push(trimmed);
    } else if (isOlItem) {
      if (blockType !== 'ol') {
        flushBlock();
        blockType = 'ol';
      }
      currentBlock.push(trimmed);
    } else {
      if (blockType !== 'p') {
        flushBlock();
      }
      currentBlock.push(line);
    }
  }
  flushBlock();
  
  let htmlResult = blocks.join('\n');
  
  // Restore code blocks
  for (let i = 0; i < codeBlocks.length; i++) {
    htmlResult = htmlResult.replace(`__CODE_BLOCK_PLACEHOLDER_${i}__`, codeBlocks[i]);
  }
  
  return htmlResult;
}

function parseInlineMarkdown(text) {
  // Parse bold **text**
  let parsed = text.replace(/\*\*([\s\S]*?)\*\*/g, '<strong>$1</strong>');
  // Parse italic *text*
  parsed = parsed.replace(/\*([\s\S]*?)\*/g, '<em>$1</em>');
  // Parse inline code `code`
  parsed = parsed.replace(/`([\s\S]*?)`/g, '<code class="inline-code">$1</code>');
  return parsed;
}

// Global copy helper for code boxes
window.copyCode = function(button) {
  const codeBox = button.closest('.code-box');
  const code = codeBox.querySelector('code').innerText;
  navigator.clipboard.writeText(code).then(() => {
    button.innerText = 'Copied!';
    button.classList.add('copied');
    setTimeout(() => {
      button.innerText = 'Copy';
      button.classList.remove('copied');
    }, 2000);
  });
};


function setChatDisabled(disabled) {
  chatInput.disabled = disabled;
  btnSend.disabled = disabled;
  btnMic.disabled = disabled;
  
  if (disabled) {
    chatInput.placeholder = "Please wait, indexing this field...";
    btnMic.style.opacity = '0.4';
    btnSend.style.opacity = '0.4';
    btnMic.style.pointerEvents = 'none';
    btnSend.style.pointerEvents = 'none';
  } else {
    chatInput.placeholder = "Ask the boardroom...";
    btnMic.style.opacity = '1';
    btnSend.style.opacity = '1';
    btnMic.style.pointerEvents = 'auto';
    btnSend.style.pointerEvents = 'auto';
  }
}

async function fetchFields() {
  try {
    const res = await fetch('/api/fields');
    const data = await res.json();
    renderFields(data.fields, data.active_field);
    updateMainArea(data.active_field);
    
    if (data.is_indexing) {
      indexingProgressContainer.style.display = 'flex';
      progressBarLabel.textContent = data.indexing_status || "Indexing field...";
      setChatDisabled(true);
    } else {
      indexingProgressContainer.style.display = 'none';
      setChatDisabled(false);
    }
  } catch (e) {
    console.error("Error fetching fields:", e);
  }
}

function renderFields(fields, currentActive) {
  fieldsList.innerHTML = '';
  fields.forEach(path => {
    const li = document.createElement('li');
    li.className = `field-item ${path === currentActive ? 'active' : ''}`;
    
    const folderName = path.split('\\').pop().split('/').pop();
    
    const nameSpan = document.createElement('span');
    nameSpan.className = 'field-name';
    nameSpan.textContent = folderName;
    nameSpan.title = path;
    nameSpan.onclick = () => setActiveField(path);
    
    const delBtn = document.createElement('button');
    delBtn.className = 'field-del-btn';
    delBtn.innerHTML = '×';
    delBtn.title = "Remove Field";
    delBtn.onclick = (e) => {
      e.stopPropagation();
      removeField(path);
    };
    
    li.appendChild(nameSpan);
    li.appendChild(delBtn);
    fieldsList.appendChild(li);
  });
  
  btnUpdateActive.style.display = currentActive ? 'block' : 'none';
}

async function removeField(path) {
  try {
    const res = await fetch('/api/fields/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    const data = await res.json();
    if (data.status === 'success') {
      await fetchFields();
    }
  } catch (e) {
    console.error("Error removing field:", e);
  }
}

function updateMainArea(currentActive) {
  activeField = currentActive;
  if (activeField) {
    welcomeScreen.style.display = 'none';
    chatInterface.style.display = 'flex';
    activeFieldTitle.textContent = activeField;
    selectedFiles.clear();
    fetchSessions();
    fetchFileTree();
  } else {
    welcomeScreen.style.display = 'flex';
    chatInterface.style.display = 'none';
    fileExplorerContainer.style.display = 'none';
  }
}

async function selectNewField() {
  try {
    const res = await fetch('/api/fields/select_dialog', { method: 'POST' });
    const data = await res.json();
    if (data.path) {
      setChatDisabled(true);
      indexingProgressContainer.style.display = 'flex';
      progressBarLabel.textContent = `Connecting to ${data.path.split('\\').pop().split('/').pop()}...`;
      
      const addRes = await fetch('/api/fields/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: data.path })
      });
      const addData = await addRes.json();
      if (!addData.error) {
        await fetchFields();
      } else {
        setChatDisabled(false);
        indexingProgressContainer.style.display = 'none';
        alert(addData.error);
      }
    }
  } catch (e) {
    console.error("Error selecting field:", e);
    setChatDisabled(false);
    indexingProgressContainer.style.display = 'none';
  }
}

async function setActiveField(path) {
  setChatDisabled(true);
  indexingProgressContainer.style.display = 'flex';
  progressBarLabel.textContent = `Connecting to ${path.split('\\').pop().split('/').pop()}...`;
  
  try {
    const res = await fetch('/api/fields/set_active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    const data = await res.json();
    if (!data.error) {
      messagesContainer.innerHTML = `
        <div class="message system-message">
          <div class="avatar system-avatar">P</div>
          <div class="message-content">
            <p>The Boardroom is ready. Your field context is loaded.</p>
          </div>
        </div>
      `;
      await fetchFields();
    } else {
      setChatDisabled(false);
      indexingProgressContainer.style.display = 'none';
      alert(data.error);
    }
  } catch (e) {
    console.error("Error setting active field:", e);
    setChatDisabled(false);
    indexingProgressContainer.style.display = 'none';
  }
}

btnUpdateActive.addEventListener('click', async () => {
  btnUpdateActive.textContent = 'Syncing...';
  try {
    const res = await fetch('/api/update', { method: 'POST' });
    const data = await res.json();
    if (data.status === 'success') {
      btnUpdateActive.textContent = `Synced (${data.indexed_files} added, ${data.deleted_files} del)`;
    } else {
      btnUpdateActive.textContent = `Error: ${data.error}`;
    }
    setTimeout(() => { btnUpdateActive.textContent = 'Sync Active Field'; }, 3000);
  } catch (e) {
    btnUpdateActive.textContent = 'Error!';
    setTimeout(() => { btnUpdateActive.textContent = 'Sync Active Field'; }, 3000);
  }
});

btnAddField.addEventListener('click', selectNewField);
btnWelcomeAdd.addEventListener('click', selectNewField);
btnAddSession.addEventListener('click', createNewSession);

btnClearSelection.addEventListener('click', () => {
  selectedFiles.clear();
  if (lastTreeData) {
    renderFileTree(lastTreeData);
  }
});

initEventsWatcher();

function appendMessage(role, text) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `message ${role === 'user' ? 'user-message' : 'system-message'}`;
  
  const avatar = document.createElement('div');
  avatar.className = `avatar ${role === 'user' ? 'user-avatar' : 'system-avatar'}`;
  avatar.textContent = role === 'user' ? 'U' : 'P';
  
  const content = document.createElement('div');
  content.className = 'message-content';
  
  if (role === 'system' && text === '') {
    msgDiv.appendChild(avatar);
    msgDiv.appendChild(content);
    messagesContainer.appendChild(msgDiv);
    return content;
  }
  
  content.innerHTML = formatMarkdown(text);
  
  msgDiv.appendChild(avatar);
  msgDiv.appendChild(content);
  messagesContainer.appendChild(msgDiv);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  return content;
}

async function fetchSessions() {
  if (!activeField) return;
  try {
    const res = await fetch('/api/sessions');
    const data = await res.json();
    if (data.error) return;
    sessions = data.sessions || [];
    activeSessionId = data.active_session_id;
    renderSessions();
    renderActiveSessionChat();
  } catch (e) {
    console.error("Error fetching sessions:", e);
  }
}

function renderSessions() {
  sessionTabs.innerHTML = '';
  sessions.forEach(sess => {
    const tab = document.createElement('div');
    tab.className = `session-tab ${sess.id === activeSessionId ? 'active' : ''}`;
    tab.onclick = () => switchSession(sess.id);

    const nameSpan = document.createElement('span');
    nameSpan.className = 'session-tab-name';
    nameSpan.textContent = sess.name;
    tab.appendChild(nameSpan);

    const closeBtn = document.createElement('span');
    closeBtn.className = 'session-tab-close';
    closeBtn.innerHTML = '×';
    closeBtn.title = "Delete Session";
    closeBtn.onclick = (e) => {
      e.stopPropagation();
      deleteSession(sess.id);
    };
    tab.appendChild(closeBtn);

    sessionTabs.appendChild(tab);
  });
}

async function switchSession(sessionId) {
  try {
    const res = await fetch('/api/sessions/set_active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    });
    const data = await res.json();
    if (!data.error) {
      sessions = data.sessions || [];
      activeSessionId = data.active_session_id;
      renderSessions();
      renderActiveSessionChat();
    }
  } catch (e) {
    console.error("Error switching session:", e);
  }
}

async function createNewSession() {
  try {
    const res = await fetch('/api/sessions/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: `Session ${sessions.length + 1}` })
    });
    const data = await res.json();
    if (!data.error) {
      sessions = data.sessions || [];
      activeSessionId = data.active_session_id;
      renderSessions();
      renderActiveSessionChat();
    }
  } catch (e) {
    console.error("Error creating session:", e);
  }
}

async function deleteSession(sessionId) {
  try {
    const res = await fetch('/api/sessions/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    });
    const data = await res.json();
    if (!data.error) {
      sessions = data.sessions || [];
      activeSessionId = data.active_session_id;
      renderSessions();
      renderActiveSessionChat();
    }
  } catch (e) {
    console.error("Error deleting session:", e);
  }
}

function renderActiveSessionChat() {
  messagesContainer.innerHTML = '';
  const currentSess = sessions.find(s => s.id === activeSessionId);
  if (currentSess && currentSess.messages && currentSess.messages.length > 0) {
    currentSess.messages.forEach(msg => {
      let contentText = "";
      if (msg.sources && msg.sources.length > 0) {
        contentText += `*Sources: ${msg.sources.join(', ')}*\n\n`;
      }
      contentText += msg.content;
      appendMessage(msg.role, contentText);
    });
  } else {
    appendMessage('system', 'The Boardroom is ready. Your field context is loaded.');
  }
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

async function fetchFileTree() {
  if (!activeField) {
    fileExplorerContainer.style.display = 'none';
    return;
  }
  try {
    const res = await fetch('/api/files/tree');
    const data = await res.json();
    if (data.error) {
      fileExplorerContainer.style.display = 'none';
      return;
    }
    fileExplorerContainer.style.display = 'flex';
    lastTreeData = data.tree;
    renderFileTree(data.tree);
  } catch (e) {
    console.error("Error fetching file tree:", e);
    fileExplorerContainer.style.display = 'none';
  }
}

function renderFileTree(treeNodes) {
  fileTree.innerHTML = '';
  if (!treeNodes || treeNodes.length === 0) {
    fileTree.innerHTML = '<div style="color: var(--text-muted); padding: 8px;">Empty folder</div>';
    return;
  }
  treeNodes.forEach(node => {
    fileTree.appendChild(createTreeNodeElement(node));
  });
}

function createTreeNodeElement(node) {
  const container = document.createElement('div');
  container.className = 'tree-node';
  
  const row = document.createElement('div');
  row.className = 'tree-node-row';
  
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'tree-checkbox';
  checkbox.checked = isNodeSelected(node);
  
  checkbox.onclick = (e) => {
    e.stopPropagation();
    toggleNodeSelection(node, checkbox.checked);
  };
  row.appendChild(checkbox);
  
  const icon = document.createElement('span');
  icon.className = 'tree-icon';
  icon.innerHTML = node.type === 'directory' ? '📁' : '📄';
  row.appendChild(icon);
  
  const nameSpan = document.createElement('span');
  nameSpan.className = 'node-name';
  nameSpan.textContent = node.name;
  nameSpan.title = node.path;
  row.appendChild(nameSpan);
  
  container.appendChild(row);
  
  if (node.type === 'directory' && node.children) {
    const childrenContainer = document.createElement('div');
    childrenContainer.className = 'tree-node-children';
    
    node.children.forEach(child => {
      childrenContainer.appendChild(createTreeNodeElement(child));
    });
    container.appendChild(childrenContainer);
    
    row.onclick = () => {
      const isCollapsed = childrenContainer.style.display === 'none';
      childrenContainer.style.display = isCollapsed ? 'flex' : 'none';
      icon.innerHTML = isCollapsed ? '📁' : '📂';
    };
  }
  
  return container;
}

function isNodeSelected(node) {
  if (node.type === 'file') {
    return selectedFiles.has(node.path);
  }
  if (node.children && node.children.length > 0) {
    const allFiles = getAllChildFiles(node);
    return allFiles.length > 0 && allFiles.every(p => selectedFiles.has(p));
  }
  return false;
}

function getAllChildFiles(node) {
  let files = [];
  if (node.type === 'file') {
    files.push(node.path);
  } else if (node.children) {
    node.children.forEach(child => {
      files = files.concat(getAllChildFiles(child));
    });
  }
  return files;
}

function toggleNodeSelection(node, isChecked) {
  const files = getAllChildFiles(node);
  files.forEach(p => {
    if (isChecked) {
      selectedFiles.add(p);
    } else {
      selectedFiles.delete(p);
    }
  });
  if (lastTreeData) {
    renderFileTree(lastTreeData);
  }
}

function initEventsWatcher() {
  const source = new EventSource('/api/events');
  source.onmessage = function(event) {
    const data = JSON.parse(event.data);
    if (data.type === 'sync') {
      showSyncToast(data.message);
      fetchFileTree();
    } else if (data.type === 'indexing_start') {
      indexingProgressContainer.style.display = 'flex';
      progressBarLabel.textContent = data.message || "Indexing field...";
      setChatDisabled(true);
    } else if (data.type === 'indexing_complete') {
      indexingProgressContainer.style.display = 'none';
      setChatDisabled(false);
      showSyncToast(data.message);
      fetchFileTree();
      fetchFields();
    } else if (data.type === 'indexing_error') {
      indexingProgressContainer.style.display = 'none';
      setChatDisabled(false);
      showSyncToast(data.message);
    }
  };
  source.onerror = function() {
    source.close();
    setTimeout(initEventsWatcher, 5000);
  };
}

function showSyncToast(message) {
  const toast = document.createElement('div');
  toast.className = 'sync-toast';
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 5000);
}

function appendTyping() {
  const msgDiv = document.createElement('div');
  msgDiv.className = `message system-message typing-msg`;
  msgDiv.innerHTML = `
    <div class="avatar system-avatar">P</div>
    <div class="message-content">
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>
  `;
  messagesContainer.appendChild(msgDiv);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  return msgDiv;
}

// --- TTS state (must be declared before sendMessage uses them) ---
let currentAudio = null;
let ttsQueue = [];
let isTTSPlaying = false;
let ttsActive = false;

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;
  
  // Capture voice input flag NOW before anything can reset it
  const triggeredByVoice = wasVoiceInput;
  wasVoiceInput = false;  // Reset for next input
  
  chatInput.value = '';
  appendMessage('user', text);
  
  // Initialise streaming TTS state for this turn
  if (triggeredByVoice) {
    stopTTSQueue(); // clear any previous queue
    ttsActive = true;
  }
  
  // Buffer for accumulating tokens between sentence boundaries
  let ttsBuffer = '';
  // Track whether we're inside a code block (to skip code from TTS)
  let codeBlockDepth = 0;

  // Flush accumulated buffer up to the last sentence boundary
  function flushTTSBuffer(force = false) {
    if (!ttsBuffer.trim()) return;
    if (force) {
      const s = ttsBuffer.trim();
      ttsBuffer = '';
      if (s.length >= 5) enqueueTTSSentence(s);
      return;
    }
    // Find the last sentence-ending boundary: . ! ? followed by whitespace
    let lastBoundary = -1;
    for (let i = 0; i < ttsBuffer.length - 1; i++) {
      if ('.!?'.includes(ttsBuffer[i]) && /\s/.test(ttsBuffer[i + 1])) {
        lastBoundary = i + 1; // include the punctuation
      }
    }
    if (lastBoundary > 0 && lastBoundary >= 12) {
      const sentence = ttsBuffer.substring(0, lastBoundary).trim();
      ttsBuffer = ttsBuffer.substring(lastBoundary).trimStart();
      enqueueTTSSentence(sentence);
    }
  }

  const typingInd = appendTyping();
  
  try {
    let url = `/api/chat?q=${encodeURIComponent(text)}${activeSessionId ? `&session_id=${activeSessionId}` : ''}`;
    if (selectedFiles.size > 0) {
      const filesParam = Array.from(selectedFiles).join(',');
      url += `&files=${encodeURIComponent(filesParam)}`;
    }
    const eventSource = new EventSource(url);
    
    let contentDiv = null;
    let fullText = "";

    eventSource.onmessage = async function(event) {
      if (typingInd.parentNode) {
        typingInd.remove();
      }
      
      const data = JSON.parse(event.data);
      
      if (data.type === 'sources') {
        if (data.sources && data.sources.length > 0) {
          fullText += `*Sources: ${data.sources.join(', ')}*\n\n`;
        }
        contentDiv = appendMessage('system', '');
        contentDiv.innerHTML = formatMarkdown(fullText);
      } else if (data.type === 'token') {
        if (!contentDiv) contentDiv = appendMessage('system', '');
        fullText += data.text;
        contentDiv.innerHTML = formatMarkdown(fullText);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        // --- Streaming TTS: accumulate and flush by sentence ---
        if (triggeredByVoice && ttsActive) {
          // Track code fence depth so we don't speak raw code
          const fences = (data.text.match(/```/g) || []).length;
          codeBlockDepth = (codeBlockDepth + fences) % 2;
          if (codeBlockDepth === 0) {
            ttsBuffer += data.text;
            flushTTSBuffer();
          }
        }

      } else if (data.type === 'error') {
        if (!contentDiv) contentDiv = appendMessage('system', '');
        fullText += `\n**Error:** ${data.text}`;
        contentDiv.innerHTML = formatMarkdown(fullText);
        eventSource.close();
      } else if (data.type === 'done') {
        eventSource.close();
        await fetchSessions();
        // Flush any remaining text in the buffer as the last TTS chunk
        if (triggeredByVoice && ttsActive) {
          flushTTSBuffer(true);
        }
      }
    };
    
    eventSource.onerror = function() {
      if (typingInd.parentNode) typingInd.remove();
      eventSource.close();
    };
    
  } catch(e) {
    if (typingInd.parentNode) typingInd.remove();
    appendMessage('system', `**Connection Error:** ${e.message}`);
  }
}

btnSend.addEventListener('click', () => {
  wasVoiceInput = false;
  sendMessage();
});
chatInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    wasVoiceInput = false;
    sendMessage();
  }
});

// --- Voice & Audio Engine (STT & TTS) ---
let isRecording = false;
let audioContext = null;
let mediaStream = null;
let sourceNode = null;
let processorNode = null;
let audioChunks = [];

let wasVoiceInput = false;
let recognition = null;
let speechTimeout = null;
let isSpeechCancelled = false;


// --- TTS Streaming Queue ---
// Sentences are synthesized concurrently as they're extracted from the stream.
// Synthesized audio blobs are stored in ttsQueue and played sequentially.


function cleanSentenceForTTS(sentence) {
  if (!sentence) return '';
  let s = sentence;
  // Skip sources prefix
  s = s.replace(/^\*Sources:.*?\*[\s\n]*/gm, '');
  // Remove code blocks - replace with pause word
  s = s.replace(/```[\s\S]*?```/g, '');
  // Unwrap inline code
  s = s.replace(/`([^`]+)`/g, '$1');
  // Unwrap bold / italic
  s = s.replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1');
  // Unwrap heading markers
  s = s.replace(/^#{1,6}\s+/gm, '');
  // Unwrap markdown links
  s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  // Collapse whitespace
  s = s.replace(/\s+/g, ' ').trim();
  return s;
}

function playNextTTS() {
  if (isTTSPlaying || ttsQueue.length === 0) return;

  const { blob, url: blobUrl } = ttsQueue.shift();
  isTTSPlaying = true;
  currentAudio = new Audio(blobUrl);

  const container = document.querySelector('.glass-container');
  if (container) {
    container.classList.remove('transcribing');
    container.classList.add('speaking');
  }

  const cleanup = () => {
    isTTSPlaying = false;
    try { URL.revokeObjectURL(blobUrl); } catch(e) {}
    currentAudio = null;
    if (ttsQueue.length === 0 && container) {
      container.classList.remove('speaking');
    }
    playNextTTS();
  };

  currentAudio.onended = cleanup;
  currentAudio.onerror = cleanup;
  currentAudio.play().catch(err => {
    console.warn('TTS playback error:', err);
    cleanup();
  });
}

// Fire-and-forget: synthesize a sentence and push its blob into the queue.
// Multiple synthesis calls can run concurrently; playback stays sequential.
function enqueueTTSSentence(sentence) {
  const cleaned = cleanSentenceForTTS(sentence);
  if (!cleaned || cleaned.length < 8) return;

  fetch('/api/voice/synthesize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: cleaned, voice: 'af_bella' })
  })
  .then(res => {
    if (!res.ok) throw new Error('TTS HTTP ' + res.status);
    return res.blob();
  })
  .then(blob => {
    if (!ttsActive) return; // response was cancelled
    const url = URL.createObjectURL(blob);
    ttsQueue.push({ blob, url });
    playNextTTS();
  })
  .catch(err => console.warn('TTS synthesis failed:', err));
}

function stopTTSQueue() {
  ttsActive = false;
  ttsQueue = [];
  isTTSPlaying = false;
  if (currentAudio) {
    try { currentAudio.pause(); } catch(e) {}
    currentAudio = null;
  }
  const container = document.querySelector('.glass-container');
  if (container) container.classList.remove('speaking', 'transcribing');
}


function initSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.warn("SpeechRecognition not supported in this browser.");
    return;
  }
  
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = 'en-US';
  
  recognition.onresult = (event) => {
    if (isSpeechCancelled) return;
    
    let interimTranscript = '';
    let finalTranscript = '';
    
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript;
      } else {
        interimTranscript += event.results[i][0].transcript;
      }
    }
    
    const textToShow = (finalTranscript || interimTranscript).trim();
    if (textToShow) {
      chatInput.value = textToShow;
    }
    
    if (speechTimeout) clearTimeout(speechTimeout);
    speechTimeout = setTimeout(() => {
      if (isRecording && !isSpeechCancelled) {
        stopRecordingAndSend(true);
      }
    }, 2000);
  };
  
  recognition.onerror = (e) => {
    console.error("SpeechRecognition error:", e);
  };
  
  recognition.onend = () => {
    if (isRecording && !isSpeechCancelled) {
      stopRecordingAndSend(true);
    }
  };
}

async function startRecording() {
  audioChunks = [];
  isSpeechCancelled = false;
  
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    alert("Microphone access denied or not available: " + err.message);
    return false;
  }
  
  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  
  processorNode = audioContext.createScriptProcessor(4096, 1, 1);
  processorNode.onaudioprocess = (e) => {
    const channelData = e.inputBuffer.getChannelData(0);
    audioChunks.push(new Float32Array(channelData));
  };
  
  sourceNode.connect(processorNode);
  processorNode.connect(audioContext.destination);
  
  isRecording = true;
  wasVoiceInput = true;
  
  const container = document.querySelector('.glass-container');
  container.classList.remove('speaking', 'transcribing', 'recording');
  container.classList.add('recording');
  btnMic.classList.add('active');
  btnMic.title = "Stop Recording";
  
  if (currentAudio) {
    try {
      currentAudio.pause();
    } catch(e){}
    currentAudio = null;
    container.classList.remove('speaking');
  }
  
  if (!recognition) {
    initSpeechRecognition();
  }
  if (recognition) {
    try {
      recognition.start();
    } catch(e){}
  }
  
  chatInput.value = "";
  return true;
}

function stopRecordingAndSend(shouldSend = true) {
  if (!isRecording) return;
  
  if (speechTimeout) clearTimeout(speechTimeout);
  
  if (recognition) {
    try {
      recognition.stop();
    } catch(e){}
  }
  
  // Capture audio context sample rate before closing
  const sampleRate = audioContext ? (audioContext.sampleRate || 44100) : 44100;
  
  if (processorNode) {
    processorNode.disconnect();
    sourceNode.disconnect();
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach(track => track.stop());
  }
  if (audioContext) {
    audioContext.close();
  }
  
  isRecording = false;
  
  const container = document.querySelector('.glass-container');
  container.classList.remove('recording');
  
  if (isSpeechCancelled) {
    btnMic.classList.remove('active', 'processing');
    btnMic.title = "Voice Input";
    chatInput.value = '';
    return;
  }
  
  btnMic.classList.remove('active');
  btnMic.title = "Voice Input";
  
  // Fast path: if Web Speech API already captured text, use it directly
  const existingText = chatInput.value.trim();
  if (existingText && shouldSend && !isSpeechCancelled) {
    console.log("Using Web Speech API result directly:", existingText);
    sendMessage();
    return;
  }
  
  // Fallback: use Whisper server-side transcription
  if (audioChunks.length === 0) {
    console.log("No audio captured.");
    return;
  }
  
  container.classList.add('transcribing');
  btnMic.classList.add('processing');
  btnMic.title = "Transcribing...";
  
  let totalLength = audioChunks.reduce((acc, chunk) => acc + chunk.length, 0);
  let mergedBuffer = new Float32Array(totalLength);
  let offset = 0;
  for (let chunk of audioChunks) {
    mergedBuffer.set(chunk, offset);
    offset += chunk.length;
  }
  
  const wavBlob = exportWAV(mergedBuffer, sampleRate);
  
  fetch('/api/voice/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: wavBlob
  })
  .then(res => res.json())
  .then(data => {
    container.classList.remove('transcribing');
    btnMic.classList.remove('processing');
    btnMic.title = "Voice Input";
    
    if (data.text) {
      chatInput.value = data.text;
      if (shouldSend && !isSpeechCancelled) {
        sendMessage();
      }
    } else if (data.error) {
      console.error("Transcription error:", data.error);
    }
  })
  .catch(err => {
    container.classList.remove('transcribing');
    btnMic.classList.remove('processing');
    btnMic.title = "Voice Input";
    console.error("Transcribe request failed:", err);
  });
}

function handleUserInteraction() {
  if (isRecording) {
    // Cancel ongoing voice recording and auto-send
    isSpeechCancelled = true;
    wasVoiceInput = false;
    if (speechTimeout) clearTimeout(speechTimeout);
    console.log("Voice input auto-send cancelled by user interaction.");
    stopRecordingAndSend(false);
  }
  // Stop any active TTS streaming (queue + current playback)
  if (ttsActive || currentAudio) {
    console.log("Stopping TTS queue on user interaction.");
    stopTTSQueue();
  }
}

function exportWAV(float32Array, sampleRate) {
  const buffer = new ArrayBuffer(44 + float32Array.length * 2);
  const view = new DataView(buffer);
  
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + float32Array.length * 2, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, 'data');
  view.setUint32(40, float32Array.length * 2, true);
  
  floatTo16BitPCM(view, 44, float32Array);
  
  return new Blob([view], { type: 'audio/wav' });
}

function floatTo16BitPCM(output, offset, input) {
  for (let i = 0; i < input.length; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, input[i]));
    output.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
}

function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}

btnMic.addEventListener('click', async () => {
  if (isRecording) {
    stopRecordingAndSend(true);
  } else {
    await startRecording();
  }
});

// Event listeners to cancel speech input auto-send or stop playback on user interactions
chatInput.addEventListener('mousedown', handleUserInteraction);
chatInput.addEventListener('keydown', handleUserInteraction);
chatInput.addEventListener('focus', handleUserInteraction);

// Initial load
fetchFields();
