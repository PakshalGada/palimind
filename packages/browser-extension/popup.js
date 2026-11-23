const baseInput = document.getElementById("base");
const tokenInput = document.getElementById("token");
const statusEl = document.getElementById("status");

chrome.storage.sync.get({ baseUrl: "http://127.0.0.1:8000", token: "" }, (settings) => {
  baseInput.value = settings.baseUrl;
  tokenInput.value = settings.token;
});

function settings() {
  return {
    baseUrl: baseInput.value.trim().replace(/\/$/, ""),
    token: tokenInput.value.trim(),
  };
}

document.getElementById("save-settings").addEventListener("click", () => {
  chrome.storage.sync.set(settings());
  statusEl.textContent = "Connection settings saved.";
  statusEl.className = "ok";
});

document.getElementById("save").addEventListener("click", async () => {
  const config = settings();
  statusEl.textContent = "Saving…";
  statusEl.className = "";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const response = await fetch(`${config.baseUrl}/api/capture/link`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(config.token ? { Authorization: `Bearer ${config.token}` } : {}),
      },
      body: JSON.stringify({ url: tab.url, title: tab.title || "" }),
    });
    const data = await response.json();
    if (data.error) {
      statusEl.textContent = data.error;
      statusEl.className = "err";
      return;
    }
    statusEl.textContent = "Saved. PaliMind is indexing it.";
    statusEl.className = "ok";
  } catch (error) {
    statusEl.textContent = String(error);
    statusEl.className = "err";
  }
});
