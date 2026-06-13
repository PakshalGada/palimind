'use strict';

const { contextBridge, ipcRenderer } = require('electron');


// ── PaliGlance popup bridge ───────────────────────────────────────────────────
// Exposed as window.glanceAPI inside glance.html
contextBridge.exposeInMainWorld('glanceAPI', {
  // Hide the popup window (called on Escape)
  hide: () => ipcRenderer.invoke('glance:hide'),
  // Register a callback for when the main process sends a screenshot
  onScreenshot: (callback) =>
    ipcRenderer.on('glance:screenshot', (_event, dataUrl) => callback(dataUrl)),
  // Register a callback for when the window is re-shown (to reset UI)
  onWindowShown: (callback) =>
    ipcRenderer.on('glance:shown', () => callback()),
});

// ── Main window bridge ────────────────────────────────────────────────────────
// Exposed as window.electronBridge inside the main index.html / app.js
// Used by Ctrl+Shift+E to drive the main window to a specific mode.
contextBridge.exposeInMainWorld('electronBridge', {
  onSwitchMode: (callback) =>
    ipcRenderer.on('switch-mode', (_event, mode) => callback(mode)),
  openGlance: () => ipcRenderer.invoke('glance:open'),
});
