async function getSettings() {
  return chrome.storage.sync.get({
    baseUrl: "http://127.0.0.1:8000",
    token: "",
  });
}

async function save(url, title) {
  const { baseUrl, token } = await getSettings();
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/capture/link`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ url, title }),
  });
  return response.json();
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "palimind-save-page",
    title: "Save page to PaliMind",
    contexts: ["page", "link"],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== "palimind-save-page") return;
  save(info.linkUrl || tab.url, tab.title || "").catch(() => {});
});
