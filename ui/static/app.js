const btnAddField = document.getElementById("btn-add-field");
const fieldsList = document.getElementById("fields-list");
const btnUpdateActive = document.getElementById("btn-update-active");

const welcomeScreen = document.getElementById("welcome-screen");
const btnWelcomeAdd = document.getElementById("btn-welcome-add");
const chatInterface = document.getElementById("chat-interface");
const activeFieldTitle = document.getElementById("active-field-title");
const fileExplorerContainer = document.getElementById(
  "file-explorer-container",
);
const fileTree = document.getElementById("file-tree");
const btnClearSelection = document.getElementById("btn-clear-selection");

const chatInput = document.getElementById("chat-input");
const btnSend = document.getElementById("btn-send");
const btnMic = document.getElementById("btn-mic");
const messagesContainer = document.getElementById("messages-container");

const indexingProgressContainer = document.getElementById(
  "indexing-progress-container",
);
const progressBarLabel = document.getElementById("progress-bar-label");

let allAgents = [];

const btnManageAgents = document.getElementById("btn-manage-agents");
const agentsModal = document.getElementById("agents-modal");
const btnCloseAgents = document.getElementById("btn-close-agents");
const agentsList = document.getElementById("agents-list");
const agentIdInput = document.getElementById("agent-id-input");
const agentNameInput = document.getElementById("agent-name-input");
const agentDescInput = document.getElementById("agent-desc-input");
const agentPromptInput = document.getElementById("agent-prompt-input");
const btnSaveAgent = document.getElementById("btn-save-agent");
const btnClearAgentForm = document.getElementById("btn-clear-agent-form");

const chatModeCheckbox = document.getElementById("chat-mode-checkbox");
const mentionsPopup = document.getElementById("mentions-popup");

let activeField = null;
let activeSessionId = null;
let sessions = [];
let selectedFiles = new Set();
let lastTreeData = null;

const sessionTabs = document.getElementById("session-tabs");
const btnAddSession = document.getElementById("btn-add-session");

// ── Workspace mode switching ─────────────────────────────────────────────
let _emailInitialised = false;

function switchToMode(mode) {
  const fieldsSidebar = document.getElementById("fields-sidebar-content");
  const mainArea      = document.getElementById("main-area");
  const emailWS       = document.getElementById("email-workspace");
  const navFields     = document.getElementById("nav-fields");
  const navEmail      = document.getElementById("nav-email");

  if (mode === "email") {
    if (fieldsSidebar) fieldsSidebar.style.display = "none";
    if (mainArea)      mainArea.style.display = "none";
    if (emailWS)       emailWS.classList.add("active");
    navFields?.classList.remove("active");
    navEmail?.classList.add("active");
    stopEmailPolling();
    if (!_emailInitialised) {
      _emailInitialised = true;
      wireEmailEvents();
      initEmailWorkspace();
    } else {
      startEmailPolling();
    }
  } else {
    if (fieldsSidebar) fieldsSidebar.style.display = "";
    if (mainArea)      mainArea.style.display = "";
    if (emailWS)       emailWS.classList.remove("active");
    navFields?.classList.add("active");
    navEmail?.classList.remove("active");
    stopEmailPolling();
  }
}

document.getElementById("nav-fields")?.addEventListener("click", () => switchToMode("fields"));
document.getElementById("nav-email")?.addEventListener("click",  () => switchToMode("email"));
// ─────────────────────────────────────────────────────────────────────────

// Markdown parser using marked, katex, and dompurify
let markedConfigured = false;

function formatMarkdown(text) {
  if (!text) return "";

  // Configure marked only once
  if (!markedConfigured && typeof marked !== "undefined") {
    const renderer = new marked.Renderer();

    // Custom code block renderer to preserve the code-box UI
    renderer.code = function (code, language) {
      const langLabel = language ? language.toUpperCase() : "CODE";
      // Escape HTML entities for display inside <code>
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

    // Use marked extensions
    if (typeof markedKatex !== "undefined") {
      marked.use(markedKatex({ throwOnError: false }));
    }
    marked.use({ renderer: renderer, breaks: true });
    markedConfigured = true;
  }

  if (typeof marked === "undefined") {
    // Fallback if CDNs failed to load
    return text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  let htmlResult = marked.parse(text);

  if (typeof DOMPurify !== "undefined") {
    // Sanitize while allowing KaTeX classes and math elements
    htmlResult = DOMPurify.sanitize(htmlResult, {
      ADD_TAGS: [
        "math",
        "mi",
        "mo",
        "mn",
        "ms",
        "mspace",
        "mtext",
        "menclose",
        "merror",
        "mpadded",
        "mphantom",
        "mroot",
        "mrow",
        "msqrt",
        "mstyle",
        "mmultiscripts",
        "mover",
        "mprescripts",
        "msub",
        "msubsup",
        "msup",
        "munder",
        "munderover",
        "none",
        "semantics",
        "annotation",
        "annotation-xml",
      ],
      ADD_ATTR: [
        "class",
        "style",
        "aria-hidden",
        "mathvariant",
        "encoding",
        "display",
        "xmlns",
      ],
    });
  }

  return htmlResult;
}

// Global copy helper for code boxes
window.copyCode = function (button) {
  const codeBox = button.closest(".code-box");
  const code = codeBox.querySelector("code").innerText;
  navigator.clipboard.writeText(code).then(() => {
    button.innerText = "Copied!";
    button.classList.add("copied");
    setTimeout(() => {
      button.innerText = "Copy";
      button.classList.remove("copied");
    }, 2000);
  });
};

function setChatDisabled(disabled) {
  chatInput.disabled = disabled;
  btnSend.disabled = disabled;
  btnMic.disabled = disabled;

  if (disabled) {
    chatInput.placeholder = "Please wait, indexing this field...";
    btnMic.style.opacity = "0.4";
    btnSend.style.opacity = "0.4";
    btnMic.style.pointerEvents = "none";
    btnSend.style.pointerEvents = "none";
  } else {
    chatInput.placeholder = "Ask anything.";
    btnMic.style.opacity = "1";
    btnSend.style.opacity = "1";
    btnMic.style.pointerEvents = "auto";
    btnSend.style.pointerEvents = "auto";
  }
}

async function fetchFields() {
  try {
    const res = await fetch("/api/fields");
    const data = await res.json();
    renderFields(data.fields, data.active_field);
    updateMainArea(data.active_field);

    if (data.is_indexing) {
      indexingProgressContainer.style.display = "flex";
      progressBarLabel.textContent =
        data.indexing_status || "Indexing field...";
      setChatDisabled(true);
    } else {
      indexingProgressContainer.style.display = "none";
      setChatDisabled(false);
    }
  } catch (e) {
    console.error("Error fetching fields:", e);
  }
}

fetchAgents();

const FIELD_TITLE_STORAGE_KEY = "palimind:field-display-titles";

function getPathLeaf(path) {
  if (!path) return "";
  return String(path).split(/[\\/]+/).filter(Boolean).pop() || String(path);
}

function titleCaseToken(token) {
  if (/^[A-Z0-9]{2,5}$/.test(token)) return token;
  if (/^[a-z]{1,3}$/i.test(token)) return token.toUpperCase();
  return token.charAt(0).toUpperCase() + token.slice(1).toLowerCase();
}

function deriveFieldTitle(path) {
  const leaf = getPathLeaf(path);
  if (!leaf) return "Field Workspace";

  const cleaned = leaf
    .replace(/\b\d{8}T\d{6}Z(?:-\d+)*\b/gi, "")
    .replace(/\b\d{8,14}\b/g, "")
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  const source = cleaned || leaf;
  const title = source
    .split(" ")
    .filter(Boolean)
    .map(titleCaseToken)
    .join(" ");

  if (/^[A-Z0-9]{2,5}$/.test(title) || title.length <= 4) {
    return `${title} Workspace`;
  }
  return title || "Field Workspace";
}

function getStoredFieldTitles() {
  try {
    return JSON.parse(localStorage.getItem(FIELD_TITLE_STORAGE_KEY) || "{}");
  } catch (e) {
    return {};
  }
}

function getFieldDisplayTitle(path) {
  const key = String(path || "");
  const titles = getStoredFieldTitles();
  if (titles[key]) return titles[key];

  const title = deriveFieldTitle(key);
  try {
    titles[key] = title;
    localStorage.setItem(FIELD_TITLE_STORAGE_KEY, JSON.stringify(titles));
  } catch (e) {
    // Non-critical: title persistence can fail in private or restricted storage.
  }
  return title;
}

function getFieldPathHint(path) {
  const parts = String(path || "").split(/[\\/]+/).filter(Boolean);
  if (parts.length <= 1) return path || "";
  return parts.slice(Math.max(0, parts.length - 3)).join(" / ");
}

function renderActiveFieldTitle(path) {
  if (!activeFieldTitle) return;
  const displayTitle = getFieldDisplayTitle(path);
  const pathHint = getFieldPathHint(path);

  activeFieldTitle.innerHTML = "";
  activeFieldTitle.title = path || displayTitle;
  activeFieldTitle.setAttribute("aria-label", `${displayTitle}. ${path || ""}`);

  const titleSpan = document.createElement("span");
  titleSpan.className = "active-field-name";
  titleSpan.textContent = displayTitle;
  activeFieldTitle.appendChild(titleSpan);

  if (pathHint && pathHint !== displayTitle) {
    const pathSpan = document.createElement("span");
    pathSpan.className = "active-field-path";
    pathSpan.textContent = pathHint;
    activeFieldTitle.appendChild(pathSpan);
  }
}

function renderFields(fields, currentActive) {
  fieldsList.innerHTML = "";
  fields.forEach((path) => {
    const li = document.createElement("li");
    li.className = `field-item ${path === currentActive ? "active" : ""}`;

    const fieldTitle = getFieldDisplayTitle(path);

    const nameSpan = document.createElement("span");
    nameSpan.className = "field-name";
    nameSpan.textContent = fieldTitle;
    nameSpan.title = path;
    nameSpan.onclick = () => setActiveField(path);

    const delBtn = document.createElement("button");
    delBtn.className = "field-del-btn";
    delBtn.innerHTML = "×";
    delBtn.title = "Remove Field";
    delBtn.onclick = (e) => {
      e.stopPropagation();
      removeField(path);
    };

    li.appendChild(nameSpan);
    li.appendChild(delBtn);
    fieldsList.appendChild(li);
  });

  btnUpdateActive.style.display = currentActive ? "block" : "none";
}

async function removeField(path) {
  try {
    const res = await fetch("/api/fields/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const data = await res.json();
    if (data.status === "success") {
      await fetchFields();
    }
  } catch (e) {
    console.error("Error removing field:", e);
  }
}

function updateMainArea(currentActive) {
  activeField = currentActive;
  if (activeField) {
    welcomeScreen.style.display = "none";
    chatInterface.style.display = "flex";
    renderActiveFieldTitle(activeField);
    selectedFiles.clear();
    fetchSessions();
    fetchFileTree();
  } else {
    welcomeScreen.style.display = "flex";
    chatInterface.style.display = "none";
    fileExplorerContainer.style.display = "none";
  }
}

async function selectNewField() {
  openDirPicker(activeField || "");
}

async function setActiveField(path) {
  setChatDisabled(true);
  indexingProgressContainer.style.display = "flex";
  progressBarLabel.textContent = `Connecting to ${path.split("\\").pop().split("/").pop()}...`;

  try {
    const res = await fetch("/api/fields/set_active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
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
      indexingProgressContainer.style.display = "none";
      alert(data.error);
    }
  } catch (e) {
    console.error("Error setting active field:", e);
    setChatDisabled(false);
    indexingProgressContainer.style.display = "none";
  }
}

btnUpdateActive.addEventListener("click", async () => {
  btnUpdateActive.textContent = "Syncing...";
  try {
    const res = await fetch("/api/update", { method: "POST" });
    const data = await res.json();
    if (data.status === "success") {
      btnUpdateActive.textContent = `Synced (${data.indexed_files} added, ${data.deleted_files} del)`;
      showSyncToast(
        `Synced successfully: ${data.indexed_files} added, ${data.deleted_files} deleted`,
      );
      fetchFileTree();
    } else {
      btnUpdateActive.textContent = `Error: ${data.error}`;
      showSyncToast(`Sync error: ${data.error}`);
    }
    setTimeout(() => {
      btnUpdateActive.textContent = "Sync Active Field";
    }, 3000);
  } catch (e) {
    btnUpdateActive.textContent = "Error!";
    showSyncToast(`Sync failed: ${e.message}`);
    setTimeout(() => {
      btnUpdateActive.textContent = "Sync Active Field";
    }, 3000);
  }
});

btnAddField.addEventListener("click", selectNewField);
btnWelcomeAdd.addEventListener("click", selectNewField);
btnAddSession.addEventListener("click", createNewSession);

if (btnClearSelection) {
  btnClearSelection.addEventListener("click", () => {
    selectedFiles.clear();
    if (lastTreeData) {
      renderFileTree(lastTreeData);
    }
  });
}

if (btnManageAgents) {
  btnManageAgents.addEventListener("click", () => {
    agentsModal.style.display = "flex";
    renderAgentsList();
  });
}
if (btnCloseAgents) {
  btnCloseAgents.addEventListener("click", () => {
    agentsModal.style.display = "none";
  });
}
if (btnClearAgentForm) {
  btnClearAgentForm.addEventListener("click", clearAgentForm);
}
if (btnSaveAgent) {
  btnSaveAgent.addEventListener("click", saveAgent);
}

initEventsWatcher();

function appendMessage(role, text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${role === "user" ? "user-message" : "system-message"}`;

  const content = document.createElement("div");
  content.className = "message-content";

  if (role === "system" && text === "") {
    msgDiv.appendChild(content);
    messagesContainer.appendChild(msgDiv);
    return content;
  }

  content.innerHTML = formatMarkdown(text);

  msgDiv.appendChild(content);
  messagesContainer.appendChild(msgDiv);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  return content;
}

async function fetchSessions() {
  if (!activeField) return;
  try {
    const res = await fetch("/api/sessions");
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
  sessionTabs.innerHTML = "";
  sessions.forEach((sess) => {
    const tab = document.createElement("div");
    tab.className = `session-tab ${sess.id === activeSessionId ? "active" : ""}`;
    tab.onclick = () => switchSession(sess.id);

    const nameSpan = document.createElement("span");
    nameSpan.className = "session-tab-name";
    nameSpan.textContent = sess.name;
    tab.appendChild(nameSpan);

    const closeBtn = document.createElement("span");
    closeBtn.className = "session-tab-close";
    closeBtn.innerHTML = "×";
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
    const res = await fetch("/api/sessions/set_active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
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
    const res = await fetch("/api/sessions/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: `Session ${sessions.length + 1}` }),
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
    const res = await fetch("/api/sessions/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
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
  messagesContainer.innerHTML = "";
  const currentSess = sessions.find((s) => s.id === activeSessionId);
  const chatInterfaceEl = document.getElementById("chat-interface");
  if (currentSess && currentSess.messages && currentSess.messages.length > 0) {
    if (chatInterfaceEl) chatInterfaceEl.classList.remove("empty-chat");
    currentSess.messages.forEach((msg) => {
      let contentText = "";
      if (msg.sources && msg.sources.length > 0) {
        contentText += `*Sources: ${msg.sources.join(", ")}*\n\n`;
      }
      contentText += msg.content;
      appendMessage(msg.role, contentText);
    });
  } else {
    if (chatInterfaceEl) chatInterfaceEl.classList.add("empty-chat");
  }
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

async function fetchFileTree() {
  if (!activeField) {
    fileExplorerContainer.style.display = "none";
    return;
  }
  try {
    const res = await fetch("/api/files/tree");
    const data = await res.json();
    if (data.error) {
      fileExplorerContainer.style.display = "none";
      return;
    }
    fileExplorerContainer.style.display = "flex";
    lastTreeData = data.tree;
    renderFileTree(data.tree);
  } catch (e) {
    console.error("Error fetching file tree:", e);
    fileExplorerContainer.style.display = "none";
  }
}

function renderFileTree(treeNodes) {
  fileTree.innerHTML = "";
  if (!treeNodes || treeNodes.length === 0) {
    fileTree.innerHTML =
      '<div style="color: var(--text-muted); padding: 8px;">Empty folder</div>';
    return;
  }
  treeNodes.forEach((node) => {
    fileTree.appendChild(createTreeNodeElement(node));
  });
}

function createTreeNodeElement(node) {
  const container = document.createElement("div");
  container.className = "tree-node";

  const row = document.createElement("div");
  row.className = "tree-node-row";

  // 1. Chevron or Space
  const chevronContainer = document.createElement("span");
  chevronContainer.className = "tree-chevron";
  if (node.type === "directory") {
    chevronContainer.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>`;
  } else {
    chevronContainer.style.visibility = "hidden";
  }
  row.appendChild(chevronContainer);

  // 2. Icon (moved up from step 3 since checkbox is removed)

  // 3. Icon
  const iconContainer = document.createElement("span");
  iconContainer.className = "tree-icon-container";
  if (node.type === "directory") {
    iconContainer.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>`;
  } else {
    iconContainer.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>`;
  }
  row.appendChild(iconContainer);

  // 4. Name
  const nameSpan = document.createElement("span");
  nameSpan.className = "node-name";
  nameSpan.textContent = node.name;
  nameSpan.title = node.path;
  row.appendChild(nameSpan);

  container.appendChild(row);

  if (node.type === "directory" && node.children) {
    const childrenContainer = document.createElement("div");
    childrenContainer.className = "tree-node-children";
    childrenContainer.style.display = "none";

    node.children.forEach((child) => {
      childrenContainer.appendChild(createTreeNodeElement(child));
    });
    container.appendChild(childrenContainer);

    row.onclick = () => {
      const isCollapsed = childrenContainer.style.display === "none";
      childrenContainer.style.display = isCollapsed ? "flex" : "none";
      chevronContainer.innerHTML = isCollapsed
        ? `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`
        : `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>`;
      iconContainer.innerHTML = isCollapsed
        ? `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>`
        : `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>`;
    };
  }

  return container;
}

function isNodeSelected(node) {
  if (node.type === "file") {
    return selectedFiles.has(node.path);
  }
  if (node.children && node.children.length > 0) {
    const allFiles = getAllChildFiles(node);
    return allFiles.length > 0 && allFiles.every((p) => selectedFiles.has(p));
  }
  return false;
}

function getAllChildFiles(node) {
  let files = [];
  if (node.type === "file") {
    files.push(node.path);
  } else if (node.children) {
    node.children.forEach((child) => {
      files = files.concat(getAllChildFiles(child));
    });
  }
  return files;
}

function toggleNodeSelection(node, isChecked) {
  const files = getAllChildFiles(node);
  files.forEach((p) => {
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
  const source = new EventSource("/api/events");
  source.onmessage = function (event) {
    const data = JSON.parse(event.data);
    if (data.type === "sync") {
      showSyncToast(data.message);
      fetchFileTree();
    } else if (data.type === "indexing_start") {
      indexingProgressContainer.style.display = "flex";
      progressBarLabel.textContent = data.message || "Indexing field...";
      setChatDisabled(true);
    } else if (data.type === "indexing_complete") {
      indexingProgressContainer.style.display = "none";
      setChatDisabled(false);
      showSyncToast(data.message);
      fetchFileTree();
      fetchFields();
    } else if (data.type === "indexing_error") {
      indexingProgressContainer.style.display = "none";
      setChatDisabled(false);
      showSyncToast(data.message);
    }
  };
  source.onerror = function () {
    source.close();
    setTimeout(initEventsWatcher, 5000);
  };
}

function showSyncToast(message) {
  const toast = document.createElement("div");
  toast.className = "sync-toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 5000);
}

function appendTyping() {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message system-message typing-msg`;
  msgDiv.innerHTML = `
    <div class="message-content">
      <div class="thinking-container">
        <div class="circle-grid">
          <div class="circle-dot"></div>
          <div class="circle-dot"></div>
          <div class="circle-dot"></div>
          <div class="circle-dot"></div>
          <div class="circle-dot"></div>
          <div class="circle-dot"></div>
          <div class="circle-dot"></div>
          <div class="circle-dot"></div>
          <div class="circle-dot"></div>
        </div>
        <div class="thinking-text">Thinking... <span>0.0s</span></div>
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
  const rawText = chatInput.value.trim();
  if (!rawText) return;

  // Capture voice input flag NOW before anything can reset it
  const triggeredByVoice = wasVoiceInput;
  wasVoiceInput = false; // Reset for next input

  // Extract agent mention from start of text
  let agentId = null;
  let text = rawText;
  const mentionMatch = text.match(/^@(\w+)\s+(.*)/s) || text.match(/^@(\w+)$/);
  if (mentionMatch) {
    const mentionedName = mentionMatch[1];
    const agent = allAgents.find(a => a.name.toLowerCase() === mentionedName.toLowerCase());
    if (agent) {
      agentId = agent.id;
      text = mentionMatch[2] ? mentionMatch[2].trim() : "";
    }
  }
  
  if (!text && !agentId) return; // empty

  chatInput.value = "";
  if (typeof adjustInputWidth === "function") adjustInputWidth();
  const chatInterfaceEl = document.getElementById("chat-interface");
  if (chatInterfaceEl) chatInterfaceEl.classList.remove("empty-chat");
  appendMessage("user", rawText);

  // Initialise streaming TTS state for this turn
  if (triggeredByVoice) {
    stopTTSQueue(); // clear any previous queue
    ttsActive = true;
  }

  // Buffer for accumulating tokens between sentence boundaries
  let ttsBuffer = "";
  // Track whether we're inside a code block (to skip code from TTS)
  let codeBlockDepth = 0;

  // Flush accumulated buffer up to the last sentence boundary
  function flushTTSBuffer(force = false) {
    if (!ttsBuffer.trim()) return;
    if (force) {
      const s = ttsBuffer.trim();
      ttsBuffer = "";
      if (s.length >= 5) enqueueTTSSentence(s);
      return;
    }
    // Find the last sentence-ending boundary: . ! ? followed by whitespace
    let lastBoundary = -1;
    for (let i = 0; i < ttsBuffer.length - 1; i++) {
      if (".!?".includes(ttsBuffer[i]) && /\s/.test(ttsBuffer[i + 1])) {
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
  const startTime = Date.now();
  let timerInterval = null;
  const timerTextEl = typingInd.querySelector(".thinking-text span");
  if (timerTextEl) {
    timerInterval = setInterval(() => {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      timerTextEl.textContent = elapsed + "s";
    }, 100);
  }

  try {
    const chatMode = chatModeCheckbox && chatModeCheckbox.checked ? "rag" : "llm";
    let url = `/api/chat?q=${encodeURIComponent(text)}&chat_mode=${chatMode}`;
    if (activeSessionId) url += `&session_id=${activeSessionId}`;
    if (agentId) url += `&agent_id=${agentId}`;
    
    if (selectedFiles.size > 0) {
      const filesParam = Array.from(selectedFiles).join(",");
      url += `&files=${encodeURIComponent(filesParam)}`;
    }
    const eventSource = new EventSource(url);

    let contentDiv = null;
    let fullText = "";

    eventSource.onmessage = async function (event) {
      const data = JSON.parse(event.data);

      if (data.type === "sources") {
        if (data.sources && data.sources.length > 0) {
          if (typingInd.parentNode) {
            typingInd.remove();
          }
          fullText += `*Sources: ${data.sources.join(", ")}*\n\n`;
          contentDiv = appendMessage("system", "");
          contentDiv.innerHTML = formatMarkdown(fullText);
          
          messagesContainer.appendChild(typingInd);
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
      } else if (data.type === "token") {
        if (typingInd.parentNode) {
          typingInd.remove();
          if (timerInterval) clearInterval(timerInterval);
        }
        if (!contentDiv) contentDiv = appendMessage("system", "");
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
      } else if (data.type === "error") {
        if (typingInd.parentNode) {
          typingInd.remove();
          if (timerInterval) clearInterval(timerInterval);
        }
        if (!contentDiv) contentDiv = appendMessage("system", "");
        fullText += `\n**Error:** ${data.text}`;
        contentDiv.innerHTML = formatMarkdown(fullText);
        eventSource.close();
      } else if (data.type === "done") {
        if (typingInd.parentNode) {
          typingInd.remove();
          if (timerInterval) clearInterval(timerInterval);
        }
        eventSource.close();
        await fetchSessions();
        // Flush any remaining text in the buffer as the last TTS chunk
        if (triggeredByVoice && ttsActive) {
          flushTTSBuffer(true);
        }
      }
    };

    eventSource.onerror = function () {
      if (typingInd.parentNode) {
        typingInd.remove();
        if (timerInterval) clearInterval(timerInterval);
      }
      eventSource.close();
    };
  } catch (e) {
    if (typingInd.parentNode) {
      typingInd.remove();
      if (timerInterval) clearInterval(timerInterval);
    }
    appendMessage("system", `**Connection Error:** ${e.message}`);
  }
}

btnSend.addEventListener("click", () => {
  wasVoiceInput = false;
  sendMessage();
});
chatInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
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
  if (!sentence) return "";
  let s = sentence;
  // Skip sources prefix
  s = s.replace(/^\*Sources:.*?\*[\s\n]*/gm, "");
  // Remove code blocks - replace with pause word
  s = s.replace(/```[\s\S]*?```/g, "");
  // Unwrap inline code
  s = s.replace(/`([^`]+)`/g, "$1");
  // Unwrap bold / italic
  s = s.replace(/\*{1,3}([^*]+)\*{1,3}/g, "$1");
  // Unwrap heading markers
  s = s.replace(/^#{1,6}\s+/gm, "");
  // Unwrap markdown links
  s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  // Collapse whitespace
  s = s.replace(/\s+/g, " ").trim();
  return s;
}

function playNextTTS() {
  if (isTTSPlaying || ttsQueue.length === 0) return;

  const { blob, url: blobUrl } = ttsQueue.shift();
  isTTSPlaying = true;
  currentAudio = new Audio(blobUrl);

  const container = document.querySelector(".app-container");
  if (container) {
    container.classList.remove("transcribing");
    container.classList.add("speaking");
  }

  const cleanup = () => {
    isTTSPlaying = false;
    try {
      URL.revokeObjectURL(blobUrl);
    } catch (e) {}
    currentAudio = null;
    if (ttsQueue.length === 0 && container) {
      container.classList.remove("speaking");
    }
    playNextTTS();
  };

  currentAudio.onended = cleanup;
  currentAudio.onerror = cleanup;
  currentAudio.play().catch((err) => {
    console.warn("TTS playback error:", err);
    cleanup();
  });
}

// Fire-and-forget: synthesize a sentence and push its blob into the queue.
// Multiple synthesis calls can run concurrently; playback stays sequential.
function enqueueTTSSentence(sentence) {
  const cleaned = cleanSentenceForTTS(sentence);
  if (!cleaned || cleaned.length < 8) return;

  fetch("/api/voice/synthesize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: cleaned, voice: "af_bella" }),
  })
    .then((res) => {
      if (!res.ok) throw new Error("TTS HTTP " + res.status);
      return res.blob();
    })
    .then((blob) => {
      if (!ttsActive) return; // response was cancelled
      const url = URL.createObjectURL(blob);
      ttsQueue.push({ blob, url });
      playNextTTS();
    })
    .catch((err) => console.warn("TTS synthesis failed:", err));
}

function stopTTSQueue() {
  ttsActive = false;
  ttsQueue = [];
  isTTSPlaying = false;
  if (currentAudio) {
    try {
      currentAudio.pause();
    } catch (e) {}
    currentAudio = null;
  }
  const container = document.querySelector(".app-container");
  if (container) container.classList.remove("speaking", "transcribing");
}

function initSpeechRecognition() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.warn("SpeechRecognition not supported in this browser.");
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onresult = (event) => {
    if (isSpeechCancelled) return;

    let interimTranscript = "";
    let finalTranscript = "";

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

  const container = document.querySelector(".app-container");
  container.classList.remove("speaking", "transcribing", "recording");
  container.classList.add("recording");
  btnMic.classList.add("active");
  btnMic.title = "Stop Recording";

  if (currentAudio) {
    try {
      currentAudio.pause();
    } catch (e) {}
    currentAudio = null;
    container.classList.remove("speaking");
  }

  if (!recognition) {
    initSpeechRecognition();
  }
  if (recognition) {
    try {
      recognition.start();
    } catch (e) {}
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
    } catch (e) {}
  }

  // Capture audio context sample rate before closing
  const sampleRate = audioContext ? audioContext.sampleRate || 44100 : 44100;

  if (processorNode) {
    processorNode.disconnect();
    sourceNode.disconnect();
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
  }
  if (audioContext) {
    audioContext.close();
  }

  isRecording = false;

  const container = document.querySelector(".app-container");
  container.classList.remove("recording");

  if (isSpeechCancelled) {
    btnMic.classList.remove("active", "processing");
    btnMic.title = "Voice Input";
    chatInput.value = "";
    return;
  }

  btnMic.classList.remove("active");
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

  container.classList.add("transcribing");
  btnMic.classList.add("processing");
  btnMic.title = "Transcribing...";

  let totalLength = audioChunks.reduce((acc, chunk) => acc + chunk.length, 0);
  let mergedBuffer = new Float32Array(totalLength);
  let offset = 0;
  for (let chunk of audioChunks) {
    mergedBuffer.set(chunk, offset);
    offset += chunk.length;
  }

  const wavBlob = exportWAV(mergedBuffer, sampleRate);

  fetch("/api/voice/transcribe", {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: wavBlob,
  })
    .then((res) => res.json())
    .then((data) => {
      container.classList.remove("transcribing");
      btnMic.classList.remove("processing");
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
    .catch((err) => {
      container.classList.remove("transcribing");
      btnMic.classList.remove("processing");
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

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + float32Array.length * 2, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, float32Array.length * 2, true);

  floatTo16BitPCM(view, 44, float32Array);

  return new Blob([view], { type: "audio/wav" });
}

function floatTo16BitPCM(output, offset, input) {
  for (let i = 0; i < input.length; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, input[i]));
    output.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
}

function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}

btnMic.addEventListener("click", async () => {
  if (isRecording) {
    stopRecordingAndSend(true);
  } else {
    await startRecording();
  }
});

// Event listeners to cancel speech input auto-send or stop playback on user interactions
chatInput.addEventListener("mousedown", handleUserInteraction);
chatInput.addEventListener("keydown", handleUserInteraction);
chatInput.addEventListener("focus", handleUserInteraction);

// Initial load
fetchFields();

// Settings Modal and Theme Toggle logic
const btnSettings = document.getElementById("btn-settings");
const settingsModal = document.getElementById("settings-modal");
const btnCloseSettings = document.getElementById("btn-close-settings");
const btnThemeLight = document.getElementById("btn-theme-light");
const btnThemeDark = document.getElementById("btn-theme-dark");

// Load stored theme or default to night (dark)
const savedTheme = localStorage.getItem("theme") || "dark";
applyTheme(savedTheme);

function applyTheme(theme) {
  if (theme === "light") {
    document.documentElement.classList.add("light-mode");
    btnThemeLight.classList.add("active");
    btnThemeDark.classList.remove("active");
  } else {
    document.documentElement.classList.remove("light-mode");
    btnThemeLight.classList.remove("active");
    btnThemeDark.classList.add("active");
  }
  localStorage.setItem("theme", theme);
}

if (btnSettings) {
  btnSettings.addEventListener("click", () => {
    settingsModal.style.display = "flex";
  });
}

if (btnCloseSettings) {
  btnCloseSettings.addEventListener("click", () => {
    settingsModal.style.display = "none";
  });
}

if (settingsModal) {
  settingsModal.addEventListener("click", (e) => {
    if (e.target === settingsModal) {
      settingsModal.style.display = "none";
    }
  });
}

if (btnThemeLight) {
  btnThemeLight.addEventListener("click", () => applyTheme("light"));
}
if (btnThemeDark) {
  btnThemeDark.addEventListener("click", () => applyTheme("dark"));
}

// --- Dynamic input width/height auto-growing ---
function adjustInputWidth() {
  const wrapper = document.querySelector(".input-wrapper");
  if (!wrapper || !chatInput) return;

  const charCount = chatInput.value.length;
  const availableWidth = Math.max(280, window.innerWidth - 48);
  const baseWidth = Math.min(600, availableWidth);
  const maxWidth = 900;
  const calculatedWidth = Math.min(
    maxWidth,
    availableWidth,
    Math.max(baseWidth, baseWidth + charCount * 6),
  );
  wrapper.style.width = `${calculatedWidth}px`;

  chatInput.style.height = "auto";
  chatInput.style.height = `${chatInput.scrollHeight}px`;
}

if (chatInput) {
  chatInput.addEventListener("input", adjustInputWidth);
  window.addEventListener("resize", adjustInputWidth);
  // Trigger initially to establish correct dimensions
  adjustInputWidth();
}

// --- Modern Web Directory Picker ---
let currentPickerPath = "";
const dirPickerModal = document.getElementById("dir-picker-modal");
const btnCloseDirPicker = document.getElementById("btn-close-dir-picker");
const btnDirUp = document.getElementById("btn-dir-up");
const dirCurrentPathInput = document.getElementById("dir-current-path-input");
const dirPickerList = document.getElementById("dir-picker-list");
const btnSelectDirConfirm = document.getElementById("btn-select-dir-confirm");

async function openDirPicker(startingPath = "") {
  if (dirPickerModal) {
    dirPickerModal.style.display = "flex";
    await loadDirPickerPath(startingPath);
  }
}

async function loadDirPickerPath(path) {
  try {
    let url = "/api/fs/list";
    if (path) {
      url += `?path=${encodeURIComponent(path)}`;
    }
    const res = await fetch(url);
    const data = await res.json();
    if (data.error) {
      alert(data.error);
      return;
    }
    currentPickerPath = data.current_path;
    if (dirCurrentPathInput) {
      dirCurrentPathInput.value = currentPickerPath;
    }

    if (dirPickerList) {
      dirPickerList.innerHTML = "";
      data.items.forEach((item) => {
        const div = document.createElement("div");
        div.className = `dir-item ${item.type === "file" ? "file-item-disabled" : ""}`;

        const iconSpan = document.createElement("span");
        iconSpan.className = "dir-item-icon";
        if (item.type === "directory") {
          iconSpan.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
          `;
        } else {
          iconSpan.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>
          `;
        }

        const nameSpan = document.createElement("span");
        nameSpan.textContent = item.name;

        div.appendChild(iconSpan);
        div.appendChild(nameSpan);

        if (item.type === "directory") {
          div.ondblclick = () => {
            loadDirPickerPath(item.path);
          };
          div.onclick = () => {
            document
              .querySelectorAll(".dir-item")
              .forEach((el) => el.classList.remove("selected"));
            div.classList.add("selected");
            currentPickerPath = item.path;
            if (dirCurrentPathInput) {
              dirCurrentPathInput.value = currentPickerPath;
            }
          };
        }

        dirPickerList.appendChild(div);
      });
    }

    if (btnDirUp) {
      if (data.parent_path) {
        btnDirUp.disabled = false;
        btnDirUp.style.opacity = "1";
        btnDirUp.onclick = () => loadDirPickerPath(data.parent_path);
      } else {
        btnDirUp.disabled = true;
        btnDirUp.style.opacity = "0.4";
      }
    }
  } catch (e) {
    console.error("Error loading directory path:", e);
  }
}

if (btnCloseDirPicker) {
  btnCloseDirPicker.addEventListener("click", () => {
    if (dirPickerModal) dirPickerModal.style.display = "none";
  });
}

if (dirPickerModal) {
  dirPickerModal.addEventListener("click", (e) => {
    if (e.target === dirPickerModal) {
      dirPickerModal.style.display = "none";
    }
  });
}

if (btnSelectDirConfirm) {
  btnSelectDirConfirm.addEventListener("click", async () => {
    if (!currentPickerPath) return;
    if (dirPickerModal) dirPickerModal.style.display = "none";

    setChatDisabled(true);
    if (indexingProgressContainer) {
      indexingProgressContainer.style.display = "flex";
      progressBarLabel.textContent = `Connecting to ${currentPickerPath.split("\\").pop().split("/").pop()}...`;
    }

    try {
      const addRes = await fetch("/api/fields/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: currentPickerPath }),
      });
      const addData = await addRes.json();
      if (!addData.error) {
        await fetchFields();
      } else {
        setChatDisabled(false);
        if (indexingProgressContainer)
          indexingProgressContainer.style.display = "none";
        alert(addData.error);
      }
    } catch (e) {
      console.error("Error adding directory field:", e);
      setChatDisabled(false);
      if (indexingProgressContainer)
        indexingProgressContainer.style.display = "none";
    }
  });
}

// ═══════════════════════════════════════════════════════════
// MODEL SWITCHER + COOKBOOK — Unified tabbed dropdown
// ═══════════════════════════════════════════════════════════

const ModelSwitcher = (() => {
  let currentModel = "";
  let modelsList = [];
  let isOpen = false;
  let highlightIndex = -1;
  let cookbookLoaded = false;
  let hwData = null;
  let recommendations = [];

  const pill = document.getElementById("model-switcher-pill");
  const nameSpan = document.getElementById("model-switcher-name");
  const dropdown = document.getElementById("model-switcher-dropdown");
  const searchInput = document.getElementById("model-search-input");
  const listContainer = document.getElementById("model-list");

  function init() {
    if (!pill) return;
    pill.setAttribute("aria-expanded", "false");
    if (dropdown) {
      dropdown.querySelectorAll(".ms-tab").forEach(tab => {
        tab.setAttribute("type", "button");
      });
    }
    fetchCurrentModel();

    pill.addEventListener("click", (e) => {
      e.stopPropagation();
      if (isOpen) close(); else open();
    });

    document.addEventListener("click", (e) => {
      if (isOpen && dropdown && !dropdown.contains(e.target) && !pill.contains(e.target)) {
        close();
      }
    });

    if (searchInput) {
      searchInput.addEventListener("input", () => renderFilteredList());
      searchInput.addEventListener("keydown", handleKeyboard);
    }

    // Tab switching
    if (dropdown) {
      dropdown.querySelectorAll(".ms-tab").forEach(tab => {
        tab.addEventListener("click", (e) => {
          e.stopPropagation();
          switchTab(tab.dataset.tab);
        });
      });
    }
  }

  function switchTab(tabName) {
    if (!dropdown) return;
    dropdown.querySelectorAll(".ms-tab").forEach(t => {
      const isActive = t.dataset.tab === tabName;
      t.classList.toggle("active", isActive);
      t.setAttribute("aria-selected", isActive ? "true" : "false");
      t.tabIndex = isActive ? 0 : -1;
    });
    const modelsPanel = document.getElementById("ms-panel-models");
    const cookbookPanel = document.getElementById("ms-panel-cookbook");
    if (modelsPanel) {
      const showModels = tabName === "models";
      modelsPanel.style.display = showModels ? "flex" : "none";
      modelsPanel.hidden = !showModels;
    }
    if (cookbookPanel) {
      const showCookbook = tabName === "cookbook";
      cookbookPanel.style.display = showCookbook ? "flex" : "none";
      cookbookPanel.hidden = !showCookbook;
    }

    if (tabName === "cookbook" && !cookbookLoaded) {
      cookbookLoaded = true;
      loadHardware();
    }
  }

  // ── Models tab ──

  async function fetchCurrentModel() {
    try {
      const res = await fetch("/api/config");
      const data = await res.json();
      currentModel = data.chat_model || "llama3";
      if (nameSpan) nameSpan.textContent = currentModel;
    } catch (e) {
      if (nameSpan) nameSpan.textContent = "offline";
    }
  }

  async function fetchModels() {
    setModelListState("Fetching models...");
    try {
      const res = await fetch("/api/models");
      const data = await res.json();
      if (data.error) {
        setModelListState(`Error: ${data.error}`, "error");
        return;
      }
      modelsList = data.models || [];
      currentModel = data.current_model || currentModel;
      if (nameSpan) nameSpan.textContent = currentModel;
      renderFilteredList();
    } catch (e) {
      setModelListState("Failed to connect", "error");
    }
  }

  function setModelListState(message, type = "") {
    if (!listContainer) return;
    listContainer.innerHTML = "";
    const state = document.createElement("div");
    state.className = `model-list-loading model-menu-state${type ? " " + type : ""}`;
    state.textContent = message;
    listContainer.appendChild(state);
  }

  function renderFilteredList() {
    if (!listContainer) return;
    const query = (searchInput ? searchInput.value : "").toLowerCase().trim();
    const filtered = query
      ? modelsList.filter(m => {
          const modelId = (m.model_id || "").toLowerCase();
          const family = (m.family || "").toLowerCase();
          const displayName = (m.display_name || "").toLowerCase();
          return modelId.includes(query) || family.includes(query) || displayName.includes(query);
        })
      : modelsList;

    highlightIndex = -1;
    if (filtered.length === 0) {
      setModelListState("No models found", "empty");
      return;
    }
    listContainer.innerHTML = "";
    filtered.forEach((m, idx) => {
      const item = document.createElement("div");
      item.className = "model-list-item" + (m.model_id === currentModel ? " active-model" : "");
      item.dataset.index = idx;
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", m.model_id === currentModel ? "true" : "false");
      item.tabIndex = -1;
      item.innerHTML = `
        ${m.model_id === currentModel ? '<span class="model-active-dot"></span>' : ""}
        <span class="model-list-item-name">${m.display_name || m.model_id}</span>
        <span class="model-list-item-meta">${m.parameter_size || ""} ${m.size_gb ? m.size_gb + "GB" : ""}</span>
      `;
      item.addEventListener("click", () => selectModel(m.model_id));
      listContainer.appendChild(item);
    });
  }

  async function selectModel(modelId) {
    if (modelId === currentModel) { close(); return; }
    if (nameSpan) nameSpan.textContent = modelId;
    currentModel = modelId;
    close();
    try {
      const res = await fetch("/api/config/model", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: modelId }),
      });
      const data = await res.json();
      if (data.error) {
        showSyncToast("Model switch failed: " + data.error);
      } else {
        showSyncToast("Switched to " + modelId);
      }
    } catch (e) {
      showSyncToast("Failed to switch model");
    }
    window.dispatchEvent(new CustomEvent("palimind:model-changed", { detail: { model: modelId } }));
  }

  function open() {
    if (!dropdown) return;
    isOpen = true;
    dropdown.style.display = "flex";
    dropdown.hidden = false;
    pill.classList.add("open");
    pill.setAttribute("aria-expanded", "true");
    switchTab("models");
    if (searchInput) { searchInput.value = ""; searchInput.focus(); }
    fetchModels();
  }

  function close() {
    if (!dropdown) return;
    isOpen = false;
    dropdown.style.display = "none";
    dropdown.hidden = true;
    pill.classList.remove("open");
    pill.setAttribute("aria-expanded", "false");
    highlightIndex = -1;
  }

  function handleKeyboard(e) {
    const items = listContainer ? listContainer.querySelectorAll(".model-list-item") : [];
    if (e.key === "Escape") { close(); return; }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      highlightIndex = Math.min(highlightIndex + 1, items.length - 1);
      updateHighlight(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      highlightIndex = Math.max(highlightIndex - 1, 0);
      updateHighlight(items);
    } else if (e.key === "Enter" && highlightIndex >= 0 && highlightIndex < items.length) {
      e.preventDefault();
      items[highlightIndex].click();
    }
  }

  function updateHighlight(items) {
    items.forEach((item, i) => {
      item.classList.toggle("keyboard-highlight", i === highlightIndex);
    });
    if (items[highlightIndex]) {
      items[highlightIndex].scrollIntoView({ block: "nearest" });
    }
  }

  // ── Cookbook tab ──

  async function loadHardware() {
    const hwCard = document.getElementById("hw-card");
    setCookbookState(hwCard, "Detecting hardware...");
    try {
      const res = await fetch("/api/cookbook/hardware");
      hwData = await res.json();
      if (hwData.error) {
        setCookbookState(hwCard, `Error: ${hwData.error}`, "error");
        return;
      }
      renderHardware();
      loadRecommendations();
    } catch (e) {
      setCookbookState(hwCard, "Hardware detection failed", "error");
    }
  }

  function setCookbookState(container, message, type = "") {
    if (!container) return;
    container.innerHTML = "";
    const state = document.createElement("span");
    state.className = `model-menu-state${type ? " " + type : ""}`;
    state.textContent = message;
    container.appendChild(state);
  }

  function renderHardware() {
    const hwCard = document.getElementById("hw-card");
    if (!hwCard || !hwData) return;
    const gpuLines = hwData.gpus && hwData.gpus.length > 0
      ? hwData.gpus.map(g => `<span class="hw-gpu-name">${g.name}</span><span>VRAM: <span class="hw-vram">${(g.vram_mb / 1024).toFixed(1)} GB</span></span>`).join("")
      : '<span class="hw-gpu-name">No GPU detected (CPU only)</span>';
    const ramGB = hwData.total_ram_mb ? (hwData.total_ram_mb / 1024).toFixed(0) : "?";
    const engines = hwData.serve_engines_available && hwData.serve_engines_available.length > 0
      ? hwData.serve_engines_available.join(", ") : "none";
    hwCard.innerHTML = `${gpuLines}<span>RAM: ${ramGB} GB · ${hwData.os_platform || "?"}</span><span>Engines: ${engines}</span>`;
  }

  async function loadRecommendations() {
    const recGrid = document.getElementById("rec-grid");
    if (!recGrid) return;
    setRecommendationState("Loading...");
    try {
      const res = await fetch("/api/cookbook/recommendations?top=10");
      const data = await res.json();
      recommendations = data.recommendations || [];
      renderRecommendations();
    } catch (e) {
      setRecommendationState("Failed to load", "error");
    }
  }

  function setRecommendationState(message, type = "") {
    const recGrid = document.getElementById("rec-grid");
    if (!recGrid) return;
    recGrid.innerHTML = "";
    const state = document.createElement("div");
    state.className = `model-menu-state${type ? " " + type : ""}`;
    state.textContent = message;
    recGrid.appendChild(state);
  }

  function renderRecommendations() {
    const recGrid = document.getElementById("rec-grid");
    if (!recGrid) return;
    if (recommendations.length === 0) {
      setRecommendationState("No recommendations", "empty");
      return;
    }
    recGrid.innerHTML = "";
    recommendations.forEach(rec => {
      const fitClass = rec.fit === "FITS_PERFECTLY" ? "fits" : rec.fit === "FITS_TIGHT" ? "tight" : rec.fit === "CPU_FALLBACK" ? "cpu" : "too-large";
      const fitLabel = rec.fit === "FITS_PERFECTLY" ? "FITS" : rec.fit === "FITS_TIGHT" ? "TIGHT" : rec.fit === "CPU_FALLBACK" ? "CPU" : "TOO BIG";
      const card = document.createElement("div");
      card.className = "rec-card";
      card.innerHTML = `<span class="rec-card-name">${rec.name}</span><span class="rec-card-size">${rec.params_b}B · ${rec.file_size_gb}GB</span><span class="fit-badge ${fitClass}">${fitLabel}</span>`;
      recGrid.appendChild(card);
    });
  }

  return { init, fetchCurrentModel };
})();

ModelSwitcher.init();

// --- Mentions & Agents Logic ---

async function fetchAgents() {
  try {
    const res = await fetch("/api/agents");
    const data = await res.json();
    allAgents = data.agents || [];
  } catch (e) {
    console.error("Error fetching agents:", e);
  }
}

function renderAgentsList() {
  agentsList.innerHTML = "";
  allAgents.forEach(agent => {
    const li = document.createElement("li");
    li.className = "agent-list-item";
    
    const info = document.createElement("div");
    info.className = "agent-list-info";
    const name = document.createElement("span");
    name.className = "agent-list-name";
    name.textContent = agent.name;
    const desc = document.createElement("span");
    desc.className = "agent-list-desc";
    desc.textContent = agent.description;
    info.appendChild(name);
    info.appendChild(desc);
    
    const actions = document.createElement("div");
    actions.className = "agent-list-actions";
    
    if (!agent.is_default) {
      const btnEdit = document.createElement("button");
      btnEdit.className = "action-btn";
      btnEdit.textContent = "Edit";
      btnEdit.onclick = () => {
        agentIdInput.value = agent.id;
        agentNameInput.value = agent.name;
        agentDescInput.value = agent.description;
        agentPromptInput.value = agent.system_prompt;
        document.getElementById("agent-form-title").textContent = "Edit Agent";
      };
      
      const btnDel = document.createElement("button");
      btnDel.className = "field-del-btn";
      btnDel.textContent = "×";
      btnDel.style.opacity = "1";
      btnDel.onclick = () => deleteAgent(agent.id);
      
      actions.appendChild(btnEdit);
      actions.appendChild(btnDel);
    } else {
      const span = document.createElement("span");
      span.style.fontSize = "0.75rem";
      span.style.color = "var(--text-muted)";
      span.textContent = "Default";
      actions.appendChild(span);
    }
    
    li.appendChild(info);
    li.appendChild(actions);
    agentsList.appendChild(li);
  });
}

function clearAgentForm() {
  agentIdInput.value = "";
  agentNameInput.value = "";
  agentDescInput.value = "";
  agentPromptInput.value = "";
  document.getElementById("agent-form-title").textContent = "Create New Agent";
}

async function saveAgent() {
  const id = agentIdInput.value;
  const name = agentNameInput.value.trim();
  const desc = agentDescInput.value.trim();
  const prompt = agentPromptInput.value.trim();
  if (!name) return alert("Name is required");
  
  const endpoint = id ? "/api/agents/edit" : "/api/agents/new";
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, name, description: desc, system_prompt: prompt })
    });
    const data = await res.json();
    if (!data.error) {
      await fetchAgents();
      renderAgentsList();
      clearAgentForm();
    } else {
      alert(data.error);
    }
  } catch (e) {
    console.error("Error saving agent:", e);
  }
}

async function deleteAgent(id) {
  if (!confirm("Are you sure you want to delete this agent?")) return;
  try {
    const res = await fetch("/api/agents/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id })
    });
    const data = await res.json();
    if (!data.error) {
      await fetchAgents();
      renderAgentsList();
    }
  } catch (e) {
    console.error("Error deleting agent:", e);
  }
}

let activeMentionIndex = 0;
let filteredAgents = [];

if (chatInput) {
  chatInput.addEventListener("input", (e) => {
    const val = chatInput.value;
    const cursor = chatInput.selectionStart;
    const textBeforeCursor = val.slice(0, cursor);
    const match = textBeforeCursor.match(/(?:^|\s)@(\w*)$/);
    if (match) {
      const query = match[1].toLowerCase();
      filteredAgents = allAgents.filter(a => a.name.toLowerCase().includes(query));
      if (filteredAgents.length > 0) {
        showMentionsPopup();
      } else {
        hideMentionsPopup();
      }
    } else {
      hideMentionsPopup();
    }
  });
  
  chatInput.addEventListener("keydown", (e) => {
    if (mentionsPopup.style.display === "block") {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeMentionIndex = (activeMentionIndex + 1) % filteredAgents.length;
        renderMentionsPopup();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeMentionIndex = (activeMentionIndex - 1 + filteredAgents.length) % filteredAgents.length;
        renderMentionsPopup();
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        selectAgentMention(filteredAgents[activeMentionIndex]);
      } else if (e.key === "Escape") {
        hideMentionsPopup();
      }
    }
  });
}

function showMentionsPopup() {
  mentionsPopup.style.display = "block";
  activeMentionIndex = 0;
  renderMentionsPopup();
}

function hideMentionsPopup() {
  mentionsPopup.style.display = "none";
}

function renderMentionsPopup() {
  mentionsPopup.innerHTML = "";
  filteredAgents.forEach((agent, i) => {
    const div = document.createElement("div");
    div.className = `mention-item ${i === activeMentionIndex ? "active" : ""}`;
    
    const name = document.createElement("span");
    name.className = "mention-item-name";
    name.textContent = "@" + agent.name;
    
    const desc = document.createElement("span");
    desc.className = "mention-item-desc";
    desc.textContent = agent.description;
    
    div.appendChild(name);
    div.appendChild(desc);
    
    div.onmousedown = (e) => {
      e.preventDefault();
      selectAgentMention(agent);
    };
    
    mentionsPopup.appendChild(div);
  });
}

function selectAgentMention(agent) {
  const val = chatInput.value;
  const newValue = val.replace(/(?:^|\s)@\w*$/, " @" + agent.name + " ");
  chatInput.value = newValue;
  chatInput.focus();
  hideMentionsPopup();
}
