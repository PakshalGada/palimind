// Palimind — Tauri 2 Main Process
//
// Responsibilities:
//  1. Spawn the FastAPI / Uvicorn backend as a child process
//  2. Poll the backend until it's ready
//  3. Open the main WebView window pointing at http://127.0.0.1:8000/ui
//  4. Register global shortcuts (platform-aware):
//       Ctrl/Cmd/Super+Shift+Space  → toggle main window (PaliSpace)
//  5. Clean up the backend on app exit

use std::fs::File;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

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
        project_root
            .join(".venv")
            .join("Scripts")
            .join("python.exe"),
        project_root.join("venv").join("Scripts").join("python.exe"),
    ];
    let mut fallbacks: Vec<String> = candidates
        .iter()
        .filter(|p| p.exists())
        .map(|p| p.to_string_lossy().into_owned())
        .collect();
    // System interpreters — verified below for backend dependencies
    fallbacks.push("python3".to_string());
    fallbacks.push("python".to_string());

    for py in &fallbacks {
        let ok = Command::new(py)
            .args(["-c", "import fastapi, uvicorn"])
            .stdin(Stdio::null())
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
        if ok {
            return py.clone();
        }
        // Direct probe failed — retry through a login shell so the user's
        // profile (mise/rbenv-style version managers, venv activation, …)
        // is applied even when launched from a desktop entry.
        let ok_login = Command::new("sh")
            .args([
                "-lc",
                &format!("command -v {py} >/dev/null && {py} -c \"import fastapi, uvicorn\""),
            ])
            .stdin(Stdio::null())
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
        if ok_login {
            return format!("sh|-lc|{}", py);
        }
        eprintln!(
            "[Palimind] Python '{}' missing backend deps, trying next…",
            py
        );
    }
    eprintln!("[Palimind] No Python with fastapi/uvicorn found — using 'python3' anyway.");
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

// ── App entry-point ──────────────────────────────────────────────────────────

fn main() {
    // Determine project root (the repo checkout that contains packages/backend)
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));

    // Walk up until we find the backend package to locate actual project root
    let mut root = exe_dir.clone();
    for _ in 0..8 {
        if root
            .join("packages")
            .join("backend")
            .join("palimind")
            .exists()
        {
            break;
        }
        if let Some(parent) = root.parent() {
            root = parent.to_path_buf();
        }
    }
    let project_root = root;
    // The Python package lives in packages/backend; running `python -m` from
    // there puts `palimind` on sys.path without requiring an install.
    let backend_root = project_root.join("packages").join("backend");

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

        // Redirect stdout/stderr to a log file so backend crashes are
        // diagnosable; stdin from /dev/null so the child never gets EIO.
        let devnull_in = File::open("/dev/null")
            .ok()
            .map(Stdio::from)
            .unwrap_or_else(Stdio::null);
        let log_path = std::env::temp_dir().join("palimind-backend.log");
        let log_file = File::create(&log_path).ok();
        let log_out = log_file
            .as_ref()
            .and_then(|f| f.try_clone().ok())
            .map(Stdio::from)
            .unwrap_or_else(Stdio::null);
        let log_err = log_file.map(Stdio::from).unwrap_or_else(Stdio::null);
        eprintln!("[Palimind] Backend log: {}", log_path.display());

        let mut backend_cmd = if python_cmd.starts_with("sh|-lc|") {
            // Login-shell resolution marker: "sh|-lc|<python>"
            let inner = python_cmd.trim_start_matches("sh|-lc|");
            let mut cmd = Command::new("sh");
            cmd.args(["-lc", &format!("exec {} -m palimind.api_server", inner)]);
            cmd
        } else {
            let mut cmd = Command::new(&python_cmd);
            cmd.args(["-m", "palimind.api_server"]);
            cmd
        };
        let backend_child = backend_cmd
            .current_dir(&backend_root)
            .stdin(devnull_in)
            .stdout(log_out)
            .stderr(log_err)
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

    // Platform-aware accelerator helper
    let is_mac = cfg!(target_os = "macos");
    let is_linux = cfg!(target_os = "linux");
    let space_hotkey = if is_mac {
        "Command+Shift+Space"
    } else if is_linux {
        "Super+Shift+Space"
    } else {
        "Ctrl+Shift+Space"
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(move |app| {
            let handle: AppHandle = app.handle().clone();

            // ── Global shortcut ──────────────────────────────────────────
            let h1 = handle.clone();

            // Unregister any stale shortcuts from a previously crashed instance
            let _ = app.global_shortcut().unregister_all();

            let shortcut_result =
                app.global_shortcut()
                    .on_shortcuts([space_hotkey], move |_app, shortcut, event| {
                        if event.state() != ShortcutState::Pressed {
                            return;
                        }
                        if shortcut.to_string().contains("Space") {
                            // Toggle main window
                            if let Some(win) = h1.get_webview_window("main") {
                                if win.is_visible().unwrap_or(false) {
                                    let _ = win.hide();
                                } else {
                                    let _ = win.show();
                                    let _ = win.set_focus();
                                }
                            }
                        }
                    });
            if let Err(e) = shortcut_result {
                eprintln!("[Palimind] Global shortcut registration failed (non-fatal): {e}");
            }

            // ── Tray icon menu (works on all platforms including Wayland) ──
            let tray_h = handle.clone();
            let open_item = MenuItem::with_id(app, "open", "Open Palimind", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_item, &quit_item])?;

            TrayIconBuilder::new()
                .menu(&menu)
                .on_menu_event(move |app, event| match event.id().as_ref() {
                    "open" => {
                        if let Some(win) = tray_h.get_webview_window("main") {
                            let _ = win.show();
                            let _ = win.set_focus();
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(move |window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    drop(backend_for_exit.lock().unwrap());
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Palimind");
}
