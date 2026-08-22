// Palimind — Tauri 2 Main Process
//
// Responsibilities:
//  1. Spawn the FastAPI / Uvicorn backend as a child process
//  2. Poll the backend until it's ready
//  3. Open the main WebView window pointing at http://127.0.0.1:8000/ui
//  4. Register global shortcuts (platform-aware):
//       Ctrl/Cmd/Super+Shift+Space  → toggle main window (PaliSpace)
//       Ctrl/Cmd/Super+Shift+V      → open PaliGlance (screen capture popup)
//  5. Clean up the backend on app exit

use std::fs::File;
use std::io::Cursor;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use std::thread;
use std::path::PathBuf;

use base64::{engine::general_purpose::STANDARD as B64, Engine};
use xcap::image::{DynamicImage, ImageFormat};
use xcap::Monitor;

use tauri::{
    AppHandle, Manager, Emitter, WebviewUrl, WebviewWindowBuilder,
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

const GLANCE_URL: &str = "http://127.0.0.1:8000/ui/glance";

// ── Python backend process holder ────────────────────────────────────────────

struct BackendProcess(Option<Child>);

impl Drop for BackendProcess {
    fn drop(&mut self) {
        if let Some(mut child) = self.0.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

// ── Python interpreter discovery ─────────────────────────────────────────────

fn find_python(project_root: &PathBuf) -> String {
    let candidates = [
        project_root.join(".venv").join("bin").join("python"),
        project_root.join("venv").join("bin").join("python"),
        project_root.join(".venv").join("Scripts").join("python.exe"),
        project_root.join("venv").join("Scripts").join("python.exe"),
    ];
    for p in &candidates {
        if p.exists() {
            return p.to_string_lossy().into_owned();
        }
    }
    // Fallback to system python3
    "python3".to_string()
}

// ── Backend health-check polling ─────────────────────────────────────────────

fn wait_for_backend(url: &str, max_attempts: u32) -> bool {
    for _ in 0..max_attempts {
        if let Ok(resp) = ureq::get(url).call() {
            let status = resp.status();
            if status < 500 {
                return true;
            }
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

// ── Screen capture ───────────────────────────────────────────────────────────

fn capture_screen_b64() -> Option<String> {
    let monitors = Monitor::all().ok()?;
    let monitor = monitors.into_iter().next()?;
    let image = monitor.capture_image().ok()?;
    let mut buf = Cursor::new(Vec::new());
    DynamicImage::ImageRgba8(image)
        .write_to(&mut buf, ImageFormat::Png)
        .ok()?;
    Some(B64.encode(buf.into_inner()))
}

// ── PaliGlance popup window ──────────────────────────────────────────────────

fn ensure_glance_window(app: &AppHandle) -> Option<tauri::WebviewWindow> {
    if let Some(win) = app.get_webview_window("glance") {
        return Some(win);
    }
    WebviewWindowBuilder::new(app, "glance", WebviewUrl::External(GLANCE_URL.parse().unwrap()))
        .title("PaliGlance")
        .inner_size(580.0, 420.0)
        .min_inner_size(400.0, 300.0)
        .resizable(true)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .visible(false)
        .build()
        .ok()
}

/// Capture the screen (before showing) then reveal the popup and hand it the
/// screenshot via events. Mirrors the Electron flow so the popup never captures
/// itself.
fn open_glance(app: &AppHandle) {
    let Some(win) = ensure_glance_window(app) else { return };

    if win.is_visible().unwrap_or(false) {
        let _ = win.hide();
        return;
    }

    // Window is hidden — give the compositor a beat, then capture.
    thread::sleep(Duration::from_millis(120));
    let screenshot = capture_screen_b64();

    let _ = win.show();
    let _ = win.set_focus();
    let _ = win.emit("glance:shown", ());
    if let Some(b64) = screenshot {
        let _ = win.emit("glance:screenshot", b64);
    }
}

#[tauri::command]
fn open_glance_cmd(app: AppHandle) {
    open_glance(&app);
}

// ── App entry-point ──────────────────────────────────────────────────────────

fn main() {
    // Determine project root (parent of src-tauri/)
    let project_root = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));

    // Walk up until we find pyproject.toml to locate actual project root
    let mut root = project_root.clone();
    for _ in 0..6 {
        if root.join("pyproject.toml").exists() {
            break;
        }
        if let Some(parent) = root.parent() {
            root = parent.to_path_buf();
        }
    }
    let project_root = root;

    // Check if FastAPI is already running (e.g. started by beforeDevCommand)
    let server_already_up = ureq::get("http://127.0.0.1:8000")
        .call()
        .map(|r| r.status() < 500)
        .unwrap_or(false);

    let backend_process = if server_already_up {
        eprintln!("[Palimind] Backend already running, skipping spawn.");
        Arc::new(Mutex::new(BackendProcess(None)))
    } else {
        let python_cmd = find_python(&project_root);
        eprintln!("[Palimind] Using Python: {}", python_cmd);
        eprintln!("[Palimind] Project root: {}", project_root.display());

        // Redirect stdin/stdout/stderr to /dev/null so that when Tauri's
        // PTY disconnects the Python process never gets EIO on its stdio fds.
        let devnull_in  = File::open("/dev/null").ok().map(Stdio::from).unwrap_or_else(Stdio::null);
        let devnull_out = File::open("/dev/null").ok().map(Stdio::from).unwrap_or_else(Stdio::null);
        let devnull_err = File::open("/dev/null").ok().map(Stdio::from).unwrap_or_else(Stdio::null);

        let backend_child = Command::new(&python_cmd)
            .args(["-m", "core.api_server"])
            .current_dir(&project_root)
            .stdin(devnull_in)
            .stdout(devnull_out)
            .stderr(devnull_err)
            .spawn();

        // Wait for the server to be ready (up to ~30 s)
        eprintln!("[Palimind] Waiting for FastAPI backend…");
        let ready = wait_for_backend("http://127.0.0.1:8000", 120);
        if ready {
            eprintln!("[Palimind] Backend is ready.");
        } else {
            eprintln!("[Palimind] Backend did not respond in time — continuing anyway.");
        }

        Arc::new(Mutex::new(BackendProcess(backend_child.ok())))
    };

    let backend_for_exit = Arc::clone(&backend_process);

    // Platform-aware accelerator helpers
    let is_mac = cfg!(target_os = "macos");
    let is_linux = cfg!(target_os = "linux");
    let space_hotkey = if is_mac { "Command+Shift+Space" } else if is_linux { "Super+Shift+Space" } else { "Ctrl+Shift+Space" };
    let glance_hotkey = if is_mac { "Command+Shift+V" } else if is_linux { "Super+Shift+V" } else { "Ctrl+Shift+V" };

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .invoke_handler(tauri::generate_handler![open_glance_cmd])
        .setup(move |app| {
            let handle: AppHandle = app.handle().clone();

            // ── Global shortcuts ───────────────────────────────────────────
            let h1 = handle.clone();
            let h2 = handle.clone();

            // Unregister any stale shortcuts from a previously crashed instance
            let _ = app.global_shortcut().unregister_all();

            let shortcut_result = app.global_shortcut().on_shortcuts(
                [space_hotkey, glance_hotkey],
                move |_app, shortcut, event| {
                    if event.state() != ShortcutState::Pressed {
                        return;
                    }
                    let key = shortcut.to_string();
                    if key.contains("Space") {
                        // Toggle main window
                        if let Some(win) = h1.get_webview_window("main") {
                            if win.is_visible().unwrap_or(false) {
                                let _ = win.hide();
                            } else {
                                let _ = win.show();
                                let _ = win.set_focus();
                            }
                        }
                    } else if key.contains('V') {
                        open_glance(&h2);
                    }
                },
            );
            if let Err(e) = shortcut_result {
                eprintln!("[Palimind] Global shortcut registration failed (non-fatal): {e}");
            }

            // Create the PaliGlance popup at startup (hidden, kept alive so its
            // JS listeners are registered before the first hotkey press).
            let _ = ensure_glance_window(&handle);

            // ── Tray icon menu (works on all platforms including Wayland) ──
            let tray_h = handle.clone();
            let open_item = MenuItem::with_id(app, "open", "Open Palimind", true, None::<&str>)?;
            let capture_item = MenuItem::with_id(app, "capture", "PaliGlance", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_item, &capture_item, &quit_item])?;

            TrayIconBuilder::new()
                .menu(&menu)
                .on_menu_event(move |app, event| {
                    match event.id().as_ref() {
                        "open" => {
                            if let Some(win) = tray_h.get_webview_window("main") {
                                let _ = win.show();
                                let _ = win.set_focus();
                            }
                        }
                        "capture" => {
                            open_glance(&tray_h);
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(move |window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Only kill backend when the main window is destroyed,
                // not when the glance popup closes
                if window.label() == "main" {
                    drop(backend_for_exit.lock().unwrap());
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Palimind");
}
