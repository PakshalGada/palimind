const { app, BrowserWindow, globalShortcut, ipcMain, desktopCapturer, session, screen } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const http = require('http');
const os = require('os');
const fs = require('fs');

// Global references to prevent JavaScript garbage collection from discarding active objects
let mainWindow   = null;
let glanceWindow = null;  // PaliGlance hotkey popup
let pythonProcess = null;

// Configuration Parameters
const PORT = 8000;
const SERVER_URL = `http://127.0.0.1:${PORT}`;
const PYTHON_SCRIPT = path.join(__dirname, '..', 'core', 'api_server.py');

/**
 * Discovers the correct Python interpreter path.
 * Prioritizes localized virtual environments (.venv, venv) over global system installations.
 */
function getPythonCommand() {
    const rootDir = path.join(__dirname, '..');
    
    // Cross-platform virtual environment resolution paths
    const venvPaths = [
        path.join(rootDir, '.venv', 'Scripts', 'python.exe'),
        path.join(rootDir, '.venv', 'bin', 'python'),
        path.join(rootDir, 'venv', 'Scripts', 'python.exe'),
        path.join(rootDir, 'venv', 'bin', 'python')
    ];

    for (const venvPath of venvPaths) {
        if (fs.existsSync(venvPath)) {
            console.log(` Active virtual environment detected at: ${venvPath}`);
            return venvPath;
        }
    }

    // Fallback heuristics if no localized environment is explicitly found
    console.warn(' No local virtual environment found. Defaulting to global interpreter.');
    return os.platform() === 'win32' ? 'python' : 'python3';
}

/**
 * Spawns the FastAPI application as a detached child process using spawn().
 */
function startPythonBackend() {
    const pythonCmd = getPythonCommand();
    
    console.log(` Initiating FastAPI server via: ${pythonCmd} -m core.api_server`);
    
    // Spawn is utilized over exec to stream IO and capture a definitive PID for clean shutdown
    pythonProcess = spawn(pythonCmd, ['-m', 'core.api_server'], {
        cwd: path.join(__dirname, '..'), // Execute from project root directory
        detached: false // Keep attached to process group for reliable lifecycle synchronization
    });

    // Stream standard output for debugging
    pythonProcess.stdout.on('data', (data) => {
        console.log(`[FastAPI]: ${data.toString().trim()}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        console.error(`[FastAPI]: ${data.toString().trim()}`);
    });

    pythonProcess.on('close', (code) => {
        console.log(` Process terminated with exit code ${code}`);
        pythonProcess = null;
    });
}

/**
 * Cleanly kills the FastAPI process tree.
 * Crucial for Windows where standard kill signals fail to terminate Uvicorn worker threads.
 */
function killPythonProcess() {
    if (!pythonProcess) return;

    const pid = pythonProcess.pid;
    console.log(` Initiating clean shutdown of process tree: PID ${pid}`);

    try {
        if (os.platform() === 'win32') {
            // taskkill /T (Tree kill) /F (Force) ensures all child Uvicorn threads die cleanly
            execSync(`taskkill /pid ${pid} /T /F`);
        } else {
            // On POSIX, a standard SIGKILL ensures no graceful delay blocks the Electron exit
            process.kill(pid, 'SIGKILL');
        }
    } catch (err) {
        console.warn(` Process termination warning: ${err.message}`);
    }
    
    pythonProcess = null;
}

/**
 * Waits for the backend to be healthy before creating the window.
 * Polls the localhost port utilizing the native Node.js HTTP module.
 */
function waitForServer() {
    return new Promise((resolve) => {
        console.log(` Waiting for FastAPI to be ready at ${SERVER_URL}...`);
        const checkServer = () => {
            // HTTP GET request to check if the server is actively responding
            const req = http.get(SERVER_URL, (res) => {
                // If any response is received (even 404), the ASGI server is bound and active
                console.log(`\n Server responded (Status: ${res.statusCode}). Proceeding.`);
                resolve();
            });

            req.on('error', (err) => {
                process.stdout.write('.');
                // ECONNREFUSED implies the FastAPI server is still booting
                setTimeout(checkServer, 200); // Retry polling every 200ms
            });

            req.end(); // Close the request payload
        };

        checkServer();
    });
}

/**
 * Creates the browser window and shows the frontend UI.
 */
function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1280,
        height: 800,
        autoHideMenuBar: true,
        webPreferences: {
            // Sane security defaults strictly enforced
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: false,
            webSecurity: true
        }
    });

    // BrowserWindow loads the app UI from localhost
    mainWindow.loadURL(SERVER_URL + '/ui');

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

/**
 * Creates the PaliGlance floating popup window.
 * Created once at startup, then shown/hidden by hotkey.
 * frame:false + transparent gives us a clean frameless overlay.
 */
function createGlanceWindow() {
    glanceWindow = new BrowserWindow({
        width: 580,
        height: 420,
        minWidth: 400,
        minHeight: 300,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        skipTaskbar: true,
        resizable: true,
        show: false,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: false,
            webSecurity: true,
        },
    });

    glanceWindow.loadURL(SERVER_URL + '/ui/glance');

    // Hide instead of close so next hotkey press re-shows instantly
    glanceWindow.on('close', (e) => {
        e.preventDefault();
        glanceWindow.hide();
    });
}

/**
 * Toggles the PaliGlance popup.
 * Key behavior: capture screenshot BEFORE showing the window so we
 * capture what the user was actually looking at, not our own UI.
 */
async function toggleGlanceWindow() {
    if (!glanceWindow) return;

    if (glanceWindow.isVisible()) {
        glanceWindow.hide();
        return;
    }

    // Step 1: Capture screenshot before the popup appears
    let screenshotDataUrl = null;
    try {
        if (process.platform === 'linux' && (process.env.XDG_SESSION_TYPE === 'wayland' || process.env.HYPRLAND_INSTANCE_SIGNATURE)) {
            const os = require('os');
            const fs = require('fs');
            const tempPath = path.join(os.tmpdir(), `paliglance_${Date.now()}.png`);
            try {
                execSync(`grim "${tempPath}"`);
                const imgData = fs.readFileSync(tempPath);
                screenshotDataUrl = `data:image/png;base64,${imgData.toString('base64')}`;
                fs.unlinkSync(tempPath);
            } catch (waylandErr) {
                console.error('[PaliGlance] grim capture failed:', waylandErr);
            }
        }
        
        if (!screenshotDataUrl) {
            const sources = await desktopCapturer.getSources({
                types: ['screen'],
                thumbnailSize: { width: 1920, height: 1080 },
            });
            if (sources && sources.length > 0) {
                const raw = sources[0].thumbnail.toDataURL();
                if (raw && raw.startsWith('data:image')) {
                    screenshotDataUrl = raw;
                }
            }
        }
    } catch (err) {
        console.error('[PaliGlance] Screenshot capture error:', err);
    }

    // Step 2: Center window in upper-third of primary display
    const primaryDisplay = screen.getPrimaryDisplay();
    const { width, height } = primaryDisplay.workAreaSize;
    const winW = 580;
    const winH = 420;
    glanceWindow.setSize(winW, winH);
    glanceWindow.setPosition(
        Math.round((width - winW) / 2),
        Math.round((height - winH) / 3)
    );

    // Step 3: Show window and signal the renderer to reset its UI
    glanceWindow.show();
    glanceWindow.focus();
    glanceWindow.webContents.send('glance:shown');

    // Step 4: Send screenshot to renderer (may arrive slightly after 'shown')
    if (screenshotDataUrl) {
        glanceWindow.webContents.send('glance:screenshot', screenshotDataUrl);
    }
}

/**
 * Toggles the main window visibility and focus state.
 * If hidden -> show and focus.
 * If minimized -> restore and focus.
 * If visible but not focused -> bring to front and focus.
 * If visible and focused -> hide.
 */
function toggleMainWindow() {
    if (!mainWindow) return;

    if (mainWindow.isMinimized()) {
        mainWindow.restore();
        mainWindow.focus();
    } else if (!mainWindow.isVisible()) {
        mainWindow.show();
        mainWindow.focus();
    } else if (!mainWindow.isFocused()) {
        mainWindow.show();
        mainWindow.focus();
    } else {
        mainWindow.hide();
    }
}

// ==========================================
// Wayland-Compatible PaliGlance SSE Trigger
// ==========================================

/**
 * Subscribes to the FastAPI /api/events SSE stream to listen for 'glance_open' events.
 * This is the Wayland-native approach: instead of relying on Electron globalShortcuts
 * (which are unreliable on Hyprland/Wayland), a Hyprland bind fires:
 *   curl -s -X POST http://127.0.0.1:8000/api/glance/open
 * FastAPI broadcasts a 'glance_open' SSE event, and Electron reacts here.
 * Auto-reconnects on disconnect with a 2-second delay.
 */
function subscribeToGlanceEvents() {
    const tryConnect = () => {
        const req = http.get(`${SERVER_URL}/api/events`, (res) => {
            console.log('[GlanceSSE] Connected to event stream.');
            let buffer = '';

            res.on('data', (chunk) => {
                buffer += chunk.toString();
                // SSE messages end with double newline
                const messages = buffer.split('\n\n');
                buffer = messages.pop(); // Keep incomplete message in buffer

                for (const msg of messages) {
                    const dataLine = msg.split('\n').find(l => l.startsWith('data: '));
                    if (!dataLine) continue;
                    try {
                        const event = JSON.parse(dataLine.slice(6));
                        if (event.type === 'glance_open') {
                            console.log('[GlanceSSE] Received glance_open event — toggling PaliGlance.');
                            toggleGlanceWindow();
                        }
                    } catch (e) {
                        // Ignore malformed SSE data lines
                    }
                }
            });

            res.on('end', () => {
                console.warn('[GlanceSSE] Stream ended. Reconnecting in 2s...');
                setTimeout(tryConnect, 2000);
            });

            res.on('error', (err) => {
                console.error('[GlanceSSE] Stream error:', err.message, '— Reconnecting in 2s...');
                setTimeout(tryConnect, 2000);
            });
        });

        req.on('error', (err) => {
            // Server not yet up or connection refused — retry silently
            setTimeout(tryConnect, 2000);
        });

        // Don't time out — we want a persistent connection
        req.setTimeout(0);
    };

    tryConnect();
}



// Electron waits for initialization to complete
app.whenReady().then(async () => {
    // 1. Electron main process starts FastAPI
    startPythonBackend();

    // 2. Electron waits until the server responds
    await waitForServer();

    // 3. Electron opens a BrowserWindow
    createWindow();

    // 4. Grant media (screen capture) permissions to pages loaded from localhost.
    //    Without this, getUserMedia with chromeMediaSource:'desktop' silently fails.
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
        if (permission === 'media') {
            callback(true);  // Allow screen capture from our trusted localhost page
        } else {
            callback(false); // Deny everything else
        }
    });



    // 6. IPC handler: hide the PaliGlance window (called from glance.js on Escape)
    ipcMain.handle('glance:hide', () => {
        if (glanceWindow) glanceWindow.hide();
    });

    ipcMain.handle('glance:open', async () => {
        await toggleGlanceWindow();
    });

    // 7. Create the PaliGlance popup window (hidden, kept alive for instant re-show)
    createGlanceWindow();

    // 8. Subscribe to FastAPI SSE stream for Wayland-compatible glance_open trigger.
    //    Hyprland keybinds can't reliably use Electron globalShortcuts on Wayland,
    //    so we instead fire: curl -s -X POST http://127.0.0.1:8000/api/glance/open
    //    from a Hyprland bind, and Electron reacts to the SSE event here.
    subscribeToGlanceEvents();


    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });

    // ── Platform detection ────────────────────────────────────────────────────
    // Linux Ctrl+Shift combos are frequently intercepted by GNOME, KDE, and
    // other desktop environments (and some Wayland compositors) before Electron
    // ever sees them.  Super+Shift is not reserved by any common DE and works
    // reliably on both X11 and Wayland sessions.
    const isMac   = process.platform === 'darwin';
    const isLinux = process.platform === 'linux';

    console.log('[Hotkey] Platform:', process.platform);
    console.log('[Hotkey] Session type (XDG_SESSION_TYPE):', process.env.XDG_SESSION_TYPE || 'n/a');

    function getAccelerator(mac, linux, win) {
        if (isMac)   return mac;
        if (isLinux) return linux;
        return win;
    }

    // Register hotkey: toggle main window
    const mainHotkey = getAccelerator('Command+Shift+Space', 'Super+Shift+Space', 'Ctrl+Shift+Space');
    const retMain = globalShortcut.register(mainHotkey, () => {
        toggleMainWindow();
    });
    if (!retMain) {
        console.error(`[Hotkey Error] Failed to register global shortcut: ${mainHotkey}`);
    } else {
        console.log(`[Hotkey] Registered: ${mainHotkey} → toggle main window`);
    }

    // Register hotkey: PaliGlance vision popup
    const glanceHotkey = getAccelerator('Command+Shift+V', 'Super+Shift+V', 'Ctrl+Shift+V');
    const retGlance = globalShortcut.register(glanceHotkey, () => {
        toggleGlanceWindow();
    });
    if (!retGlance) {
        console.error(`[Hotkey Error] Failed to register global shortcut: ${glanceHotkey}`);
    } else {
        console.log(`[Hotkey] Registered: ${glanceHotkey} → PaliGlance popup`);
    }

    // Register hotkey: open main window and switch to Email mode
    const emailHotkey = getAccelerator('Command+Shift+E', 'Super+Shift+E', 'Ctrl+Shift+E');
    const retEmail = globalShortcut.register(emailHotkey, () => {
        if (!mainWindow) return;
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
        // Tell the renderer to switch to email mode
        mainWindow.webContents.send('switch-mode', 'email');
    });
    if (!retEmail) {
        console.error(`[Hotkey Error] Failed to register global shortcut: ${emailHotkey}`);
    } else {
        console.log(`[Hotkey] Registered: ${emailHotkey} → Email mode`);
    }
});

// Shutdown flow: Electron closes
app.on('window-all-closed', () => {
    // Electron kills the FastAPI process cleanly
    killPythonProcess();
    
    // App exits (except on macOS, adhering to native UX guidelines)
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

// Failsafe termination hook for abrupt exits (e.g., Cmd+Q on macOS)
app.on('before-quit', () => {
    killPythonProcess();
});

// Unregister all shortcuts before quitting
app.on('will-quit', () => {
    globalShortcut.unregisterAll();
});
