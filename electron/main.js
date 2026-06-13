const { app, BrowserWindow, globalShortcut } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const http = require('http');
const os = require('os');
const fs = require('fs');

// Global references to prevent JavaScript garbage collection from discarding active objects
let mainWindow = null;
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
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: true,
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
// Application Lifecycle State Machine
// ==========================================

// Electron waits for initialization to complete
app.whenReady().then(async () => {
    // 1. Electron main process starts FastAPI
    startPythonBackend();

    // 2. Electron waits until the server responds
    await waitForServer();

    // 3. Electron opens a BrowserWindow
    createWindow();

    // macOS specific recreation behavior (handling dock clicks)
    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });

    // 4. Register global hotkey for toggling the window
    const hotkey = process.platform === 'darwin' ? 'Command+Shift+Space' : 'Ctrl+Shift+Space';
    const ret = globalShortcut.register(hotkey, () => {
        toggleMainWindow();
    });

    if (!ret) {
        console.error(`[Hotkey Error] Failed to register global shortcut: ${hotkey}`);
    } else {
        console.log(`[Hotkey] Successfully registered global shortcut: ${hotkey}`);
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
